from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.data.loaders import DataLoadError
from app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app(Settings(_env_file=None))) as active:
        yield active


def test_health_loaded_actual_data(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "voice-router",
        "mode": "foundation",
        "starter_kit": {"scenarios": 40, "system_intents": 3, "actions": 31, "dev_utterances": 104},
    }


def test_text_endpoint_honest_501_without_dialog_mutation(client):
    session_id = str(uuid4())
    response = client.post("/api/v1/turns/text", json={"session_id": session_id, "text": "Привет"})
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_implemented"
    assert client.app.state.services.dialogs.get(session_id) is None
    assert client.app.state.services.traces.get(session_id) == []


@pytest.mark.parametrize("text", ["", "  ", "x" * 10001])
def test_invalid_turn_input_rejected(client, text):
    response = client.post("/api/v1/turns/text", json={"session_id": str(uuid4()), "text": text})
    assert response.status_code == 422


def test_voice_reports_error_and_closes(client):
    with client.websocket_connect(
        "/api/v1/voice", headers={"origin": "http://localhost:5173"}
    ) as socket:
        assert socket.receive_json()["code"] == "missing_api_key"
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1013


def test_voice_rejects_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/api/v1/voice", headers={"origin": "https://other.test"}):
            pass
    assert closed.value.code == 1008


def test_missing_starter_kit_fails_startup(tmp_path):
    with pytest.raises(DataLoadError, match="scenarios.json"):
        with TestClient(create_app(Settings(_env_file=None, starter_kit_path=tmp_path))):
            pass


def test_openapi_and_cors(client):
    spec = client.get("/openapi.json").json()
    assert "501" in spec["paths"]["/api/v1/turns/text"]["post"]["responses"]
    response = client.options(
        "/api/v1/turns/text",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
