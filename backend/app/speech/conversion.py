"""Bounded real TTS container decoding shared by server phone output adapters."""

from io import BytesIO

import av

from app.speech.tts.base import SpeechResult


def speech_to_pcm(speech: SpeechResult, *, rate: int, max_seconds: int = 120) -> bytes:
    formats = {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav"}
    if speech.content_type not in formats or len(speech.audio) > 25_000_000:
        raise ValueError("Unsupported or oversized TTS audio")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    output = bytearray()

    def append(frames):
        for frame in frames:
            if len(output) + frame.samples * 2 > max_seconds * rate * 2:
                raise ValueError("TTS audio duration exceeds limit")
            output.extend(bytes(frame.planes[0])[: frame.samples * 2])

    with av.open(BytesIO(speech.audio), format=formats[speech.content_type]) as container:
        if len(container.streams.audio) != 1:
            raise ValueError("Expected one audio stream")
        for frame in container.decode(audio=0):
            append(resampler.resample(frame))
        append(resampler.resample(None))
    if not output:
        raise ValueError("TTS produced no audio")
    return bytes(output)
