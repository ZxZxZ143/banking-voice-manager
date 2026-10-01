"""Real G.711 and rate conversion using PyAV's bundled FFmpeg libraries."""

from io import BytesIO

import av

from app.speech.tts.base import SpeechResult

MAX_MULAW_FRAME = 800  # 100 ms; Twilio normally sends 20 ms.
MAX_OUTPUT_SECONDS = 120


class MulawInput:
    """One resampler per listening interval; never carry echo across a reply."""

    def __init__(self):
        self.decoder = av.CodecContext.create("pcm_mulaw", "r")
        self.decoder.sample_rate = 8000
        self.decoder.layout = "mono"
        self.resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)

    def decode(self, payload: bytes) -> list[bytes]:
        if not 0 < len(payload) <= MAX_MULAW_FRAME:
            raise ValueError("Invalid mu-law frame size")
        result = []
        for frame in self.decoder.decode(av.Packet(payload)):
            for pcm in self.resampler.resample(frame):
                data = bytes(pcm.planes[0])[: pcm.samples * 2]
                result.extend(data[i : i + 4800] for i in range(0, len(data), 4800))
        return result


def speech_to_mulaw(speech: SpeechResult) -> bytes:
    """Decode actual MP3/WAV, downmix, resample, encode raw headerless G.711."""
    formats = {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav"}
    if speech.content_type not in formats or len(speech.audio) > 25_000_000:
        raise ValueError("Unsupported or oversized TTS audio")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=8000)
    encoder = av.CodecContext.create("pcm_mulaw", "w")
    encoder.sample_rate = 8000
    encoder.layout = "mono"
    encoder.format = "s16"
    output = bytearray()
    samples = 0

    def encode(frames):
        nonlocal samples
        for frame in frames:
            samples += frame.samples
            if samples > MAX_OUTPUT_SECONDS * 8000:
                raise ValueError("TTS audio duration exceeds limit")
            for packet in encoder.encode(frame):
                output.extend(bytes(packet))

    with av.open(BytesIO(speech.audio), format=formats[speech.content_type]) as container:
        if len(container.streams.audio) != 1:
            raise ValueError("Expected one audio stream")
        for frame in container.decode(audio=0):
            encode(resampler.resample(frame))
        encode(resampler.resample(None))
    for packet in encoder.encode(None):
        output.extend(bytes(packet))
    if not output:
        raise ValueError("TTS produced no phone audio")
    return bytes(output)
