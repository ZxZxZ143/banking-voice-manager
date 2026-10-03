from dataclasses import dataclass, field
from typing import Protocol

from pydantic import JsonValue

from app.speech.audio import PCM_CHANNELS, PCM_ENCODING, PCM_SAMPLE_RATE
from app.speech.tts.base import SpeechResult


@dataclass(frozen=True)
class ProviderAudio:
    data: bytes
    encoding: str = PCM_ENCODING
    sample_rate_hz: int = PCM_SAMPLE_RATE
    channels: int = PCM_CHANNELS


@dataclass(frozen=True)
class CallStarted:
    call_id: str
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class IncomingAudio:
    call_id: str
    audio: ProviderAudio


@dataclass(frozen=True)
class CallEnded:
    call_id: str


@dataclass(frozen=True)
class ProviderError:
    call_id: str
    # Safe application code, not raw provider error text/headers.
    code: str = "provider_error"


TelephonyEvent = CallStarted | IncomingAudio | CallEnded | ProviderError


class TelephonyProvider(Protocol):
    async def send_audio(self, call_id: str, speech: SpeechResult) -> None:
        """Return only when playback completes; cancel/close must stop pending playback.

        The adapter owns outgoing codec conversion or explicit format rejection.
        """
        ...

    async def hangup(self, call_id: str) -> None: ...

    async def close(self, call_id: str) -> None:
        """Release this call's streams/subscriptions and cancel queued output; idempotent."""
        ...
