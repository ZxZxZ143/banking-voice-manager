from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Application upload budget; audio decoding remains the provider's responsibility.
MAX_AUDIO_BYTES = 25_000_000


class AudioInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    audio: bytes = Field(min_length=1, max_length=MAX_AUDIO_BYTES, repr=False)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)

    @field_validator("filename", "content_type")
    @classmethod
    def nonblank_metadata(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Audio filename and content type must not be blank.")
        return value


class TranscriptionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    # Preserve the provider's language label; do not guess a language from script.
    detected_language: str | None = None
    duration: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)


class STTProvider(Protocol):
    async def transcribe(self, audio: AudioInput) -> TranscriptionResult:
        """Transcribe recorded audio; duration, when present, is in seconds."""
        ...
