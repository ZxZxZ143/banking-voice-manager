"""Offline Twilio protocol/audio/security checks; no provider/API network traffic."""

import asyncio
import base64
import io
import json
import struct
import wave
from xml.etree import ElementTree

import av
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from app.core.config import Settings
from app.main import create_app
from app.speech.tts.base import SpeechResult
from app.telephony.bench import FakePhoneTTS, ScriptedPhoneSTT
from app.telephony.providers.twilio import PlaybackCancelled, TwilioTelephonyProvider
from app.telephony.providers.twilio_audio import MulawInput, speech_to_mulaw
from app.telephony.providers.twilio_messages import message_adapter
from app.telephony.runtime import PhoneRuntime
from app.telephony.twilio_gateway import MEDIA_PATH, VOICE_PATH, TwilioGateway, build_twilio_gateway

ACCOUNT = "AC" + "1" * 32
CALL = "CA" + "2" * 32
STREAM = "MZ" + "3" * 32
OTHER = "CA" + "4" * 32
OTHER_STREAM = "MZ" + "5" * 32
TOKEN = "offline-test-token"
BASE = "https://phone.example.test"


class Agent:
    def __init__(self, status="awaiting_user", language="ru"):
        self.requests = []
        self.status = status
        self.language = language

    async def process(self, session_id, text, *, channel="voice"):
        assert channel == "voice"
        self.requests.append((session_id, text))
        return {
            "session_id": session_id,
            "response_text": "[MOCK] Ответ",
            "conversation_status": self.status,
            "state": {"response_language": self.language},
            "risk": {"preserved": True},
            "trace": {"scenarios": []},
        }


class Socket:
    def __init__(self):
        self.input = asyncio.Queue()
        self.output = []
        self.closed = None

    async def receive_text(self):
        item = await self.input.get()
        if item is None:
            raise WebSocketDisconnect()
        return item if isinstance(item, str) else json.dumps(item)

    async def send_json(self, item):
        self.output.append(item)

    async def close(self, code=1000):
        self.closed = code
        self.input.put_nowait(None)


def config(**overrides):
    return Settings(
        _env_file=None,
        twilio_account_sid=ACCOUNT,
        twilio_auth_token=SecretStr(TOKEN),
        public_base_url=BASE,
        **overrides,
    )


def make_gateway(agent=None, stt=None, tts=None, timeout=1):
    provider = TwilioTelephonyProvider(playback_timeout_seconds=timeout)
    runtime = PhoneRuntime(
        agent or Agent(),
        stt or ScriptedPhoneSTT(),
        tts or FakePhoneTTS(),
        provider,
        cleanup_timeout_seconds=0.1,
    )
    return TwilioGateway(config(), runtime, provider)


def connected():
    return {"event": "connected", "protocol": "Call", "version": "1.0.0"}


def start(call=CALL, stream=STREAM):
    return {
        "event": "start",
        "sequenceNumber": "1",
        "streamSid": stream,
        "start": {
            "callSid": call,
            "streamSid": stream,
            "accountSid": ACCOUNT,
            "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
        },
    }


def media(seq=2, payload=None, stream=STREAM):
    return {
        "event": "media",
        "sequenceNumber": str(seq),
        "streamSid": stream,
        "media": {
            "track": "inbound",
            "chunk": str(seq - 1),
            "timestamp": str(seq * 20),
            "payload": payload or base64.b64encode(bytes([255]) * 160).decode(),
        },
    }


def mark(name, seq=3, stream=STREAM):
    return {
        "event": "mark",
        "sequenceNumber": str(seq),
        "streamSid": stream,
        "mark": {"name": name},
    }


def stop(seq=2, call=CALL, stream=STREAM):
    return {
        "event": "stop",
        "sequenceNumber": str(seq),
        "streamSid": stream,
        "stop": {"accountSid": ACCOUNT, "callSid": call},
    }


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


async def open_stream(gateway, socket, call=CALL, stream=STREAM):
    gateway.admit(call)
    task = asyncio.create_task(gateway.serve(socket))
    socket.input.put_nowait(connected())
    socket.input.put_nowait(start(call, stream))
    await until(lambda: gateway.runtime.registry.get(call) is not None)
    return task


