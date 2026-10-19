"""Hosted access and protocol boundaries, without any external provider calls."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.deployment import COOKIE_NAME, SESSION_SECONDS
from app.main import create_app

ORIGIN = "https://veyra.test"
PASSWORD = "offline-demo-password-fixture"
SECRET = "offline-cookie-signing-fixture-0123456789"


@pytest.fixture
def client(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html><title>Veyra fixture</title></html>")
    (frontend / "pcm-worklet.js").write_text("// explicit static test fixture")
    settings = Settings(
        _env_file=None,
        openai_api_key=None,
        frontend_origin=ORIGIN,
        static_frontend_dir=frontend,
        demo_access_password=PASSWORD,
        demo_session_secret=SECRET,
    )
    with TestClient(create_app(settings), base_url=ORIGIN) as active:
        yield active


def login(client):
    response = client.post(
        "/login", data={"password": PASSWORD}, headers={"Origin": ORIGIN}, follow_redirects=False
    )
    assert response.status_code == 303
    return response


def test_public_probe_exposes_only_status_and_browser_gets_login(client):
    assert client.get("/health").json() == {"status": "ok"}
    response = client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    html = client.get("/login")
    assert html.status_code == 200
    assert PASSWORD not in html.text
    assert SECRET not in html.text
    assert "no-store" in html.headers["cache-control"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/analytics/overview"),
        ("POST", "/api/message"),
        ("POST", "/api/speech/tts"),
        ("POST", "/api/conversation/start"),
        ("GET", "/openapi.json"),
        ("GET", "/pcm-worklet.js"),
    ],
)
def test_unauthenticated_routes_are_denied_before_business_logic(client, method, path):
    response = client.request(method, path, headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_login_cookie_flags_static_assets_and_full_health_contract(client):
    response = login(client)
    cookie = response.headers["set-cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert flag in cookie
    assert f"Max-Age={SESSION_SECONDS}" in cookie
    assert PASSWORD not in cookie and SECRET not in cookie
    assert "Veyra fixture" in client.get("/").text
    worklet = client.get("/pcm-worklet.js")
    assert worklet.status_code == 200
    assert "javascript" in worklet.headers["content-type"]
    health = client.get("/health").json()
    assert health["service"] == "voice-router"
    assert health["mode"] == "foundation"
    assert health["starter_kit"]["scenarios"] == 40


def test_real_opener_remains_available_without_model_or_mock_after_login(client):
    login(client)
    response = client.post(
        "/api/conversation/start",
        json={"session_id": "deployment-test", "scenario_mode": "insurance_manager"},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == "deployment-test"
    assert response.json()["response_text"].strip()
    assert "[MOCK]" not in response.text


def test_cookie_tampering_and_expiry_are_rejected(client, monkeypatch):
    login(client)
    cookie = client.cookies.get(COOKIE_NAME)
    client.cookies.clear()
    response = client.get(
        "/api/analytics/overview", headers={"Cookie": f"{COOKIE_NAME}={cookie[:-1]}x"}
    )
    assert response.status_code == 401
    expiry = int(cookie.split(".")[0])
    monkeypatch.setattr("app.deployment.time.time", lambda: expiry + 1)
    response = client.get("/api/analytics/overview", headers={"Cookie": f"{COOKIE_NAME}={cookie}"})
    assert response.status_code == 401


def test_malformed_cookie_never_reaches_api_or_raises(client):
    for value in ("1.nonce.é", "not-a-cookie", "1.nonce." + "g" * 64, "x" * 300):
        response = client.get(
            "/api/analytics/overview",
            headers={"Cookie": f"{COOKIE_NAME}={value}".encode("latin-1")},
        )
        assert response.status_code == 401


def test_foreign_origin_cannot_login_or_mutate_and_logout_revokes_browser_cookie(client):
    response = client.post(
        "/login", data={"password": PASSWORD}, headers={"Origin": "https://other.test"}
    )
    assert response.status_code == 403
    login(client)
    response = client.post(
        "/api/conversation/start", json={}, headers={"Origin": "https://other.test"}
    )
    assert response.status_code == 403
    response = client.post("/logout", headers={"Origin": ORIGIN}, follow_redirects=False)
    assert response.status_code == 303
    assert COOKIE_NAME not in client.cookies
    assert client.get("/api/analytics/overview").status_code == 401


def test_websocket_auth_and_origin_then_original_provider_error(client):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("wss://veyra.test/api/v1/voice", headers={"Origin": ORIGIN}):
            pass
    assert closed.value.code == 1008
    login(client)
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(
            "wss://veyra.test/api/v1/voice", headers={"Origin": "https://other.test"}
        ):
            pass
    assert closed.value.code == 1008
    with client.websocket_connect(
        "wss://veyra.test/api/v1/voice", headers={"Origin": ORIGIN}
    ) as socket:
        assert socket.receive_json()["code"] == "missing_api_key"


def test_failed_login_is_bounded_and_never_echoes_password(client):
    for _ in range(10):
        response = client.post(
            "/login", data={"password": "incorrect-fixture"}, headers={"Origin": ORIGIN}
        )
        assert response.status_code == 401
        assert "incorrect-fixture" not in response.text
    response = client.post("/login", data={"password": PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


def test_cloud_port_and_explicit_backend_port_precedence(monkeypatch):
    monkeypatch.delenv("BACKEND_PORT", raising=False)
    monkeypatch.setenv("PORT", "10000")
    assert Settings(_env_file=None).backend_port == 10000
    monkeypatch.setenv("BACKEND_PORT", "8001")
    assert Settings(_env_file=None).backend_port == 8001
    assert Settings(_env_file=None, backend_port=9000).backend_port == 9000


def test_render_origin_and_explicit_frontend_origin_precedence(monkeypatch):
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    assert Settings(_env_file=None).frontend_origin == "http://localhost:5173"
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://veyra-demo.onrender.com")
    assert Settings(_env_file=None).frontend_origin == "https://veyra-demo.onrender.com"
    monkeypatch.setenv("FRONTEND_ORIGIN", ORIGIN)
    assert Settings(_env_file=None).frontend_origin == ORIGIN


def test_incomplete_access_configuration_fails_closed():
    settings = Settings(_env_file=None, demo_access_password=PASSWORD)
    with pytest.raises(RuntimeError, match="Set both"):
        with TestClient(create_app(settings)):
            pass


def test_static_mount_is_explicit_and_requires_build(tmp_path):
    with pytest.raises(RuntimeError, match="index.html"):
        create_app(Settings(_env_file=None, static_frontend_dir=tmp_path))
