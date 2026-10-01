"""Explicit offline fixtures, never automatically substituted for live failures."""

import io
import wave

from app.speech.stt.streaming import EmitEvent, ReceiveInput
from app.speech.tts.base import SpeechLanguage, SpeechRequest, SpeechResult


class FakePhoneTTS:
    """A deterministic 100 ms silent WAV, NOT synthesized Russian/Kazakh speech."""

    def __init__(self):
        self.requests: list[SpeechRequest] = []

    async def synthesize(self, text: str, language: SpeechLanguage) -> SpeechResult:
        request = SpeechRequest(text=text, language=language)
        self.requests.append(request)
        audio = io.BytesIO()
        with wave.open(audio, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(bytes(4800))
        return SpeechResult(audio=audio.getvalue(), content_type="audio/wav", language=language)


class ScriptedPhoneSTT:
    """On manual finish emit an explicitly scripted final; does not transcribe audio."""

    def __init__(self, text: str = "[MOCK] Тестовый вопрос", language: str = "ru"):
        self.text = text
        self.language = language
        self.frames: list[bytes] = []

    async def run(self, receive: ReceiveInput, emit: EmitEvent) -> None:
        while True:
            packet = await receive()
            if packet.kind == "cancel":
                return
            if packet.kind == "audio":
                self.frames.append(packet.audio)
                await emit({"type": "transcript.partial", "delta": "[MOCK]"})
            elif packet.kind == "finish":
                await emit(
                    {"type": "utterance.final", "text": self.text, "language": self.language}
                )
                return
