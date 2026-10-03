import asyncio
import math
from time import perf_counter

from openai import AsyncOpenAI, OpenAIError

from app.speech.errors import SpeechConfigurationError, SpeechProviderError
from app.speech.tts.base import SpeechLanguage, SpeechRequest, SpeechResult
from app.speech.tts.normalization import prepare_speech


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
        instructions_ru: str | None = None,
        instructions_kk: str | None = None,
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
        self._instructions = {"ru": instructions_ru, "kk": instructions_kk}
        self._active = 0

    async def synthesize(self, text: str, language: SpeechLanguage) -> SpeechResult:
        request = SpeechRequest(text=text, language=language)
        if not self._api_key or not self._api_key.strip():
            raise SpeechConfigurationError("Set OPENAI_API_KEY before invoking speech synthesis.")
        speech_text = prepare_speech(request.text, request.language)
        if not speech_text or len(speech_text) > 4000:
            raise SpeechProviderError("Prepared speech exceeds the synthesis limit.")
        if self._active >= 2:
            raise SpeechProviderError("Speech synthesis is busy.")

        started = perf_counter()
        first_audio_latency_ms: float | None = None
        chunks: list[bytes] = []
        audio_size = 0
        instructions = self._instructions.get(request.language)
        options = (
            {"instructions": instructions}
            if instructions and self._model not in {"tts-1", "tts-1-hd"}
            else {}
        )
        self._active += 1
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
                        input=speech_text,
                        response_format="mp3",
                        **options,
                    ) as response:
                        async for chunk in response.iter_bytes():
                            if chunk:
                                audio_size += len(chunk)
                                if audio_size > 8_000_000:
                                    raise SpeechProviderError(
                                        "Speech audio exceeds the response limit."
                                    )
                                if first_audio_latency_ms is None:
                                    first_audio_latency_ms = (perf_counter() - started) * 1000
                                chunks.append(chunk)
        except (OpenAIError, TimeoutError):
            raise SpeechProviderError(
                "OpenAI speech synthesis failed; check credentials, model access, and connectivity."
            ) from None
        finally:
            self._active -= 1

        if not chunks:
            raise SpeechProviderError("OpenAI speech synthesis returned no audio.")
        return SpeechResult(
            audio=b"".join(chunks),
            content_type="audio/mpeg",
            language=request.language,
            first_audio_latency_ms=first_audio_latency_ms,
        )
