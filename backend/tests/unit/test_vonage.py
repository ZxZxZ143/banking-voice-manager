"""Offline Vonage SDK/protocol/audio/auth checks. No live phone or OpenAI requests."""

import asyncio
import hashlib
import io
import json
import logging
import struct
import time
import wave
from uuid import uuid4

import jwt
import pytest
import requests
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
from app.telephony.providers.vonage_audio import CONTENT_TYPE, L16Input, speech_to_l16
from app.telephony.providers.vonage_messages import Answer, CallEvent
from app.telephony.runtime import PhoneRuntime
from app.telephony.vonage_calls import (
    ANSWER_PATH,
    EVENTS_PATH,
    MEDIA_PATH,
    VonageConfigurationError,
    create_trial_call,
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

    async def process(self, session_id, text):
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
    assert not settings.vonage_enabled and settings.vonage_test_from_number == FROM
    assert build_vonage_gateway(settings, Agent()) is None
    assert SIGNATURE_SECRET not in repr(config())
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.post(ANSWER_PATH, json={}).status_code == 503
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(MEDIA_PATH):
                pass


def test_outbound_single_configured_trial_request_and_sdk_application_auth(key_path, monkeypatch):
    from vonage_http_client import HttpClient

    captured = []

    def fake_post(client, host, path, params):
        # Exercise actual SDK JWT generation, without making any network request.
        auth_header = client._auth.create_jwt_auth_string()
        private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        claims = jwt.decode(
            auth_header.removeprefix(b"Bearer "), private.public_key(), algorithms=["RS256"]
        )
        assert claims["application_id"] == APP
        assert client._auth.api_secret is None
        assert client._http_client_options.max_retries == 0
        assert client._http_client_options.pool_maxsize == 1
        assert client._timeout == 10
        captured.append((path, params))
        return {
            "uuid": CALL,
            "status": "started",
            "direction": "outbound",
            "conversation_uuid": "CON-test",
        }

    monkeypatch.setattr(HttpClient, "post", fake_post)
    settings = config(vonage_enabled=True, vonage_private_key_path=key_path)
    assert create_trial_call(settings) == CALL
    assert len(captured) == 1
    path, request = captured[0]
    assert path == "/v1/calls"
    assert request["to"] == [{"type": "phone", "number": TO}]
    assert request["from"] == {"type": "phone", "number": FROM}
    assert request["answer_url"] == [BASE + ANSWER_PATH] and request["answer_method"] == "POST"
    assert request["event_url"] == [BASE + EVENTS_PATH] and request["length_timer"] == 600


@pytest.mark.parametrize("from_number", [FROM, "447700900002"])
def test_outbound_final_http_body_preserves_configured_caller_id(
    key_path, monkeypatch, caplog, from_number
):
    captured = []

    def fake_send(session, prepared, **kwargs):
        # Intercept the prepared HTTP body, after all SDK/requests serialization.
        # Never inspect or print Authorization; no actual network request is made.
        assert prepared.method == "POST"
        assert prepared.url == "https://api.nexmo.com/v1/calls"
        assert prepared.headers["Content-Type"] == "application/json"
        captured.append(json.loads(prepared.body))
        response = requests.Response()
        response.status_code = 201
        response.url = prepared.url
        response._content = json.dumps(
            {
                "uuid": CALL,
                "status": "started",
                "direction": "outbound",
                "conversation_uuid": "CON-test",
            }
        ).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", fake_send)
    settings = config(
        vonage_enabled=True,
        vonage_private_key_path=key_path,
        vonage_test_from_number=from_number,
    )
    with caplog.at_level(logging.INFO, logger="app.telephony.vonage_calls"):
        assert create_trial_call(settings) == CALL
    assert len(captured) == 1
    assert captured[0]["from"] == {"type": "phone", "number": from_number}
    assert captured[0]["to"] == [{"type": "phone", "number": TO}]
    assert "from_" not in captured[0]
    diagnostic = caplog.text
    assert "from_configured=True to_configured=True from_type=phone to_type=phone" in diagnostic
    assert f"trial_cli={from_number == FROM}" in diagnostic
    for private_value in [from_number, TO, SIGNATURE_SECRET, "offline-api-key", str(key_path)]:
        assert private_value not in diagnostic
    assert "Bearer" not in diagnostic and "PRIVATE KEY" not in diagnostic


@pytest.mark.parametrize("bad_from", [None, "Unknown", {"type": "phone", "number": "Unknown"}])
def test_bad_sdk_caller_id_serialization_fails_before_submission(key_path, monkeypatch, bad_from):
    from vonage_voice import CreateCallRequest

    original_dump = CreateCallRequest.model_dump

    def broken_dump(request, **kwargs):
        payload = original_dump(request, **kwargs)
        if bad_from is None:
            payload.pop("from", None)
        else:
            payload["from"] = bad_from
        return payload

    class NeverCall:
        def create_call(self, request):
            pytest.fail("Must not submit a malformed caller ID")

    monkeypatch.setattr(CreateCallRequest, "model_dump", broken_dump)
    with pytest.raises(VonageConfigurationError, match="no call submitted"):
        create_trial_call(
            config(vonage_enabled=True, vonage_private_key_path=key_path),
            voice_override=NeverCall(),
        )


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
        ("vonage_enabled", False),
        ("public_base_url", "http://example.test"),
    ],
)
def test_invalid_call_configuration_fails_before_api(key_path, field, value):
    settings = config(vonage_enabled=True, vonage_private_key_path=key_path)
    setattr(settings, field, value)

    class NeverCall:
        def create_call(self, request):
            pytest.fail("Must not invoke provider with invalid config")

    with pytest.raises(VonageConfigurationError):
        create_trial_call(settings, voice_override=NeverCall())


