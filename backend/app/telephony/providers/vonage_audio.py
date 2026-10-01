"""Vonage's Voice WebSocket L16 is signed little-endian PCM, mono 16kHz."""

import av

from app.speech.conversion import speech_to_pcm
from app.speech.tts.base import SpeechResult

CONTENT_TYPE = "audio/l16;rate=16000"
FRAME_BYTES = 640  # 20ms, 320 int16 samples


class L16Input:
    def __init__(self):
        self.resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)

    def decode(self, payload: bytes) -> list[bytes]:
        if not payload or len(payload) % 2 or len(payload) > 3200:
            raise ValueError("Invalid L16 frame")
        frame = av.AudioFrame(format="s16", layout="mono", samples=len(payload) // 2)
        frame.sample_rate = 16000
        frame.planes[0].update(payload)
        output = []
        for pcm in self.resampler.resample(frame):
            data = bytes(pcm.planes[0])[: pcm.samples * 2]
            output.extend(data[i : i + 4800] for i in range(0, len(data), 4800))
        return output


def speech_to_l16(speech: SpeechResult) -> bytes:
    return speech_to_pcm(speech, rate=16000, max_seconds=60)
