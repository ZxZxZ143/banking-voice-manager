from typing import Protocol

from app.speech.audio import PCM_CHANNELS, PCM_ENCODING, PCM_SAMPLE_RATE, validate_pcm_frame
from app.telephony.base import ProviderAudio


class AudioNormalizer(Protocol):
    def normalize(self, audio: ProviderAudio) -> bytes:
        """Produce canonical mono PCM16LE/24kHz frames; do not relabel unsupported codecs."""
        ...


class PcmPassThroughNormalizer:
    """Only canonical PCM is implemented. No mu-law, A-law, resampling or decoding."""

    def normalize(self, audio: ProviderAudio) -> bytes:
        if (audio.encoding, audio.sample_rate_hz, audio.channels) != (
            PCM_ENCODING,
            PCM_SAMPLE_RATE,
            PCM_CHANNELS,
        ):
            raise ValueError("Unsupported phone audio format; implement provider normalization")
        validate_pcm_frame(audio.data)
        return audio.data