def wav(rate=24000, channels=1, samples=2400):
    result = io.BytesIO()
    with wave.open(result, "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(struct.pack("<h", 1000) * samples * channels)
    return SpeechResult(audio=result.getvalue(), content_type="audio/wav", language="ru")


def test_known_g711_samples_and_input_rate():
    decoder = av.CodecContext.create("pcm_mulaw", "r")
    decoder.sample_rate = 8000
    decoder.layout = "mono"
    frame = decoder.decode(av.Packet(bytes([255, 127, 0, 128])))[0]
    assert struct.unpack("<4h", bytes(frame.planes[0])[:8]) == (0, 0, -32124, 32124)
    phone = MulawInput()
    chunks = phone.decode(bytes([255]) * 160)
    chunks += phone.decode(bytes([255]) * 160)
    # Stateful filter retains a small tail, rather than stretching each packet separately.
    assert 1800 <= sum(map(len, chunks)) <= 1920
    assert all(len(chunk) % 2 == 0 and len(chunk) <= 4800 for chunk in chunks)
    assert all(not any(chunk) for chunk in chunks)


@pytest.mark.parametrize("payload", [b"", bytes(801)])
def test_bad_input_audio_size(payload):
    with pytest.raises(ValueError):
        MulawInput().decode(payload)


@pytest.mark.parametrize("rate,channels", [(24000, 1), (44100, 2), (48000, 1), (8000, 1)])
def test_real_wav_conversion_rate_channels_and_no_container(rate, channels):
    audio = speech_to_mulaw(wav(rate, channels, rate // 10))
    assert len(audio) == 800
    assert not audio.startswith((b"RIFF", b"ID3"))
    assert len(set(audio)) < 10  # steady tone level, not WAV bytes renamed as mu-law


def test_real_mp3_decoding():
    source = io.BytesIO()
    with av.open(source, "w", format="mp3") as container:
        stream = container.add_stream("libmp3lame", rate=24000)
        frame = av.AudioFrame(format="s16p", layout="mono", samples=2400)
        frame.sample_rate = 24000
        frame.planes[0].update(bytes(4800))
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    result = speech_to_mulaw(
        SpeechResult(audio=source.getvalue(), content_type="audio/mpeg", language="kk")
    )
    assert len(result) == 800
    assert set(result) <= {127, 255}


@pytest.mark.parametrize(
    "speech",
    [
        SpeechResult(audio=b"not mp3", content_type="audio/mpeg", language="ru"),
        SpeechResult(audio=b"bytes", content_type="audio/ogg", language="ru"),
        SpeechResult(audio=b"x" * 25_000_001, content_type="audio/wav", language="ru"),
    ],
)
def test_invalid_tts_audio_fails(speech):
    with pytest.raises(Exception):
        speech_to_mulaw(speech)


@pytest.mark.parametrize(
    "base",
    [
        "http://phone.test",
        "https://phone.test/a",
        "https://user:password@phone.test",
        "https://phone.test?x=1",
        "https://phone.test/#fragment",
        "",
    ],
)
def test_canonical_origin_validation(base):
    settings = config()
    settings.public_base_url = base
    gateway = make_gateway()
    with pytest.raises(ValueError):
        TwilioGateway(settings, gateway.runtime, gateway.provider)


def test_not_configured_web_still_works_and_no_automatic_mock():
    assert build_twilio_gateway(Settings(_env_file=None), Agent()) is None
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/health").status_code == 200
        assert client.post(VOICE_PATH).status_code == 503
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(MEDIA_PATH):
                pass


def test_sdk_signed_webhook_twiml_and_request_tampering():
    gateway = make_gateway()
    params = {"AccountSid": ACCOUNT, "CallSid": CALL, "ExtraTwilioField": "preserve signature"}
    signature = RequestValidator(TOKEN).compute_signature(BASE + VOICE_PATH, params)
    with TestClient(create_app(config(), twilio_override=gateway)) as client:
        response = client.post(
            VOICE_PATH,
            data=params,
            headers={
                "X-Twilio-Signature": signature,
                "Host": "untrusted.test",
                "X-Forwarded-Host": "attacker.test",
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/xml")
        root = ElementTree.fromstring(response.text)
        assert (
            root.find("Connect/Stream").attrib["url"] == BASE.replace("https", "wss") + MEDIA_PATH
        )
        assert root.find("Hangup") is not None
        assert (
            client.post(
                VOICE_PATH,
                data={**params, "CallSid": OTHER},
                headers={"X-Twilio-Signature": signature},
            ).status_code
            == 403
        )
        assert client.post(VOICE_PATH, data=params).status_code == 403
        assert client.post(VOICE_PATH + "?x=1", data=params).status_code == 400
        assert (
            client.post(
                VOICE_PATH,
                content="x" * 16385,
                headers={"content-type": "application/x-www-form-urlencoded"},
            ).status_code
            == 413
        )


@pytest.mark.parametrize(
    "url", [BASE + MEDIA_PATH, BASE + MEDIA_PATH + "/", BASE.replace("https", "wss") + MEDIA_PATH]
)
def test_signed_websocket_handshake(url):
    gateway = make_gateway()
    signature = RequestValidator(TOKEN).compute_signature(url, {})
    with TestClient(create_app(config(), twilio_override=gateway)) as client:
        with client.websocket_connect(MEDIA_PATH, headers={"X-Twilio-Signature": signature}) as ws:
            ws.send_json(connected())
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(MEDIA_PATH, headers={"X-Twilio-Signature": "invalid"}):
                pass


def test_admission_capacity_expiry_and_replay():
    gateway = make_gateway()
    gateway.pending[CALL] = 0
    gateway.admit(OTHER)
    assert CALL not in gateway.pending
    for number in range(100):
        gateway.pending["CA" + format(number, "032x")] = float("inf")
    with pytest.raises(ValueError):
        gateway.admit(CALL)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(event="unknown"),
        lambda m: m.update(sequenceNumber="0"),
        lambda m: m.update(streamSid="bad"),
        lambda m: m["start"]["mediaFormat"].update(sampleRate=24000),
        lambda m: m["start"]["mediaFormat"].update(channels=2),
        lambda m: m["start"]["mediaFormat"].update(encoding="pcm_s16le"),
        lambda m: m["start"].update(tracks=["outbound"]),
    ],
)
def test_protocol_schema_rejects_invalid(mutation):
    message = start()
    mutation(message)
    with pytest.raises(ValueError):
        message_adapter.validate_python(message)


@pytest.mark.parametrize(
    "bad",
    [
        start(),  # start before connected
        {"event": "connected", "protocol": "Unknown", "version": "1.0.0"},
        "not-json",
        " " * 8193,
    ],
)
def test_invalid_prestart_closes_without_session(bad):
    async def run():
        gateway, socket = make_gateway(), Socket()
        socket.input.put_nowait(bad)
        await gateway.serve(socket)
        assert socket.closed == 1008
        assert not gateway.provider.streams
        assert not gateway.runtime._calls and not gateway.runtime.agent.messages.requests

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad",
    [
        connected(),
        start(),
        media(seq=5),
        media(stream=OTHER_STREAM),
        media(payload="!!!!"),
        media(payload=base64.b64encode(bytes(801)).decode()),
        stop(call=OTHER),
        {
            "event": "dtmf",
            "sequenceNumber": "2",
            "streamSid": STREAM,
            "dtmf": {"track": "outbound_track", "digit": "1"},
        },
    ],
)
def test_bad_bound_stream_isolated_and_cleanup(bad):
    async def run():
        gateway, socket = make_gateway(), Socket()
        task = await open_stream(gateway, socket)
        failed_session = gateway.runtime.registry.get(CALL)
        other_socket = Socket()
        other_task = await open_stream(gateway, other_socket, OTHER, OTHER_STREAM)
        socket.input.put_nowait(bad)
        await task
        assert gateway.runtime.registry.get(CALL) is None
        assert gateway.runtime.registry.get(OTHER) is not None
        assert OTHER in gateway.provider.streams
        assert failed_session.status == "error"
        assert failed_session.error_code == "provider_error"
        other_socket.input.put_nowait(stop(call=OTHER, stream=OTHER_STREAM))
        await other_task
        assert not gateway.provider.streams

    asyncio.run(run())


def test_missing_admission_and_closed_call_replay():
    async def run():
        gateway, socket = make_gateway(), Socket()
        socket.input.put_nowait(connected())
        socket.input.put_nowait(start())
        await gateway.serve(socket)
        assert not gateway.runtime._calls and not gateway.runtime.agent.messages.requests
        socket = Socket()
        task = await open_stream(gateway, socket)
        session = gateway.runtime.registry.get(CALL)
        socket.input.put_nowait(stop())
        await task
        assert session.status == "ended"
        replay = Socket()
        gateway.admit(CALL)
        replay.input.put_nowait(connected())
        replay.input.put_nowait(start())
        await gateway.serve(replay)
        assert gateway.runtime.registry.get(CALL) is None
        assert len(gateway.runtime.registry._seen) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,language", [("awaiting_user", "ru"), ("ended", "kk"), ("handoff", "ru")]
)
def test_full_twilio_turn_mark_gating_half_duplex_and_terminal_cleanup(status, language):
    async def run():
        agent, stt, tts = Agent(status, language), ScriptedPhoneSTT(), FakePhoneTTS()
        gateway, socket = make_gateway(agent, stt, tts), Socket()
        task = await open_stream(gateway, socket)
        session = gateway.runtime.registry.get(CALL)
        assert session.channel == "voice" and session.session_id != CALL
        socket.input.put_nowait(media())
        await until(lambda: stt.frames)
        assert len(stt.frames[0]) > 800 and len(stt.frames[0]) % 2 == 0
        await gateway.runtime.finish_utterance(CALL)
        await until(lambda: any(m["event"] == "mark" for m in socket.output))
        playback = next(m for m in socket.output if m["event"] == "mark")
        assert session.status == "speaking"
        assert len(agent.requests) == 1 and agent.requests[0][0] == session.session_id
        assert tts.requests[0].language == language
        outgoing = [
            base64.b64decode(m["media"]["payload"]) for m in socket.output if m["event"] == "media"
        ]
        assert sum(map(len, outgoing)) == 800
        socket.input.put_nowait(media(3))  # echo/caller audio while speaking gets dropped
        socket.input.put_nowait(mark("wrong-mark", 4))
        await asyncio.sleep(0.01)
        assert session.status == "speaking" and len(stt.frames) == 1
        socket.input.put_nowait(mark(playback["mark"]["name"], 5))
        if status == "awaiting_user":
            await until(lambda: session.status == "active")
            socket.input.put_nowait(
                {
                    "event": "dtmf",
                    "sequenceNumber": "6",
                    "streamSid": STREAM,
                    "dtmf": {"track": "inbound_track", "digit": "1"},
                }
            )
            socket.input.put_nowait(stop(7))
        await task
        assert not gateway.provider.streams and gateway.runtime.registry.get(CALL) is None
        assert len(agent.requests) == 1
        assert session.channel == "voice"
        assert session.provider_metadata["stream_sid"] == STREAM
        assert any(m["event"] == "clear" for m in socket.output)
        assert session.status == ("ended" if status == "awaiting_user" else status)

    asyncio.run(run())


@pytest.mark.parametrize("action", ["clear", "close", "timeout"])
def test_playback_clear_timeout_cannot_be_acknowledged_as_success(action):
    async def run():
        provider, socket = TwilioTelephonyProvider(playback_timeout_seconds=0.05), Socket()
        stream = provider.bind(CALL, STREAM, socket)
        task = asyncio.create_task(provider.send_audio(CALL, wav()))
        await until(lambda: stream.marks)
        name = next(iter(stream.marks))
        if action == "clear":
            await provider.clear(stream)
        elif action == "close":
            await provider.close(CALL)
            await provider.close(CALL)
        provider.acknowledge(stream, "stale")
        if action != "timeout":
            provider.acknowledge(stream, name)
        with pytest.raises((PlaybackCancelled, TimeoutError)):
            await task
        assert not stream.marks
        await provider.close(CALL)

    asyncio.run(run())


def test_disconnect_during_agent_blocks_late_audio_and_partial_never_calls_agent():
    async def run():
        gate = asyncio.Event()

        class SlowAgent(Agent):
            async def process(self, session_id, text, *, channel="voice"):
                await gate.wait()
                return await super().process(session_id, text, channel=channel)

        agent = SlowAgent()
        gateway, socket = make_gateway(agent), Socket()
        task = await open_stream(gateway, socket)
        await gateway.runtime.handle_transcript(
            CALL, {"type": "transcript.partial", "text": "partial"}
        )
        assert not agent.requests
        await gateway.runtime.handle_transcript(
            CALL, {"type": "utterance.final", "text": "final"}, wait_for_completion=False
        )
        socket.input.put_nowait(None)
        await task
        gate.set()
        await asyncio.sleep(0)
        assert not any(m["event"] == "media" for m in socket.output)
        assert not gateway.provider.streams

    asyncio.run(run())


def test_secrets_and_raw_audio_not_in_logs(caplog):
    async def run():
        caplog.set_level("INFO")
        gateway, socket = make_gateway(), Socket()
        task = await open_stream(gateway, socket)
        await gateway.runtime.handle_transcript(
            CALL, {"type": "utterance.final", "text": "PRIVATE_TEXT"}, wait_for_completion=False
        )
        await until(lambda: any(m["event"] == "mark" for m in socket.output))
        socket.input.put_nowait(None)
        await task
        assert TOKEN not in caplog.text and "PRIVATE_TEXT" not in caplog.text
        assert "call_sid=" in caplog.text and "session_id=" in caplog.text

    asyncio.run(run())


def test_two_utterances_same_session_and_no_overlapping_agent_turn():
    async def run():
        agent = Agent()
        gateway, socket = make_gateway(agent), Socket()
        task = await open_stream(gateway, socket)
        session = gateway.runtime.registry.get(CALL)
        for index in range(2):
            await gateway.runtime.handle_transcript(
                CALL,
                {"type": "utterance.final", "text": f"[MOCK] turn {index}"},
                wait_for_completion=False,
            )
            await until(lambda: sum(m["event"] == "mark" for m in socket.output) == index + 1)
            await gateway.runtime.handle_transcript(
                CALL, {"type": "utterance.final", "text": "overlap"}
            )
            assert len(agent.requests) == index + 1
            name = [m["mark"]["name"] for m in socket.output if m["event"] == "mark"][-1]
            socket.input.put_nowait(mark(name, seq=index + 2))
            await until(lambda: session.status == "active")
        assert len({session_id for session_id, _ in agent.requests}) == 1
        socket.input.put_nowait(stop(seq=4))
        await task

    asyncio.run(run())


def test_stale_tts_after_disconnect_cannot_send_audio():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class LateTTS(FakePhoneTTS):
            async def synthesize(self, text, language):
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()  # intentionally broken dependency
                return await super().synthesize(text, language)

        gateway, socket = make_gateway(tts=LateTTS()), Socket()
        task = await open_stream(gateway, socket)
        await gateway.runtime.handle_transcript(
            CALL, {"type": "utterance.final", "text": "fixture"}, wait_for_completion=False
        )
        await entered.wait()
        socket.input.put_nowait(None)
        await task
        release.set()
        await asyncio.sleep(0.01)
        assert not any(m["event"] == "media" for m in socket.output)
        assert gateway.runtime.registry.get(CALL) is None

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["stt", "tts", "conversion"])
def test_provider_path_dependency_errors_terminate_call(failure):
    async def run():
        class FailedSTT:
            async def run(self, receive, emit):
                await receive()
                raise RuntimeError("offline error")

        class FailedTTS:
            async def synthesize(self, text, language):
                raise RuntimeError("offline error")

        class BadAudioTTS:
            async def synthesize(self, text, language):
                return SpeechResult(
                    audio=b"invalid mp3", content_type="audio/mpeg", language=language
                )

        gateway = make_gateway(
            stt=FailedSTT() if failure == "stt" else None,
            tts=FailedTTS()
            if failure == "tts"
            else BadAudioTTS()
            if failure == "conversion"
            else None,
        )
        socket = Socket()
        task = await open_stream(gateway, socket)
        session = gateway.runtime.registry.get(CALL)
        if failure == "stt":
            socket.input.put_nowait(media())
        else:
            await gateway.runtime.handle_transcript(
                CALL, {"type": "utterance.final", "text": "fixture"}, wait_for_completion=False
            )
        await task
        assert session.status == "error" and not gateway.provider.streams
        assert gateway.runtime.registry.get(CALL) is None

    asyncio.run(run())


