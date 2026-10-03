"""One streaming result and at most one bounded second pass. Audio never persists."""

import asyncio
import io
import wave
from collections import OrderedDict
from dataclasses import dataclass, field
from hashlib import sha256
from time import monotonic, perf_counter
from typing import Literal
from uuid import uuid4

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from app.speech.audio import PCM_BYTES_PER_SECOND, PCM_SAMPLE_RATE
from app.speech.structured.context import ExpectedKind, TranscriptionContext
from app.speech.structured.normalization import recognize_expected


class RecognitionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["streaming", "structured"]
    expected_kind: ExpectedKind
    first_pass_valid: bool
    second_pass_used: bool
    second_pass_failed: bool = False
    candidate_count: int = Field(ge=0, le=65)
    accepted: bool
    first_pass_ms: float = Field(default=0, ge=0, allow_inf_nan=False)
    second_pass_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)


@dataclass(frozen=True)
class RecognitionOutcome:
    metadata: RecognitionMetadata
    kind: str
    value: str | None = field(default=None, repr=False)


class BoundedTranscriber:
    def __init__(self, api_key: str, model: str = "gpt-transcribe"):
        self.api_key = api_key
        self.model = model

    async def transcribe(self, pcm: bytes, context: TranscriptionContext) -> str:
        if not 0 < len(pcm) <= PCM_BYTES_PER_SECOND * 120 or len(pcm) % 2:
            raise ValueError("Invalid bounded transcription audio")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setparams((1, 2, PCM_SAMPLE_RATE, 0, "NONE", "not compressed"))
            wav.writeframes(pcm)
        async with asyncio.timeout(20):
            async with AsyncOpenAI(api_key=self.api_key, timeout=20, max_retries=0) as client:
                result = await client.audio.transcriptions.create(
                    model=self.model,
                    file=("utterance.wav", buffer.getvalue(), "audio/wav"),
                    response_format="json",
                    prompt=context.prompt,
                    keywords=list(context.keywords),
                    languages=["ru", "kk"],
                )
        if not isinstance(result.text, str) or len(result.text) > 10000:
            raise ValueError("Invalid bounded transcription result")
        return result.text


async def resolve_recognition(text, pcm, context, second_pass=None, first_pass_ms=0):
    first = recognize_expected(text, context.expected_kind)
    final = first
    used = False
    failed = False
    second_ms = None
    if context.expected_kind != "none" and not first.accepted and pcm and second_pass:
        used = True
        started = perf_counter()
        try:
            async with asyncio.timeout(20):
                second_text = await second_pass.transcribe(pcm, context)
            second = recognize_expected(second_text, context.expected_kind)
            # A second pass may resolve an invalid length, but cannot override an
            # explicit ambiguity with an unrelated valid-looking identifier.
            if first.candidates and second.accepted and second.value not in first.candidates:
                final = first
            else:
                final = second
        except (OpenAIError, TimeoutError, ValueError):
            failed = True  # Allowlisted failure flag; never provider payload/audio.
        second_ms = (perf_counter() - started) * 1000
    return RecognitionOutcome(
        RecognitionMetadata(
            mode="streaming" if context.expected_kind == "none" else "structured",
            expected_kind=context.expected_kind,
            first_pass_valid=first.accepted,
            second_pass_used=used,
            second_pass_failed=failed,
            candidate_count=65 if final.overflow else len(final.candidates),
            accepted=final.accepted,
            first_pass_ms=first_pass_ms,
            second_pass_ms=second_ms,
        ),
        kind=final.kind,
        value=final.value,
    )


@dataclass(frozen=True)
class _Receipt:
    session_id: str
    turn: int
    expected_slot: str
    text_hash: str
    outcome: RecognitionOutcome
    expires: float


class RecognitionReceipts:
    """Bounded one-use private results. No audio/transcript, persistence or logging."""

    def __init__(self):
        self._items = OrderedDict()

    def _prune(self):
        now = monotonic()
        for key in list(self._items):
            if self._items[key].expires <= now:
                del self._items[key]

    def put(self, session_id, turn, slot, text, outcome):
        self._prune()
        while len(self._items) >= 100:
            self._items.popitem(last=False)
        token = str(uuid4())
        self._items[token] = _Receipt(
            session_id,
            turn,
            slot,
            sha256(text.strip().encode()).hexdigest(),
            outcome,
            monotonic() + 120,
        )
        return token

    def take(self, token, session_id, turn, slot, text):
        self._prune()
        receipt = self._items.get(token)
        if receipt is None or (
            receipt.session_id,
            receipt.turn,
            receipt.expected_slot,
            receipt.text_hash,
        ) != (session_id, turn, slot, sha256(text.strip().encode()).hexdigest()):
            return None
        del self._items[token]
        return receipt.outcome