def test_bad_private_key_and_unknown_outcome_are_safe(key_path):
    settings = config(vonage_enabled=True, vonage_private_key_path=key_path)
    key_path.write_text("INVALID_PRIVATE_CONTENT")
    with pytest.raises(VonageConfigurationError) as error:
        create_trial_call(settings)
    assert "INVALID_PRIVATE_CONTENT" not in str(error.value)


def test_sdk_remote_disconnect_does_not_retry_call(key_path, monkeypatch):
    count = 0

    def broken(*args, **kwargs):
        nonlocal count
        count += 1
        raise requests.ConnectionError("RemoteDisconnected")

    monkeypatch.setattr(requests.Session, "request", broken)
    with pytest.raises(RuntimeError, match="outcome is unknown"):
        create_trial_call(config(vonage_enabled=True, vonage_private_key_path=key_path))
    assert count == 1


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


@pytest.mark.parametrize("rate,channels", [(24000, 1), (44100, 2), (16000, 1)])
def test_outbound_raw_pcm_correct_duration_no_container(rate, channels):
    result = speech_to_l16(wav(rate, channels, rate // 10))
    assert len(result) == 3200  # 100ms at 16k mono int16
    assert not result.startswith((b"RIFF", b"ID3"))
    assert all(990 <= value <= 1010 for value in struct.unpack("<1600h", result)[50:-50])


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
        events = gateway.runtime.event_store.get_by_session(session.session_id)
        assert events[0].event_type == "session.started"
        assert events[-1].event_type == "conversation.ended"
        assert all(
            e.channel == "phone"
            and e.metadata["provider"] == "vonage"
            and e.metadata["call_uuid"] == CALL
            for e in events
        )
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
            async def process(self, sid, text):
                await wait()
                return await super().process(sid, text)

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
        for event in gateway.runtime.event_store.list():
            assert SIGNATURE_SECRET not in event.model_dump_json()

    asyncio.run(run())


def test_rejection_without_uuid_is_observed_without_creating_session():
    async def run():
        gateway = make_gateway()
        await gateway.event(CallEvent(status="rejected"))
        assert not gateway.runtime.event_store.list()

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


def test_application_wiring_reuses_real_speech_and_shared_messages():
    from app.speech.stt.streaming_provider import OpenAIStreamingSTT
    from app.speech.tts.openai_provider import OpenAITTSProvider

    agent = Agent()
    settings = config(
        vonage_enabled=True,
        openai_api_key=SecretStr("offline-fixture"),
        openai_router_model="offline-router",
        backend_tts_model="offline-tts",
        backend_tts_voice="offline-voice",
    )
    gateway = build_vonage_gateway(settings, agent)
    assert gateway.runtime.agent.messages is agent
    assert isinstance(gateway.runtime.stt, OpenAIStreamingSTT)
    assert isinstance(gateway.runtime.tts, OpenAITTSProvider)
    settings.vonage_signature_secret = None
    assert build_vonage_gateway(settings, agent) is None
