import asyncio
import math
from time import perf_counter

from openai import AsyncOpenAI, OpenAIError

from app.speech.errors import SpeechConfigurationError, SpeechProviderError
from app.speech.tts.base import SpeechLanguage, SpeechRequest, SpeechResult


class OpenAITTSProvider:
    """Read the provider stream into one MP3 result; browser streaming is not wired."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        voice: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 1,
    ) -> None:
        if not model.strip() or not voice.strip():
            raise SpeechConfigurationError("An OpenAI speech model and voice are required.")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise SpeechConfigurationError("Speech timeout must be between 0 and 300 seconds.")
        if not 0 <= max_retries <= 3:
            raise SpeechConfigurationError("Speech retries must be between 0 and 3.")
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    async def synthesize(self, text: str, language: SpeechLanguage) -> SpeechResult:
        request = SpeechRequest(text=text, language=language)
        if not self._api_key or not self._api_key.strip():
            raise SpeechConfigurationError("Set OPENAI_API_KEY before invoking speech synthesis.")

        started = perf_counter()
        first_audio_latency_ms: float | None = None
        chunks: list[bytes] = []
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with AsyncOpenAI(
                    api_key=self._api_key,
                    timeout=self._timeout_seconds,
                    max_retries=self._max_retries,
                ) as client:
                    # Speech follows the input text. The API has no language argument.
                    async with client.audio.speech.with_streaming_response.create(
                        model=self._model,
                        voice=self._voice,
                        input=request.text,
                        response_format="mp3",
                    ) as response:
                        async for chunk in response.iter_bytes():
                            if chunk:
                                if first_audio_latency_ms is None:
                                    first_audio_latency_ms = (perf_counter() - started) * 1000
                                chunks.append(chunk)
        except (OpenAIError, TimeoutError):
            raise SpeechProviderError(
                "OpenAI speech synthesis failed; check credentials, model access, and connectivity."
            ) from None

        if not chunks:
            raise SpeechProviderError("OpenAI speech synthesis returned no audio.")
        return SpeechResult(
            audio=b"".join(chunks),
            content_type="audio/mpeg",
            language=request.language,
            first_audio_latency_ms=first_audio_latency_ms,
        )
