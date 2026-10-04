"""Two bounded hypotheses and an application-owned admission decision. No audio persists."""

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
from app.speech.structured.capture import phone_style, recognize_context
from app.speech.structured.context import ExpectedKind, PhoneInputStyle, TranscriptionContext
from app.speech.structured.policy import (
    AcceptedStructuredValue,
    RecognitionHypothesis,
    RecognitionOutcome,
    RecognitionRisk,
    StructuredRecognitionPolicy,
)


class RecognitionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["streaming", "structured"]
    expected_kind: ExpectedKind
    first_pass_valid: bool
    second_pass_used: bool
    second_pass_failed: bool = False
    candidate_count: int = Field(ge=0, le=65)
    accepted: bool
    outcome: RecognitionOutcome = RecognitionOutcome.repair_required
    risk: RecognitionRisk = RecognitionRisk.low
    consensus: bool = False
    verification_method: (
        Literal["low_risk_schema", "customer_confirmation", "manual_entry"] | None
    ) = None
    first_pass_ms: float = Field(default=0, ge=0, allow_inf_nan=False)
    second_pass_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    second_pass_wait_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    candidate_ready_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    realtime_final_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    bounded_final_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    readback_source: Literal["realtime", "bounded"] | None = None
    loser_cancelled: bool = False
    segment_evidence: Literal["agreement", "single", "conflict", "unusable"] | None = None


@dataclass(frozen=True)
class RecognitionResult:
    metadata: RecognitionMetadata
    kind: str
    accepted_value: AcceptedStructuredValue | None = field(default=None, repr=False)
    candidate: RecognitionHypothesis | None = field(default=None, repr=False)
    phone_input_style: PhoneInputStyle | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.metadata.accepted != (self.accepted_value is not None):
            raise ValueError("Acceptance requires a typed verified value")
        if self.accepted_value and (
            self.accepted_value.kind != self.kind
            or self.metadata.outcome != RecognitionOutcome.accepted
        ):
            raise ValueError("Inconsistent recognition verification")

    @property
    def value(self):
        return self.accepted_value.canonical_value if self.accepted_value else None


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


@dataclass(frozen=True)
class BoundedHypothesis:
    hypothesis: RecognitionHypothesis = field(repr=False)
    failed: bool
    elapsed_ms: float
    text: str = field(default="", repr=False)


async def bounded_hypothesis(pcm, context, second_pass):
    """One attempt; the deadline starts at launch, even while Realtime is pending."""
    started = perf_counter()
    text = ""
    try:
        async with asyncio.timeout(20):
            text = await second_pass.transcribe(pcm, context)
        parsed = recognize_context(text, context)
        hypothesis = RecognitionHypothesis.from_normalized("bounded", parsed)
        failed = False
    except (OpenAIError, TimeoutError, ValueError):
        failed = True
        hypothesis = RecognitionHypothesis(
            "bounded", context.expected_kind, None, False, "unavailable"
        )
    return BoundedHypothesis(hypothesis, failed, (perf_counter() - started) * 1000, text)


def pending_readback(
    hypothesis, *, elapsed_ms, first=None, second=None, second_used=False, first_final_ms=None
):
    """Race winner authorizes a full read-back only. Never business-slot admission.

    A completed loser can corroborate metadata but cannot replace the winner. A
    pending loser is cancelled by the relay: another paid result cannot supersede
    what the customer heard and adds no acceptance authority.
    """
    decision = StructuredRecognitionPolicy().decide(hypothesis.kind, hypothesis)
    if decision.outcome != RecognitionOutcome.confirmation_required:
        raise ValueError("Read-back race requires one unique sensitive hypothesis")
    corroborated = bool(
        first
        and second
        and first.valid_schema
        and second.hypothesis.valid_schema
        and first.kind == second.hypothesis.kind
        and first.canonical_candidate == second.hypothesis.canonical_candidate
    )
    return RecognitionResult(
        RecognitionMetadata(
            mode="structured",
            expected_kind=hypothesis.kind,
            first_pass_valid=bool(first and first.valid_schema),
            second_pass_used=second_used,
            second_pass_failed=bool(second and second.failed),
            candidate_count=1,
            accepted=False,
            outcome=decision.outcome,
            risk=decision.risk,
            consensus=corroborated,
            candidate_ready_ms=elapsed_ms,
            realtime_final_ms=first_final_ms,
            bounded_final_ms=second.elapsed_ms if second else None,
            first_pass_ms=first_final_ms or 0,
            second_pass_ms=second.elapsed_ms if second else None,
            second_pass_wait_ms=0,
            readback_source=hypothesis.source,
            loser_cancelled=not (first and second),
        ),
        kind=hypothesis.kind,
        candidate=hypothesis,
    )


async def resolve_recognition(
    text, pcm, context, second_pass=None, first_pass_ms=0, *, second_task=None
):
    first = recognize_context(text, context)
    hypothesis = RecognitionHypothesis.from_normalized("realtime", first)
    policy = StructuredRecognitionPolicy()
    second = None
    used = second_task is not None
    failed = False
    second_ms = None
    waited_ms = None
    if (
        second_task is None
        and context.expected_kind != "none"
        and pcm
        and second_pass
        and (policy.requires_consensus(context.expected_kind) or not first.accepted)
    ):
        second_task = asyncio.create_task(bounded_hypothesis(pcm, context, second_pass))
    if second_task is not None:
        used = True
        wait_started = perf_counter()
        result = await second_task
        waited_ms = (perf_counter() - wait_started) * 1000
        second, failed, second_ms = result.hypothesis, result.failed, result.elapsed_ms
    decision = (
        policy.decide_segment(context.expected_kind, hypothesis, second)
        if context.capture_part != "whole"
        else policy.decide(context.expected_kind, hypothesis, second)
    )
    styles = {
        phone_style(h.spoken_candidate)
        for h in (hypothesis, second)
        if h and h.kind == "phone" and h.spoken_candidate
    }
    return RecognitionResult(
        RecognitionMetadata(
            mode="streaming" if context.expected_kind == "none" else "structured",
            expected_kind=context.expected_kind,
            first_pass_valid=first.accepted,
            second_pass_used=used,
            second_pass_failed=failed,
            candidate_count=65 if first.overflow else len(first.candidates),
            accepted=decision.accepted_value is not None,
            outcome=decision.outcome,
            risk=decision.risk,
            consensus=decision.consensus,
            segment_evidence=decision.segment_evidence,
            verification_method=(
                decision.accepted_value.verification_method if decision.accepted_value else None
            ),
            first_pass_ms=first_pass_ms,
            second_pass_ms=second_ms,
            second_pass_wait_ms=waited_ms,
        ),
        kind=(decision.accepted_value or decision.candidate or hypothesis).kind,
        accepted_value=decision.accepted_value,
        candidate=decision.candidate,
        phone_input_style=next(iter(styles)) if len(styles) == 1 else None,
    )


@dataclass(frozen=True)
class _Receipt:
    session_id: str
    turn: int
    expected_slot: str
    text_hash: str
    outcome: RecognitionResult
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
