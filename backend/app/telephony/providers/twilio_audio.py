"""Real G.711 and rate conversion using PyAV's bundled FFmpeg libraries."""

import av

from app.speech.conversion import speech_to_pcm
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
    pcm = speech_to_pcm(speech, rate=8000, max_seconds=MAX_OUTPUT_SECONDS)
    frame = av.AudioFrame(format="s16", layout="mono", samples=len(pcm) // 2)
    frame.sample_rate = 8000
    frame.planes[0].update(pcm)
    encoder = av.CodecContext.create("pcm_mulaw", "w")
    encoder.sample_rate = 8000
    encoder.layout = "mono"
    encoder.format = "s16"
    return b"".join(bytes(packet) for packet in encoder.encode(frame) + encoder.encode(None))