def test_configured_ws_missing_signature_and_query_rejected():
    gateway = make_gateway()
    with TestClient(create_app(config(), twilio_override=gateway)) as client:
        for path in (MEDIA_PATH, MEDIA_PATH + "?x=1"):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(path):
                    pass


def test_webhook_signed_wrong_account_and_invalid_form():
    gateway = make_gateway()
    with TestClient(create_app(config(), twilio_override=gateway)) as client:
        params = {"AccountSid": "AC" + "f" * 32, "CallSid": CALL}
        signature = RequestValidator(TOKEN).compute_signature(BASE + VOICE_PATH, params)
        assert (
            client.post(
                VOICE_PATH, data=params, headers={"X-Twilio-Signature": signature}
            ).status_code
            == 400
        )
        assert (
            client.post(
                VOICE_PATH,
                content="invalid",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ).status_code
            == 400
        )
        assert client.post(VOICE_PATH, json=params).status_code == 415


def test_duplicate_bind_and_cross_call_mark_isolation():
    async def run():
        provider, one, two = TwilioTelephonyProvider(), Socket(), Socket()
        first = provider.bind(CALL, STREAM, one)
        second = provider.bind(OTHER, OTHER_STREAM, two)
        with pytest.raises(ValueError):
            provider.bind(CALL, OTHER_STREAM, Socket())
        with pytest.raises(ValueError):
            provider.bind("third", STREAM, Socket())
        first_task = asyncio.create_task(provider.send_audio(CALL, wav()))
        second_task = asyncio.create_task(provider.send_audio(OTHER, wav()))
        await until(lambda: first.marks and second.marks)
        first_mark, second_mark = next(iter(first.marks)), next(iter(second.marks))
        assert first_mark != second_mark
        provider.acknowledge(second, first_mark)
        assert not first_task.done() and not second_task.done()
        provider.acknowledge(first, first_mark)
        provider.acknowledge(second, second_mark)
        await asyncio.gather(first_task, second_task)
        await provider.close(CALL)
        await provider.close(OTHER)

    asyncio.run(run())


def test_live_factory_reuses_existing_speech_and_message_boundaries():
    from app.speech.stt.streaming_provider import OpenAIStreamingSTT
    from app.speech.tts.openai_provider import OpenAITTSProvider

    agent = Agent()
    settings = config(
        twilio_enabled=True,
        openai_api_key=SecretStr("offline-key"),
        openai_router_model="offline-router",
        backend_tts_model="offline-tts",
        backend_tts_voice="offline-voice",
        phone_endpoint_silence_ms=1100,
    )
    gateway = build_twilio_gateway(settings, agent)
    assert gateway.runtime.agent.messages is agent
    assert isinstance(gateway.runtime.stt, OpenAIStreamingSTT)
    assert gateway.runtime.stt._pause_ms == 1100
    assert isinstance(gateway.runtime.tts, OpenAITTSProvider)
    settings.backend_tts_model = " "
    assert build_twilio_gateway(settings, agent) is None
    settings.backend_tts_model = "offline-tts"
    settings.twilio_auth_token = None
    assert build_twilio_gateway(settings, agent) is None
