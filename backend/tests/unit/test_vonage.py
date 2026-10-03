"""Offline Vonage SDK/protocol/audio/auth checks. No live phone or OpenAI requests."""

import asyncio
import hashlib
import io
import json
import logging
import struct
import threading
import time
import wave
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.main import create_app
from app.speech.tts.base import SpeechResult
from app.telephony.bench import FakePhoneTTS, ScriptedPhoneSTT
from app.telephony.providers.vonage import PlaybackCancelled, VonageTelephonyProvider
from app.telephony.providers.vonage_audio import CONTENT_TYPE, L16Input
from app.telephony.providers.vonage_messages import Answer, CallEvent
from app.telephony.runtime import PhoneRuntime
from app.telephony.vonage_calls import (
    ANSWER_PATH,
    EVENTS_PATH,
    MEDIA_PATH,
    VonageConfigurationError,
    validate_private_key,
)
from app.telephony.vonage_gateway import VonageGateway, build_vonage_gateway

APP = "aaaaaaaa-bbbb-cccc-dddd-0123456789ab"
CALL = "11111111-2222-3333-4444-555555555555"
OTHER = "aaaaaaaa-1111-2222-3333-444444444444"
FROM = "123456789"
TO = "447700900001"  # synthetic reserved example
SIGNATURE_SECRET = "offline-only-signature-secret-12345"
BASE = "https://voice.example.test"


def config(**overrides):
    values = dict(
        _env_file=None,
        vonage_application_id=APP,
        vonage_api_key="offline-api-key",
        vonage_signature_secret=SecretStr(SIGNATURE_SECRET),
        vonage_test_from_number=FROM,
        vonage_test_to_number=TO,
        public_base_url=BASE,
    )
    return Settings(**(values | overrides))


def token(body=None, **overrides):
    claims = {
        "iss": "Vonage",
        "iat": int(time.time()),
        "jti": uuid4().hex,
        "api_key": "offline-api-key",
        "application_id": APP,
    }
    if body is not None:
        claims["payload_hash"] = hashlib.sha256(body).hexdigest()
    claims.update(overrides)
    return "Bearer " + jwt.encode(claims, SIGNATURE_SECRET, algorithm="HS256")


def answer(call=CALL):
    return Answer.model_validate({"uuid": call, "from": FROM, "to": TO})


def connected(call=CALL):
    return {"event": "websocket:connected", "content-type": CONTENT_TYPE, "call_uuid": call}


class Agent:
    def __init__(self, status="awaiting_user"):
        self.requests = []
        self.status = status

    async def process(self, session_id, text, *, channel="voice"):
        assert channel == "voice"
        self.requests.append((session_id, text))
        return {
            "session_id": session_id,
            "response_text": "[MOCK] Ответ",
            "conversation_status": self.status,
            "routing": {},
            "risk": {"opaque": True},
            "trace": None,
            "state": {"response_language": "kk"},
        }


class Socket:
    def __init__(self):
        self.input = asyncio.Queue()
        self.binary = []
        self.controls = []
        self.closed = None

    async def receive(self):
        packet = await self.input.get()
        if packet is None:
            return {"type": "websocket.disconnect"}
        if isinstance(packet, bytes):
            return {"type": "websocket.receive", "bytes": packet}
        return {
            "type": "websocket.receive",
            "text": packet if isinstance(packet, str) else json.dumps(packet),
        }

    async def send_bytes(self, packet):
        self.binary.append(packet)

    async def send_json(self, control):
        self.controls.append(control)

    async def close(self, code=1000):
        self.closed = code
        self.input.put_nowait(None)


def make_gateway(agent=None, stt=None, tts=None, timeout=1):
    provider = VonageTelephonyProvider(playback_timeout_seconds=timeout)
    runtime = PhoneRuntime(
        agent or Agent(),
        stt or ScriptedPhoneSTT(),
        tts or FakePhoneTTS(),
        provider,
        cleanup_timeout_seconds=0.05,
    )
    return VonageGateway(config(), runtime, provider)


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


