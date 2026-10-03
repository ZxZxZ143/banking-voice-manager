"""Canonical streaming STT framing; conversion belongs at the channel boundary."""

PCM_ENCODING = "pcm_s16le"
PCM_SAMPLE_RATE = 24_000
PCM_CHANNELS = 1
MAX_PCM_FRAME_BYTES = 4_800  # 100 ms at 24 kHz, 16 bits, mono.
PCM_BYTES_PER_SECOND = PCM_SAMPLE_RATE * PCM_CHANNELS * 2


def validate_pcm_frame(pcm: bytes | None) -> None:
    if not isinstance(pcm, bytes) or not pcm or len(pcm) > MAX_PCM_FRAME_BYTES or len(pcm) % 2:
        raise ValueError("Invalid PCM frame")
