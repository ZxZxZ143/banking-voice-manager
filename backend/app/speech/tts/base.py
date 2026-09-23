from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

SpeechLanguage = Literal["ru", "kk", "mixed"]
MAX_SPEECH_CHARACTERS = 4_000


class SpeechRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=MAX_SPEECH_CHARACTERS)
    language: SpeechLanguage

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Speech text must not be blank.")
        return value


class SpeechResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    audio: bytes = Field(min_length=1, repr=False)
    content_type: str
    # Requested language, not an assertion about the quality/language of the audio.
    language: SpeechLanguage
    first_audio_latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class TTSProvider(Protocol):
    async def synthesize(self, text: str, language: SpeechLanguage) -> SpeechResult:
        """Synthesize speech with honest audio and timing metadata."""
        ...
