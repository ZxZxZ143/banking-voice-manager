"""Offline checks for the optional same-origin local development stand."""

from html.parser import HTMLParser

from fastapi.testclient import TestClient

from app.agent.schemas import RouterDecision, ScenarioSelection
from app.core.config import Settings
from app.main import create_app


def settings(*, enabled: bool) -> Settings:
    return Settings(
        _env_file=None,
        enable_dev_stand=enabled,
        openai_api_key=None,
        openai_router_model=None,
    )


class StandParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.external_resources: list[str] = []
        self.labels: set[str] = set()
        self.fields: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"script", "link", "iframe", "img", "form"}:
            for attribute in ("src", "href", "action"):
                if attributes.get(attribute):
                    self.external_resources.append(attributes[attribute])
        if tag == "label" and attributes.get("for"):
            self.labels.add(attributes["for"])
        if tag in {"input", "textarea"} and attributes.get("id"):
            self.fields.add(attributes["id"])


def test_dev_stand_is_absent_when_disabled():
    assert Settings.model_fields["enable_dev_stand"].default is False
    with TestClient(create_app(settings(enabled=False))) as client:
        assert client.get("/dev").status_code == 404


def test_dev_stand_serves_self_contained_html_without_model_calls():
    with TestClient(create_app(settings(enabled=True))) as client:
        response = client.get("/dev")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "LOCAL DEVELOPMENT" in response.text
        assert "Last successful result" in response.text
        assert "fetch('/api/message'" in response.text
        assert "JSON.stringify({ session_id, text })" in response.text
        assert "/api/v1/turns/text" not in response.text
        assert "innerHTML" not in response.text
        assert "OPENAI_API_KEY" not in response.text
        parser = StandParser()
        parser.feed(response.text)
        assert parser.external_resources == []
        assert parser.fields == {"session-id", "message-text"}
        assert parser.fields <= parser.labels
        assert "/dev" not in client.get("/openapi.json").json()["paths"]


def test_dev_stand_same_origin_api_reuses_session_with_scripted_router():
    class ScriptedRouter:
        def __init__(self) -> None:
            self.previous_turns: list[int] = []

        async def route(self, text, state):
            self.previous_turns.append(state.turn_number)
            return RouterDecision(
                language="ru",
                scenarios=[
                    ScenarioSelection(
                        scenario_id="SC27",
                        confidence=0.95,
                        reason="Offline stand API smoke check",
                    )
                ],
                is_continuation=state.turn_number > 0,
            )

    router = ScriptedRouter()
    with TestClient(create_app(settings(enabled=True), router_override=router)) as client:
        assert client.get("/dev").status_code == 200
        assert router.previous_turns == []
        for turn, text in enumerate(("Продлить полис.", "Какие данные нужны?"), start=1):
            response = client.post(
                "/api/message", json={"session_id": "manual-stand-smoke", "text": text}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["session_id"] == "manual-stand-smoke"
            assert body["state"]["turn_number"] == turn
            assert body["state"]["active_scenario"] == "SC27"
            assert body["response_text"]
            assert body["trace"]["latency_ms"]["total"] >= 0
        assert router.previous_turns == [0, 1]