async def open_stream(gateway, socket, call=CALL):
    gateway.answer(answer(call))
    socket.input.put_nowait(connected(call))
    task = asyncio.create_task(gateway.serve(socket))
    await until(lambda: gateway.runtime.registry.get(call) is not None)
    return task


def wav(rate=24000, channels=1, samples=2400):
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setframerate(rate)
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.writeframes(struct.pack("<h", 1000) * samples * channels)
    return SpeechResult(audio=output.getvalue(), content_type="audio/wav", language="ru")


@pytest.fixture
def key_path(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "private.key"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path


def test_disabled_settings_key_repr_and_default_from():
    settings = Settings(_env_file=None)
    assert not settings.vonage_enabled and settings.vonage_test_from_number is None
    assert build_vonage_gateway(settings, Agent()) is None
    assert SIGNATURE_SECRET not in repr(config())
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.post(ANSWER_PATH, json={}).status_code == 503
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(MEDIA_PATH):
                pass


@pytest.mark.parametrize(
    "field,value",
    [
        ("vonage_test_to_number", "+447700900001"),
        ("vonage_test_to_number", "bad"),
        ("vonage_test_to_number", ""),
        ("vonage_application_id", None),
        ("vonage_private_key_path", None),
        ("vonage_api_key", None),
        ("vonage_signature_secret", None),
        ("public_base_url", "http://example.test"),
    ],
)
def test_invalid_call_configuration_fails_before_api(key_path, field, value):
    settings = config(vonage_enabled=True, vonage_private_key_path=key_path)
    setattr(settings, field, value)

    settings.openai_api_key = SecretStr("offline-fixture-key")
    settings.openai_router_model = "fixture-model"
    settings.backend_tts_model = "fixture-model"
    settings.backend_tts_voice = "fixture-voice"
    assert build_vonage_gateway(settings, Agent()) is None


def test_bad_private_key_and_unknown_outcome_are_safe(key_path):
    settings = config(vonage_enabled=True, vonage_private_key_path=key_path)
    key_path.write_text("INVALID_PRIVATE_CONTENT")
    with pytest.raises(VonageConfigurationError) as error:
        validate_private_key(settings)
    assert "INVALID_PRIVATE_CONTENT" not in str(error.value)


def test_ncco_secure_correct_format_metadata_auth_no_twilio_fields():
    gateway = make_gateway()
    ncco = gateway.answer(answer())
    endpoint = ncco[0]["endpoint"][0]
    assert ncco[0]["action"] == "connect"
    assert endpoint["uri"] == BASE.replace("https", "wss") + MEDIA_PATH
    assert endpoint["content-type"] == "audio/l16;rate=16000"
    assert endpoint["authorization"] == {"type": "vonage"}
    assert endpoint["headers"] == {"call_uuid": CALL}
    assert "streamSid" not in json.dumps(ncco) and "mulaw" not in json.dumps(ncco)
    assert SIGNATURE_SECRET not in json.dumps(ncco)


@pytest.mark.parametrize(
    "claims",
    [
        {"api_key": "other"},
        {"application_id": OTHER},
        {"iss": "Other"},
        {"iat": int(time.time()) - 1000},
        {"iat": int(time.time()) + 1000},
        {"jti": ""},
    ],
)
def test_auth_claims_rejected(claims):
    assert not make_gateway().authenticate(token(**claims))


def test_auth_valid_missing_bad_token_body_hash_and_unsigned_rejected():
    gateway = make_gateway()
    assert gateway.authenticate(token())
    assert not gateway.authenticate("") and not gateway.authenticate("Bearer invalid")
    assert not gateway.authenticate("Bearer " + jwt.encode({"iss": "Vonage"}, "", algorithm="none"))
    assert gateway.authenticate(token(b"body"), b"body")
    assert not gateway.authenticate(token(b"body"), b"tampered")
    assert not gateway.authenticate(token(), b"unsigned-body")


def test_signed_http_answer_events_ws_and_tampering():
    gateway = make_gateway()
    body = json.dumps({"uuid": CALL, "from": FROM, "to": TO}).encode()
    with TestClient(create_app(config(), vonage_override=gateway)) as client:
        headers = {
            "Content-Type": "application/json",
            "Authorization": token(body),
            "X-Forwarded-Host": "untrusted.example",
        }
        response = client.post(ANSWER_PATH, content=body, headers=headers)
        assert response.status_code == 200
        assert response.json()[0]["endpoint"][0]["uri"].startswith("wss://voice.example.test/")
        assert client.post(ANSWER_PATH, json={}).status_code == 403
        assert client.post(ANSWER_PATH, content=body + b" ", headers=headers).status_code == 403
        assert client.post(ANSWER_PATH, content=b"x" * 16385, headers=headers).status_code == 413
        with client.websocket_connect(MEDIA_PATH, headers={"Authorization": token()}) as ws:
            ws.send_json(connected())
            ws.send_bytes(bytes(640))
        for auth in ("", "Bearer bad"):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(MEDIA_PATH, headers={"Authorization": auth}):
                    pass
        event = json.dumps({"uuid": CALL, "status": "completed"}).encode()
        assert (
            client.post(
                EVENTS_PATH,
                content=event,
                headers={"Content-Type": "application/json", "Authorization": token(event)},
            ).status_code
            == 204
        )
        assert CALL in gateway.closed


def test_signed_fastapi_websocket_text_controls_binary_stt_and_outbound_l16(caplog):
    delivered = threading.Event()

    class ThreeFrameSTT(ScriptedPhoneSTT):
        async def run(self, receive, emit):
            for _ in range(3):
                packet = await receive()
                assert packet.kind == "audio"
                self.frames.append(packet.audio)
                await emit({"type": "activity"})
            await emit({"type": "utterance.final", "text": self.text, "language": "ru"})
            delivered.set()

    stt = ThreeFrameSTT()
    gateway = make_gateway(stt=stt)
    body = json.dumps({"uuid": CALL, "from": FROM, "to": TO}).encode()
    with (
        caplog.at_level(logging.INFO),
        TestClient(create_app(config(), vonage_override=gateway)) as client,
    ):
        response = client.post(
            ANSWER_PATH,
            content=body,
            headers={"Content-Type": "application/json", "Authorization": token(body)},
        )
        assert response.status_code == 200
        assert len(response.json()) == 1 and set(response.json()[0]) == {"action", "endpoint"}
        with client.websocket_connect(MEDIA_PATH, headers={"Authorization": token()}) as ws:
            ws.send_text(json.dumps(connected()))
            ws.send_bytes(bytes(640))
            ws.send_json({"event": "websocket:cleared"})
            ws.send_bytes(bytes(640))
            ws.send_json({"event": "websocket:dtmf", "digit": "5", "duration": 100})
            ws.send_bytes(bytes(640))
            assert delivered.wait(2)
            for _ in range(5):  # Fixture TTS is 100ms = five raw 20ms frames.
                assert len(ws.receive_bytes()) == 640
            notify = ws.receive_json()
            assert notify["action"] == "notify"
            ws.send_json({"event": "websocket:notify", "payload": notify["payload"]})
    assert len(stt.frames) == 3 and all(len(frame) > 640 for frame in stt.frames)
    assert gateway.runtime.registry.get(CALL) is None and not gateway.provider.streams
    assert "vonage websocket_accepted" in caplog.text
    assert "vonage control event=websocket:connected" in caplog.text
    assert "vonage first_binary_audio" in caplog.text
    assert "phone stt_stream_started" in caplog.text
    assert caplog.text.count("phone stt_activity") == 1
    assert "phone stt_final" in caplog.text and "phone agent_response" in caplog.text
    assert "phone tts_ready" in caplog.text
    assert SIGNATURE_SECRET not in caplog.text and stt.text not in caplog.text
    assert "Bearer" not in caplog.text


@pytest.mark.parametrize("failure", ["malformed_control", "receive_exception", "stt_exception"])
def test_websocket_failure_logs_safe_class_phase_reason_and_cleans_up(failure, caplog):
    marker = "DO_NOT_LOG_CREDENTIAL_OR_TRANSCRIPT"

    async def run():
        class RaisingSocket(Socket):
            async def receive(self):
                packet = await super().receive()
                if packet.get("text") == "raise":
                    raise RuntimeError(marker)
                return packet

        class RaisingSTT(ScriptedPhoneSTT):
            async def run(self, receive, emit):
                raise RuntimeError(marker)

        gateway = make_gateway(stt=RaisingSTT() if failure == "stt_exception" else None)
        socket = RaisingSocket()
        task = await open_stream(gateway, socket)
        session = gateway.runtime.registry.get(CALL)
        if failure == "malformed_control":
            socket.input.put_nowait('{"secret":"' + marker + '"')  # Invalid JSON.
        elif failure == "receive_exception":
            socket.input.put_nowait("raise")
        else:
            socket.input.put_nowait(bytes(640))
        await asyncio.wait_for(task, 2)
        assert session.status == "error"
        assert gateway.runtime.registry.get(CALL) is None and not gateway.provider.streams

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    assert marker not in caplog.text
    if failure == "stt_exception":
        assert "phone stt_failed" in caplog.text and "exception_type=RuntimeError" in caplog.text
        assert "message=streaming_stt_failed" in caplog.text
        assert "close_reason=stt_failed" in caplog.text
    else:
        expected = "ValidationError" if failure == "malformed_control" else "RuntimeError"
        phase = "control_validation" if failure == "malformed_control" else "receive"
        assert f"phase={phase} exception_type={expected}" in caplog.text
        assert "message=websocket_receive_processing_failed" in caplog.text
        assert "close_code=1008" in caplog.text


def test_peer_disconnect_code_logged_without_untrusted_reason(caplog):
    async def run():
        class DisconnectSocket(Socket):
            async def receive(self):
                packet = await super().receive()
                if packet["type"] == "websocket.disconnect":
                    packet.update(code=1001, reason="DO_NOT_LOG_PEER_REASON")
                return packet

        gateway, socket = make_gateway(), DisconnectSocket()
        task = await open_stream(gateway, socket)
        socket.input.put_nowait(bytes(640))
        socket.input.put_nowait(None)
        await task
        assert not gateway.provider.streams and gateway.runtime.registry.get(CALL) is None

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    assert "audio_frames=1 close_code=1001 close_reason=peer_disconnect" in caplog.text
    assert "DO_NOT_LOG_PEER_REASON" not in caplog.text


@pytest.mark.parametrize("payload", [b"", b"\0", bytes(3202)])
def test_bad_l16_size(payload):
    with pytest.raises(ValueError):
        L16Input().decode(payload)


def test_known_l16_little_endian_and_real_16_to_24_resampling():
    converter = L16Input()
    result = converter.decode(struct.pack("<h", 1000) * 320)
    result += converter.decode(struct.pack("<h", 1000) * 320)
    pcm = b"".join(result)
    values = struct.unpack("<" + "h" * (len(pcm) // 2), pcm)
    assert 900 <= len(values) <= 960
    assert all(990 <= value <= 1010 for value in values[50:-50])
    assert all(len(chunk) % 2 == 0 and len(chunk) <= 4800 for chunk in result)


@pytest.mark.parametrize(
    "bad",
    [
        b"\0",
        bytes(3202),
        "invalid",
        {"event": "unknown"},
        {"event": "websocket:connected", "call_uuid": CALL, "content-type": "audio/l16;rate=24000"},
    ],
)
def test_bad_stream_isolated_and_cleanup(bad):
    async def run():
        gateway, first, second = make_gateway(), Socket(), Socket()
        first_task = await open_stream(gateway, first)
        second_task = await open_stream(gateway, second, OTHER)
        a, b = gateway.runtime.registry.get(CALL), gateway.runtime.registry.get(OTHER)
        assert a.session_id != b.session_id
        first.input.put_nowait(bad)
        await first_task
        assert a.status == "error" and gateway.runtime.registry.get(CALL) is None
        assert gateway.runtime.registry.get(OTHER) is b
        second.input.put_nowait(None)
        await second_task
        assert not gateway.provider.streams

    asyncio.run(run())


def test_initial_text_and_interleaved_controls_keep_multiple_audio_frames_open():
    async def run():
        stt = ScriptedPhoneSTT()
        gateway, socket = make_gateway(stt=stt), Socket()
        task = await open_stream(gateway, socket)
        session = gateway.runtime.registry.get(CALL)
        try:
            assert not task.done() and socket.closed is None  # TEXT initialization stays open.
            for index, control in enumerate(
                [
                    {"event": "websocket:cleared"},
                    {"event": "websocket:dtmf", "digit": "5", "duration": 100},
                    {"event": "websocket:notify", "payload": {"reply_id": "stale"}},
                ]
            ):
                socket.input.put_nowait(bytes(640))
                socket.input.put_nowait(control)
                await until(lambda: len(stt.frames) == index + 1)
                assert not task.done() and socket.closed is None
            assert session.status == "transcribing"
            assert all(len(frame) > 640 for frame in stt.frames)  # Actual 16k → 24k conversion.
        finally:
            socket.input.put_nowait(None)
            await task
        assert session.status == "cancelled"
        assert not gateway.provider.streams and gateway.runtime.registry.get(CALL) is None

    asyncio.run(run())


def test_delayed_stt_startup_does_not_disconnect_after_sixteen_audio_frames():
    async def run():
        entered, release, seventeenth = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class StartingSTT(ScriptedPhoneSTT):
            async def run(self, receive, emit):
                entered.set()
                await release.wait()  # Deterministic VAD/upstream setup, before queue consumption.
                await super().run(receive, emit)

        class CountingSocket(Socket):
            received_audio = 0

            async def receive(self):
                packet = await super().receive()
                if packet.get("bytes") is not None:
                    self.received_audio += 1
                    if self.received_audio == 17:
                        seventeenth.set()
                return packet

        stt = StartingSTT()
        gateway, socket = make_gateway(stt=stt), CountingSocket()
        task = await open_stream(gateway, socket)
        session = gateway.runtime.registry.get(CALL)
        try:
            socket.input.put_nowait(bytes(640))
            await asyncio.wait_for(entered.wait(), 2)
            for _ in range(20):
                socket.input.put_nowait(bytes(640))
            await asyncio.wait_for(seventeenth.wait(), 2)
            await asyncio.sleep(0)  # Allow an old QueueFull failure/cleanup to run.
            assert gateway.runtime.registry.get(CALL) is session
            assert session.status == "transcribing" and not task.done()
            release.set()
            await until(lambda: len(stt.frames) == 21)
            assert not task.done() and socket.closed is None
        finally:
            release.set()
            socket.input.put_nowait(None)
            await task
        assert not gateway.provider.streams and gateway.runtime.registry.get(CALL) is None

    asyncio.run(run())


@pytest.mark.parametrize("termination", ["deadline", "completed_event"])
def test_backpressure_is_bounded_and_terminal_cleanup_interrupts_wait(
    termination, monkeypatch, caplog
):
    if termination == "deadline":
        monkeypatch.setattr("app.telephony.runtime.AUDIO_QUEUE_WAIT_SECONDS", 0.02)

    async def run():
        class BlockedSTT(ScriptedPhoneSTT):
            async def run(self, receive, emit):
                await asyncio.Event().wait()

        gateway, socket = make_gateway(stt=BlockedSTT()), Socket()
        task = await open_stream(gateway, socket)
        session = gateway.runtime.registry.get(CALL)
        for _ in range(20):
            socket.input.put_nowait(bytes(640))
        await until(lambda: "phone audio_backpressure" in caplog.text)
        if termination == "completed_event":
            await gateway.event(CallEvent(uuid=CALL, status="completed"))
        await asyncio.wait_for(task, 2)
        assert gateway.runtime.registry.get(CALL) is None and not gateway.provider.streams
        if termination == "deadline":
            assert session.status == "error" and session.error_code == "audio_input_failed"
        else:
            assert session.status == "ended" and session.error_code is None

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    if termination == "deadline":
        assert "exception_type=TimeoutError message=audio_admission_failed" in caplog.text
        assert "close_reason=audio_input_failed" in caplog.text


@pytest.mark.parametrize("status", ["awaiting_user", "ended", "handoff"])
def test_full_audio_stt_agent_tts_notify_events_and_terminal(status):
    async def run():
        agent, stt, tts = Agent(status), ScriptedPhoneSTT(), FakePhoneTTS()
        gateway, socket = make_gateway(agent, stt, tts), Socket()
        task = await open_stream(gateway, socket)
        session = gateway.runtime.registry.get(CALL)
        for index in range(2 if status == "awaiting_user" else 1):
            socket.input.put_nowait(bytes(640))
            await until(lambda: len(stt.frames) == index + 1)
            assert len(stt.frames[-1]) > 640
            assert len(agent.requests) == index  # partial does not route
            await gateway.runtime.finish_utterance(CALL)
            await until(lambda: sum(m["action"] == "notify" for m in socket.controls) == index + 1)
            assert session.status == "speaking" and tts.requests[-1].language == "kk"
            await gateway.runtime.handle_transcript(
                CALL, {"type": "utterance.final", "text": "overlap"}
            )
            assert len(agent.requests) == index + 1
            socket.input.put_nowait(bytes(640))  # half-duplex echo ignored
            socket.input.put_nowait({"event": "websocket:notify", "payload": {"reply_id": "wrong"}})
            await asyncio.sleep(0.01)
            assert session.status == "speaking" and len(stt.frames) == index + 1
            notification = [m for m in socket.controls if m["action"] == "notify"][-1]
            socket.input.put_nowait(
                {"event": "websocket:notify", "payload": notification["payload"]}
            )
            if status == "awaiting_user":
                await until(lambda: session.status == "active")
        if status == "awaiting_user":
            assert len({sid for sid, _ in agent.requests}) == 1
            socket.input.put_nowait(None)
        await task
        assert session.status == ("cancelled" if status == "awaiting_user" else status)
        assert not gateway.provider.streams and gateway.runtime.registry.get(CALL) is None
        assert all(len(frame) == 640 and not frame.startswith(b"RIFF") for frame in socket.binary)
        assert session.channel == "voice"
        assert session.provider_metadata["call_uuid"] == CALL
        assert session.conversation_status == status
        assert any(m["action"] == "clear" for m in socket.controls)

    asyncio.run(run())


@pytest.mark.parametrize("action", ["clear", "close", "timeout"])
def test_playback_notification_clear_timeout_safe(action):
    async def run():
        provider, socket = VonageTelephonyProvider(playback_timeout_seconds=0.05), Socket()
        stream = provider.bind(CALL, socket)
        task = asyncio.create_task(provider.send_audio(CALL, wav()))
        await until(lambda: stream.notifications)
        reply_id = next(iter(stream.notifications))
        if action == "clear":
            await provider.clear(stream)
        elif action == "close":
            await provider.close(CALL)
            await provider.close(CALL)
        if action != "timeout":
            provider.acknowledge(stream, reply_id)
        with pytest.raises((PlaybackCancelled, TimeoutError)):
            await task
        assert not stream.notifications
        await provider.close(CALL)

    asyncio.run(run())


def test_answer_destination_and_closed_replay_protection():
    async def run():
        gateway, socket = make_gateway(), Socket()
        wrong = answer().model_copy(update={"to": "447700900002"})
        with pytest.raises(ValueError):
            gateway.answer(wrong)
        task = await open_stream(gateway, socket)
        with pytest.raises(ValueError):
            gateway.answer(answer())
        socket.input.put_nowait(None)
        await task
        with pytest.raises(ValueError):
            gateway.answer(answer())

    asyncio.run(run())


@pytest.mark.parametrize("status", ["completed", "rejected", "failed"])
def test_event_webhook_terminal_cancels_only_bound_call(status):
    async def run():
        gateway, socket, other = make_gateway(), Socket(), Socket()
        task = await open_stream(gateway, socket)
        other_task = await open_stream(gateway, other, OTHER)
        session = gateway.runtime.registry.get(CALL)
        await gateway.event(CallEvent(uuid=CALL, status=status))
        await task
        assert session.status == ("ended" if status == "completed" else "error")
        assert gateway.runtime.registry.get(OTHER) is not None
        other.input.put_nowait(None)
        await other_task

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["agent", "tts"])
def test_late_results_after_disconnect_never_send_audio(stage):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def wait():
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()

        class LateAgent(Agent):
            async def process(self, sid, text, *, channel="voice"):
                await wait()
                return await super().process(sid, text, channel=channel)

        class LateTTS(FakePhoneTTS):
            async def synthesize(self, text, language):
                await wait()
                return await super().synthesize(text, language)

        gateway = make_gateway(
            agent=LateAgent() if stage == "agent" else None,
            tts=LateTTS() if stage == "tts" else None,
        )
        socket = Socket()
        task = await open_stream(gateway, socket)
        await gateway.runtime.handle_transcript(
            CALL, {"type": "utterance.final", "text": "fixture"}, wait_for_completion=False
        )
        await entered.wait()
        socket.input.put_nowait(None)
        await task
        release.set()
        await asyncio.sleep(0.01)
        assert not socket.binary and not gateway.provider.streams

    asyncio.run(run())


def test_logs_and_events_do_not_expose_credentials_or_raw_transcript(caplog):
    async def run():
        caplog.set_level("INFO")
        gateway, socket = make_gateway(), Socket()
        task = await open_stream(gateway, socket)
        await gateway.runtime.handle_transcript(
            CALL, {"type": "utterance.final", "text": "PRIVATE_TEXT"}, wait_for_completion=False
        )
        await until(lambda: socket.controls)
        socket.input.put_nowait(None)
        await task
        assert SIGNATURE_SECRET not in caplog.text and "PRIVATE_TEXT" not in caplog.text
        assert gateway.runtime.agent.messages.requests
        assert not hasattr(gateway.runtime, "event_store")

    asyncio.run(run())


def test_rejection_without_uuid_is_observed_without_creating_session():
    async def run():
        gateway = make_gateway()
        await gateway.event(CallEvent(status="rejected"))
        assert not gateway.runtime._calls and not gateway.runtime.agent.messages.requests

    asyncio.run(run())


def test_native_error_event_closes_known_call():
    async def run():
        gateway, socket = make_gateway(), Socket()
        task = await open_stream(gateway, socket)
        session = gateway.runtime.registry.get(CALL)
        await gateway.event(CallEvent(uuid=CALL, type="error"))
        await task
        assert session.status == "error"

    asyncio.run(run())


def test_late_clear_ack_does_not_complete_or_cancel_new_reply():
    async def run():
        gateway, socket = make_gateway(), Socket()
        task = await open_stream(gateway, socket)
        session = gateway.runtime.registry.get(CALL)
        await gateway.runtime.handle_transcript(
            CALL, {"type": "utterance.final", "text": "fixture"}, wait_for_completion=False
        )
        await until(lambda: bool(socket.controls))
        socket.input.put_nowait({"event": "websocket:cleared"})
        await asyncio.sleep(0.01)
        assert session.status == "speaking"
        assert gateway.provider.streams[CALL].notifications
        notify = next(m for m in socket.controls if m["action"] == "notify")
        socket.input.put_nowait({"event": "websocket:notify", "payload": notify["payload"]})
        await until(lambda: session.status == "active")
        socket.input.put_nowait(None)
        await task

    asyncio.run(run())


def test_application_wiring_reuses_real_speech_and_shared_messages(key_path):
    from app.speech.stt.streaming_provider import OpenAIStreamingSTT
    from app.speech.tts.openai_provider import OpenAITTSProvider

    agent = Agent()
    settings = config(
        vonage_enabled=True,
        vonage_private_key_path=key_path,
        openai_api_key=SecretStr("offline-fixture"),
        openai_router_model="offline-router",
        backend_tts_model="offline-tts",
        backend_tts_voice="offline-voice",
        phone_endpoint_silence_ms=1000,
    )
    gateway = build_vonage_gateway(settings, agent)
    assert gateway.runtime.agent.messages is agent
    assert isinstance(gateway.runtime.stt, OpenAIStreamingSTT)
    assert gateway.runtime.stt._pause_ms == 1000
    assert isinstance(gateway.runtime.tts, OpenAITTSProvider)
    settings.vonage_signature_secret = None
    assert build_vonage_gateway(settings, agent) is None
