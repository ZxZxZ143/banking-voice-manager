"""Offline mock call accepted → signed answer → L16/STT/Agent/TTS → two turns → close."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.config import Settings
from app.telephony.bench import FakePhoneTTS, ScriptedPhoneSTT
from app.telephony.providers.vonage import VonageTelephonyProvider
from app.telephony.providers.vonage_audio import CONTENT_TYPE
from app.telephony.providers.vonage_messages import Answer
from app.telephony.runtime import PhoneRuntime
from app.telephony.vonage_calls import validate_private_key
from app.telephony.vonage_gateway import VonageGateway
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

CALL = "11111111-2222-3333-4444-555555555555"
FROM = "123456789"
TO = "447700900001"


class FixtureAgent:
    def __init__(self):
        self.sessions = []

    async def process(self, session_id, text, *, channel="voice"):
        self.sessions.append(session_id)
        return {
            "session_id": session_id,
            "response_text": "[MOCK] Тестовый ответ",
            "conversation_status": "awaiting_user",
        }


class FixtureSocket:
    def __init__(self):
        self.input = asyncio.Queue()
        self.binary = []
        self.controls = []
        self.closed = False

    async def receive(self):
        packet = await self.input.get()
        if packet is None:
            return {"type": "websocket.disconnect"}
        if isinstance(packet, bytes):
            return {"type": "websocket.receive", "bytes": packet}
        return {"type": "websocket.receive", "text": json.dumps(packet)}

    async def send_bytes(self, packet):
        self.binary.append(packet)

    async def send_json(self, control):
        self.controls.append(control)

    async def close(self, code=1000):
        self.closed = True
        self.input.put_nowait(None)


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


async def main():
    with TemporaryDirectory(prefix="veyra-vonage-smoke-") as directory:
        path = Path(directory) / "private.key"
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        settings = Settings(
            _env_file=None,
            vonage_enabled=True,
            vonage_application_id="aaaaaaaa-bbbb-cccc-dddd-0123456789ab",
            vonage_private_key_path=path,
            vonage_api_key="offline-fixture-key",
            vonage_signature_secret=SecretStr("offline-fixture-signature-secret"),
            vonage_test_from_number=FROM,
            vonage_test_to_number=TO,
            public_base_url="https://offline.example.test",
        )
        validate_private_key(settings)
        provider, stt, agent = (
            VonageTelephonyProvider(),
            ScriptedPhoneSTT(),
            FixtureAgent(),
        )
        runtime = PhoneRuntime(agent, stt, FakePhoneTTS(), provider)
        gateway, socket = VonageGateway(settings, runtime, provider), FixtureSocket()
        ncco = gateway.answer(
            Answer.model_validate({"uuid": CALL, "from": FROM, "to": TO})
        )
        assert ncco[0]["endpoint"][0]["content-type"] == CONTENT_TYPE
        task = asyncio.create_task(gateway.serve(socket))
        try:
            socket.input.put_nowait(
                {
                    "event": "websocket:connected",
                    "call_uuid": CALL,
                    "content-type": CONTENT_TYPE,
                }
            )
            await until(lambda: runtime.registry.get(CALL) is not None)
            session = runtime.registry.get(CALL)
            for index in range(2):
                socket.input.put_nowait(bytes(640))
                await until(lambda count=index + 1: len(stt.frames) == count)
                await runtime.finish_utterance(CALL)
                await until(
                    lambda count=index + 1: (
                        sum(m["action"] == "notify" for m in socket.controls) == count
                    )
                )
                assert session.status == "speaking"
                notify = [m for m in socket.controls if m["action"] == "notify"][-1]
                socket.input.put_nowait(
                    {"event": "websocket:notify", "payload": notify["payload"]}
                )
                await until(lambda: session.status == "active")
            assert len(agent.sessions) == 2 and len(set(agent.sessions)) == 1
            assert all(
                len(frame) == 640 and not frame.startswith(b"RIFF")
                for frame in socket.binary
            )
            socket.input.put_nowait(None)
            await task
            assert not provider.streams and runtime.registry.get(CALL) is None
            print(
                json.dumps(
                    {
                        "mode": "OFFLINE MOCK — no real phone/API/STT/Agent/TTS requests",
                        "call_requests": 0,
                        "session_id": session.session_id,
                        "same_session_turns": len(agent.sessions),
                        "input": "real L16 16k→24k resample",
                        "output": "real WAV→raw L16 16k decode/resample",
                        "playback": "two fixture notifications acknowledged",
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
