"""Offline phone flow: all Agent/STT/TTS/telephony outputs are explicit fixtures."""

import asyncio
import json

from app.telephony.base import CallStarted, ProviderAudio
from app.telephony.bench import FakePhoneTTS, ScriptedPhoneSTT
from app.telephony.providers.mock import MockTelephonyProvider
from app.telephony.runtime import PhoneRuntime


class FixtureAgent:
    def __init__(self):
        self.turns = 0

    async def process(self, session_id: str, text: str, *, channel="voice") -> dict:
        self.turns += 1
        assert channel == "voice"
        return {
            "session_id": session_id,
            "response_text": "[MOCK] Ответ для проверки телефонного потока.",
            "conversation_status": "awaiting_user",
        }


async def main() -> None:
    provider = MockTelephonyProvider()
    runtime = PhoneRuntime(FixtureAgent(), ScriptedPhoneSTT(), FakePhoneTTS(), provider)
    session = runtime.start_call(CallStarted("offline-call", {"mode": "mock"}))
    try:
        # Exercise audio normalization + scripted STT; final transcript admission runs once.
        await runtime.feed_audio("offline-call", ProviderAudio(bytes(4800)))
        await runtime.finish_utterance("offline-call")
        async with asyncio.timeout(2):
            while not provider.outgoing["offline-call"]:
                await asyncio.sleep(0)
        # Second completed input in the same call, bypassing STT for development.
        await runtime.handle_transcript(
            "offline-call",
            {
                "type": "utterance.final",
                "text": "[MOCK] Второй вопрос",
                "language": "kk",
            },
        )
    finally:
        await runtime.shutdown()
    assert runtime.agent.messages.turns == 2
    assert len(provider.outgoing["offline-call"]) == 2
    assert runtime.registry.get("offline-call") is None
    print(
        json.dumps(
            {
                "mode": "MOCK — no real calls, transcription, Agent routing or speech",
                "channel": session.channel,
                "session_id": session.session_id,
                "outgoing_audio_count": len(provider.outgoing["offline-call"]),
                "output_format": "audio/wav (silent fixture)",
                "cleaned_up": "offline-call" in provider.closed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
