import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.config import Settings
from app.main import create_app
from app.speech.errors import SpeechProviderError
from app.speech.tts.base import SpeechResult


@pytest.mark.parametrize("mode", ["disconnect", "timeout"])
def test_request_cancellation_and_timeout_cancel_inflight_synthesis(monkeypatch, mode):
    from fastapi import HTTPException

    from app.api.routes.speech import speech

    async def flow():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def synthesize(*_):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": json.dumps({"text": "Synthetic", "language": "ru"}).encode(),
                    "more_body": False,
                }
            await entered.wait()
            if mode == "disconnect":
                return {"type": "http.disconnect"}
            await asyncio.Future()

        app = SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(_env_file=None),
                tts_provider=SimpleNamespace(synthesize=synthesize),
            )
        )
        request = Request(
            {
                "type": "http",
                "app": app,
                "headers": [
                    (b"origin", b"http://localhost:5173"),
                    (b"content-type", b"application/json"),
                ],
            },
            receive,
        )
        real_timeout = asyncio.timeout
        if mode == "timeout":
            monkeypatch.setattr(asyncio, "timeout", lambda _: real_timeout(0.02))
        with pytest.raises(HTTPException) as error:
            await speech(request)
        assert error.value.status_code == (499 if mode == "disconnect" else 502)
        assert cancelled.is_set()

    asyncio.run(flow())


@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings(_env_file=None, openai_api_key=None, event_db_path=tmp_path / "events.db")
    )
    with TestClient(app) as client:
        app.state.tts_provider = AsyncMock()
        app.state.tts_provider.synthesize.return_value = SpeechResult(
            audio=b"fixture audio", content_type="audio/mpeg", language="ru"
        )
        yield client


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_tts_private_audio_only_no_cache_and_no_analytics(client, language):
    response = client.post(
        "/api/speech/tts",
        headers={"Origin": "http://127.0.0.1:5173"},
        json={"text": "Synthetic sample", "language": language},
    )
    assert response.status_code == 200
    assert response.content == b"fixture audio"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-speech-language"] == language
    client.app.state.tts_provider.synthesize.assert_awaited_once_with("Synthetic sample", language)
    assert client.get("/api/analytics/events").json()["total"] == 0


@pytest.mark.parametrize("origin", [None, "https://evil.invalid", "null"])
def test_tts_rejects_untrusted_or_missing_origin(client, origin):
    response = client.post(
        "/api/speech/tts",
        headers={"Origin": origin} if origin else {},
        json={"text": "private", "language": "ru"},
    )
    assert response.status_code == 403
    client.app.state.tts_provider.synthesize.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "private", "language": "en"},
        {"text": "private", "language": "ru", "voice": "other"},
        {"text": " ", "language": "ru"},
        {"text": "x" * 4001, "language": "ru"},
    ],
)
def test_tts_strict_validation_does_not_echo_speech(client, payload):
    response = client.post(
        "/api/speech/tts", headers={"Origin": "http://localhost:5173"}, json=payload
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_speech_request"}
    client.app.state.tts_provider.synthesize.assert_not_called()


def test_tts_body_limit_before_provider(client):
    response = client.post(
        "/api/speech/tts",
        headers={"Origin": "http://localhost:5173", "Content-Type": "application/json"},
        content="x" * 20001,
    )
    assert response.status_code == 413
    client.app.state.tts_provider.synthesize.assert_not_called()


@pytest.mark.parametrize("failure", [None, SpeechProviderError("secret customer speech")])
def test_tts_unavailable_and_failure_are_honest_and_safe(client, failure):
    if failure:
        client.app.state.tts_provider.synthesize.side_effect = failure
    else:
        client.app.state.tts_provider = None
    response = client.post(
        "/api/speech/tts",
        headers={"Origin": "http://localhost:5173"},
        json={"text": "private", "language": "ru"},
    )
    assert response.status_code == (502 if failure else 503)
    assert "private" not in response.text and "secret" not in response.text
