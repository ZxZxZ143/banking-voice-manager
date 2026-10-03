"""Offline Twilio adapter smoke. Agent/STT/TTS are explicit fixtures, no calls/APIs."""

import asyncio
import base64
import json

from app.core.config import Settings
from app.telephony.bench import FakePhoneTTS, ScriptedPhoneSTT
from app.telephony.providers.twilio import TwilioTelephonyProvider
from app.telephony.runtime import PhoneRuntime
from app.telephony.twilio_gateway import TwilioGateway
from fastapi import WebSocketDisconnect
from pydantic import SecretStr

CALL = "CA" + "2" * 32
STREAM = "MZ" + "3" * 32
ACCOUNT = "AC" + "1" * 32


class FixtureAgent:
    def __init__(self):
        self.turns = 0

    async def process(self, session_id, text, *, channel="voice"):
        self.turns += 1
        assert channel == "voice"
        return {
            "session_id": session_id,
            "response_text": "[MOCK] Телефонный ответ",
            "conversation_status": "awaiting_user",
        }


class FixtureSocket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.outgoing = []
        self.closed = False

    async def receive_text(self):
        message = await self.incoming.get()
        if message is None:
            raise WebSocketDisconnect()
        return json.dumps(message)

    async def send_json(self, message):
        self.outgoing.append(message)

    async def close(self, code=1000):
        self.closed = True
        self.incoming.put_nowait(None)


async def wait_for(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


async def main():
    provider, stt = TwilioTelephonyProvider(), ScriptedPhoneSTT()
    runtime = PhoneRuntime(FixtureAgent(), stt, FakePhoneTTS(), provider)
    gateway = TwilioGateway(
        Settings(
            _env_file=None,
            twilio_account_sid=ACCOUNT,
            twilio_auth_token=SecretStr("offline-fixture-token"),
            public_base_url="https://offline.example.test",
        ),
        runtime,
        provider,
    )
    socket = FixtureSocket()
    gateway.admit(CALL)
    task = asyncio.create_task(gateway.serve(socket))
    try:
        socket.incoming.put_nowait(
            {"event": "connected", "protocol": "Call", "version": "1.0.0"}
        )
        socket.incoming.put_nowait(
            {
                "event": "start",
                "sequenceNumber": "1",
                "streamSid": STREAM,
                "start": {
                    "accountSid": ACCOUNT,
                    "callSid": CALL,
                    "streamSid": STREAM,
                    "tracks": ["inbound"],
                    "mediaFormat": {
                        "encoding": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "channels": 1,
                    },
                },
            }
        )
        await wait_for(lambda: runtime.registry.get(CALL) is not None)
        session = runtime.registry.get(CALL)
        socket.incoming.put_nowait(
            {
                "event": "media",
                "sequenceNumber": "2",
                "streamSid": STREAM,
                "media": {
                    "track": "inbound",
                    "chunk": "1",
                    "timestamp": "0",
                    "payload": base64.b64encode(bytes([255]) * 160).decode(),
                },
            }
        )
        await wait_for(lambda: bool(stt.frames))
        await runtime.finish_utterance(CALL)
        await wait_for(lambda: any(m["event"] == "mark" for m in socket.outgoing))
        assert session.status == "speaking"
        mark = next(m for m in socket.outgoing if m["event"] == "mark")
        socket.incoming.put_nowait(
            {
                "event": "mark",
                "sequenceNumber": "3",
                "streamSid": STREAM,
                "mark": mark["mark"],
            }
        )
        await wait_for(lambda: session.status == "active")
        socket.incoming.put_nowait(
            {
                "event": "stop",
                "sequenceNumber": "4",
                "streamSid": STREAM,
                "stop": {"accountSid": ACCOUNT, "callSid": CALL},
            }
        )
        await task
        assert runtime.agent.messages.turns == 1
        assert not provider.streams and runtime.registry.get(CALL) is None
        assert any(m["event"] == "clear" for m in socket.outgoing)
        print(
            json.dumps(
                {
                    "mode": "OFFLINE MOCK — no PSTN call, live STT/Agent or speech synthesis",
                    "channel": session.channel,
                    "session_id": session.session_id,
                    "input": "real mu-law 8kHz decode + PCM16LE 24kHz resample",
                    "output": "real silent WAV decode + raw mu-law 8kHz encode",
                    "playback": "fixture mark acknowledged, listening resumed",
                    "cleaned_up": socket.closed,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await gateway.shutdown()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
