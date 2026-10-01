from collections import defaultdict

from app.speech.tts.base import SpeechResult


class MockTelephonyProvider:
    """Offline sink only. No telephone network, codec conversion or actual playback."""

    def __init__(self):
        self.outgoing: dict[str, list[SpeechResult]] = defaultdict(list)
        self.hung_up: set[str] = set()
        self.closed: set[str] = set()

    async def send_audio(self, call_id: str, speech: SpeechResult) -> None:
        if call_id in self.closed:
            raise RuntimeError("Cannot send to a closed mock call")
        self.outgoing[call_id].append(speech.model_copy(deep=True))

    async def hangup(self, call_id: str) -> None:
        self.hung_up.add(call_id)

    async def close(self, call_id: str) -> None:
        self.closed.add(call_id)
