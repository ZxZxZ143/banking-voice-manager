"""Per-connection Silero speech detection; no Whisper transcription is loaded."""


class PauseTracker:
    def __init__(self, pause_ms: int):
        self.pause_ms = pause_ms
        self.elapsed_ms = 0
        self.last_speech_ms = 0
        self.speech_run_ms = 0
        self.has_speech = False

    def step(self, speech: bool, frame_ms: int = 32) -> bool:
        self.elapsed_ms += frame_ms
        if speech:
            self.speech_run_ms += frame_ms
            self.last_speech_ms = self.elapsed_ms
            if self.speech_run_ms >= 96:
                self.has_speech = True
        else:
            self.speech_run_ms = 0
        return self.has_speech and self.silence_ms >= self.pause_ms

    @property
    def silence_ms(self):
        return max(0, self.elapsed_ms - self.last_speech_ms)


class SpeechEndDetector:
    def __init__(self, pause_ms: int):
        import av
        import numpy as np
        from faster_whisper.vad import get_vad_model

        self.np = np
        self.av = av
        self.model = get_vad_model()
        self.resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
        self.pending = np.empty(0, dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.tracker = PauseTracker(pause_ms)

    def feed(self, pcm: bytes):
        samples = self.np.frombuffer(pcm, dtype="<i2").reshape(1, -1)
        frame = self.av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = 24000
        for converted in self.resampler.resample(frame):
            self.pending = self.np.concatenate((self.pending, converted.to_ndarray().ravel()))
        ended = False
        probability = 0.0
        while self.pending.size >= 512:
            block, self.pending = self.pending[:512], self.pending[512:]
            values = self.np.concatenate((self.context, block.reshape(1, -1)), axis=1)
            output, self.h, self.c = self.model.session.run(
                None, {"input": values, "h": self.h, "c": self.c}
            )
            self.context = block[-64:].reshape(1, -1)
            probability = float(output.ravel()[-1])
            ended = self.tracker.step(probability >= 0.5)
        return ended, probability
