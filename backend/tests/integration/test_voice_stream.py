"""Offline WebSocket protocol checks; audio, detector and provider are explicit fixtures."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.websocket import voice as voice_module
from app.core.config import Settings
from app.main import create_app


class FixtureDetector:
    def __init__(self, pause_ms):
        self.tracker = SimpleNamespace(has_speech=False, silence_ms=0)

    def feed(self, pcm):
        self.tracker.has_speech = True
        return False, 0.9


class FixtureUpstream:
    def __init__(self, *, complete=True, provider_error=False):
        self.sent = []
        self.events = asyncio.Queue()
        self.complete = complete
        self.provider_error = provider_error
        self.closed = False

    async def send(self, raw):
        event = json.loads(raw)
        self.sent.append(event)
        if event["type"] == "input_audio_buffer.append":
            if self.provider_error:
                self.events.put_nowait({"type": "error", "message": "private-provider-payload"})
            else:
                self.events.put_nowait(
                    {
                        "type": "conversation.item.input_audio_transcription.delta",
                        "delta": "Test ",
                        "item_id": "offline-item",
                    }
                )
        if event["type"] == "input_audio_buffer.commit" and self.complete:
            self.events.put_nowait(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "transcript": "Test transcript fixture",
                    "item_id": "offline-item",
                }
            )

    async def recv(self):
        return json.dumps({"type": "session.updated"})

    def __aiter__(self):
        return self

    async def __anext__(self):
        return json.dumps(await self.events.get())


@pytest.fixture
def client():
    config = Settings(
        _env_file=None,
        openai_api_key="offline-fixture-key",
        openai_router_model=None,
        enable_dev_stand=False,
    )
    with TestClient(create_app(config)) as active:
        yield active


def patch_provider(monkeypatch, upstream=None):
    upstream = upstream or FixtureUpstream()
    connections = []

    @asynccontextmanager
    async def connect(url, **kwargs):
        connections.append((url, kwargs))
        try:
            yield upstream
        finally:
            upstream.closed = True

    monkeypatch.setattr(voice_module, "connect", connect)
    monkeypatch.setattr(voice_module, "SpeechEndDetector", FixtureDetector)
    return upstream, connections


def start(socket, **overrides):
    socket.send_json(
        {
            "type": "start",
            "session_id": str(uuid4()),
            "sample_rate": 24000,
            "channels": 1,
            "pause_ms": 2500,
            **overrides,
        }
    )


def receive_until(socket, kind):
    events = []
    for _ in range(10):
        event = socket.receive_json()
        events.append(event)
        if event["type"] == kind:
            return events
    raise AssertionError(f"Did not receive expected {kind} event")


def test_stream_configuration_partial_commit_and_final_do_not_route(monkeypatch, client):
    upstream, connections = patch_provider(monkeypatch)
    session_id = str(uuid4())
    with client.websocket_connect(
        "/api/v1/voice", headers={"origin": "http://localhost:5173"}
    ) as socket:
        start(socket, session_id=session_id)
        assert socket.receive_json() == {"type": "ready", "pause_ms": 2500}
        socket.send_bytes(bytes(4800))
        partial = receive_until(socket, "transcript.partial")[-1]
        assert partial["delta"] == "Test "
        socket.send_json({"type": "finish"})
        events = receive_until(socket, "utterance.final")
        final = events[-1]
        assert final["text"] == "Test transcript fixture"
        assert final["language"] is None
        assert final["audio_ms"] == 100
        assert final["stt_after_commit_ms"] >= 0
        assert sum(event["type"] == "committed" for event in events) == 1
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert upstream.closed
    assert client.app.state.voice_connections == 0
    assert client.app.state.services.dialogs.get(session_id) is None
    assert client.app.state.services.traces.get(session_id) == []
    assert len(connections) == 1
    assert connections[0][0] == "wss://api.openai.com/v1/realtime?intent=transcription"
    config = upstream.sent[0]["session"]["audio"]["input"]
    assert config["format"] == {"type": "audio/pcm", "rate": 24000}
    assert config["transcription"]["model"] == "gpt-live-transcribe"
    assert config["transcription"]["languages"] == ["kk", "ru"]
    assert config["turn_detection"] is None
    assert sum(event["type"] == "input_audio_buffer.commit" for event in upstream.sent) == 1


def test_manual_finish_without_speech_is_empty_and_never_commits(monkeypatch, client):
    upstream, _ = patch_provider(monkeypatch)
    with client.websocket_connect(
        "/api/v1/voice", headers={"origin": "http://localhost:5173"}
    ) as socket:
        start(socket)
        assert socket.receive_json()["type"] == "ready"
        socket.send_json({"type": "finish"})
        assert socket.receive_json()["type"] == "empty"
    assert not any(event["type"] == "input_audio_buffer.commit" for event in upstream.sent)


def test_cancel_after_commit_stops_waiting_for_provider():
    class FixtureBrowser:
        def __init__(self):
            self.messages = asyncio.Queue()
            for kind in ("finish", "cancel"):
                self.messages.put_nowait(
                    {"type": "websocket.receive", "text": json.dumps({"type": kind})}
                )
            self.sent = []

        async def receive(self):
            return await self.messages.get()

        async def send_json(self, value):
            self.sent.append(value)

    async def run():
        browser = FixtureBrowser()
        upstream = FixtureUpstream(complete=False)
        detector = FixtureDetector(2500)
        detector.tracker.has_speech = True
        await asyncio.wait_for(voice_module.relay(browser, upstream, detector), timeout=0.5)
        assert browser.sent == [{"type": "committed"}]
        assert upstream.sent == [{"type": "input_audio_buffer.commit"}]

    asyncio.run(run())


@pytest.mark.parametrize("pcm", [b"", b"x", bytes(4802)], ids=["empty", "odd", "oversize"])
def test_invalid_pcm_is_rejected_without_forwarding(monkeypatch, client, pcm):
    upstream, _ = patch_provider(monkeypatch)
    with client.websocket_connect(
        "/api/v1/voice", headers={"origin": "http://localhost:5173"}
    ) as socket:
        start(socket)
        assert socket.receive_json()["type"] == "ready"
        socket.send_bytes(pcm)
        error = socket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "voice_failed"
    assert not any(event["type"] == "input_audio_buffer.append" for event in upstream.sent)


@pytest.mark.parametrize("config", [{"pause_ms": 499}, {"sample_rate": 48000}, {"channels": 2}])
def test_invalid_start_never_connects_to_provider(monkeypatch, client, config):
    _, connections = patch_provider(monkeypatch)
    with client.websocket_connect(
        "/api/v1/voice", headers={"origin": "http://localhost:5173"}
    ) as socket:
        start(socket, **config)
        assert socket.receive_json()["code"] == "voice_failed"
    assert connections == []


def test_provider_failure_is_safe_and_frees_connection(monkeypatch, client):
    upstream, _ = patch_provider(monkeypatch, FixtureUpstream(provider_error=True))
    with client.websocket_connect(
        "/api/v1/voice", headers={"origin": "http://localhost:5173"}
    ) as socket:
        start(socket)
        assert socket.receive_json()["type"] == "ready"
        socket.send_bytes(bytes(4800))
        events = receive_until(socket, "error")
        assert events[-1]["code"] == "voice_failed"
        serialized = json.dumps(events)
        assert "private-provider-payload" not in serialized
        assert "offline-fixture-key" not in serialized
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert upstream.closed
    assert client.app.state.voice_connections == 0


def test_connection_cap_rejects_without_opening_provider(monkeypatch, client):
    _, connections = patch_provider(monkeypatch)
    client.app.state.voice_connections = 2
    with client.websocket_connect(
        "/api/v1/voice", headers={"origin": "http://localhost:5173"}
    ) as socket:
        assert socket.receive_json()["code"] == "busy"
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1013
    assert connections == []
    assert client.app.state.voice_connections == 2


def test_missing_local_dependencies_give_actionable_safe_error(monkeypatch, client):
    _, connections = patch_provider(monkeypatch)

    def unavailable(pause_ms):
        raise ImportError("private-environment-path")

    monkeypatch.setattr(voice_module, "SpeechEndDetector", unavailable)
    with client.websocket_connect(
        "/api/v1/voice", headers={"origin": "http://localhost:5173"}
    ) as socket:
        start(socket)
        event = socket.receive_json()
        assert event["code"] == "voice_unavailable"
        assert "backend[voice]" in event["message"]
        assert "private-environment-path" not in json.dumps(event)
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert connections == []
    assert client.app.state.voice_connections == 0
