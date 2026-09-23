import asyncio
import math
from time import perf_counter

from openai import AsyncOpenAI, OpenAIError

from app.speech.errors import SpeechConfigurationError, SpeechProviderError
from app.speech.stt.base import AudioInput, TranscriptionResult


class OpenAISTTProvider:
    """Minimal recorded-audio adapter; live streaming and quality evals come later."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 1,
    ) -> None:
        if not model.strip():
            raise SpeechConfigurationError("An OpenAI transcription model is required.")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise SpeechConfigurationError("Speech timeout must be between 0 and 300 seconds.")
        if not 0 <= max_retries <= 3:
            raise SpeechConfigurationError("Speech retries must be between 0 and 3.")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    async def transcribe(self, audio: AudioInput) -> TranscriptionResult:
        if not self._api_key or not self._api_key.strip():
            raise SpeechConfigurationError("Set OPENAI_API_KEY before invoking transcription.")

        started = perf_counter()
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with AsyncOpenAI(
                    api_key=self._api_key,
                    timeout=self._timeout_seconds,
                    max_retries=self._max_retries,
                ) as client:
                    result = await client.audio.transcriptions.create(
                        model=self._model,
                        file=(audio.filename, audio.audio, audio.content_type),
                        response_format="json",
                    )
        except (OpenAIError, TimeoutError):
            raise SpeechProviderError(
                "OpenAI transcription failed; check credentials, model access, and connectivity."
            ) from None

        return TranscriptionResult(
            text=result.text,
            detected_language=getattr(result, "language", None),
            duration=getattr(result, "duration", None),
            latency_ms=(perf_counter() - started) * 1000,
        )
