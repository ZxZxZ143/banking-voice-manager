from collections import deque
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.agent.errors import RouterProviderError
from app.agent.schemas import RouterDecision
from app.core.config import Settings
from app.main import create_app
from app.packs.product_promoter.models import ProductDecision
from app.risk.models import RiskSignal, SecurityDecision


class RouterFixture:
    def __init__(self, *outputs):
        self.outputs = deque(outputs)

    async def route(self, text, state):
        output = self.outputs.popleft()
        if isinstance(output, Exception):
            raise output
        return output


def decision(scenario="SC33", slots=None):
    return RouterDecision(
        language="ru",
        response_language="ru",
        slots=slots or {},
        scenarios=[dict(scenario_id=scenario, confidence=0.99, reason="fixture")],
    )


@pytest.fixture
def client():
    with TestClient(
        create_app(
            Settings(_env_file=None),
            router_override=RouterFixture(
                decision(),
                decision("SC37"),
                decision("SYS_GOODBYE"),
            ),
        )
    ) as active:
        yield active


def test_empty_contract_and_openapi(client):
    assert client.get("/api/analytics/events").json() == {
        "events": [],
        "total": 0,
        "limit": 100,
        "offset": 0,
        "next_offset": None,
    }
    summary = client.get("/api/analytics/summary").json()
    assert summary["period"] == {"from": None, "to": None}
    assert summary["conversations"] == summary["sales"]["leads"] == 0
    assert client.get("/api/analytics/sessions/absent").json()["channel"] is None
    spec = client.get("/openapi.json").json()
    for path in (
        "/api/analytics/events",
        "/api/analytics/summary",
        "/api/analytics/sessions/{session_id}",
    ):
        assert set(spec["paths"][path]) == {"get"}
        assert (
            "$ref"
            in spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
                "schema"
            ]
        )
    assert "ConversationEvent" in spec["components"]["schemas"]


def test_committed_turns_handoff_end_and_session_order(client):
    for session in ("insurance", "handoff", "ended"):
        response = client.post(
            "/api/message", json={"session_id": session, "text": "fixture input"}
        )
        assert response.status_code == 200
    session = client.get("/api/analytics/sessions/insurance", params={"limit": 2}).json()
    assert session["total"] == 4 and session["next_offset"] == 2
    assert [e["event_type"] for e in session["events"]] == [
        "conversation_started",
        "assistant_selected",
    ]
    summary = client.get("/api/analytics/summary").json()
    assert summary["conversations"] == 3 and summary["handoffs"] == 1
    before = client.get("/api/analytics/events").json()["total"]
    assert (
        client.post("/api/message", json={"session_id": "handoff", "text": "again"}).status_code
        == 409
    )
    assert client.get("/api/analytics/events").json()["total"] == before
    ended = client.get("/api/analytics/events", params={"event_type": "conversation_ended"}).json()
    assert ended["total"] == 1


@pytest.mark.parametrize(
    "query",
    [
        {"limit": 501},
        {"limit": 0},
        {"offset": -1},
        {"offset": 1000001},
        {"assistant_id": "unknown"},
        {"assistant_id": "' OR 1=1 --"},
        {"event_type": "all"},
        {"risk_level": "attack"},
        {"channel": "web"},
        {"source": "unknown"},
        {"from": "2026-10-03T10:00:00"},
        {"to": "invalid"},
        {"from": "2026-10-04T00:00:00Z", "to": "2026-10-03T00:00:00Z"},
    ],
)
def test_filters_reject_invalid_values(client, query):
    assert client.get("/api/analytics/events", params=query).status_code == 422
    assert client.get("/api/analytics/summary", params=query).status_code == 422


def test_rollback_emits_no_events(client):
    built = client.app.state.services
    built.insurance.processor.router = RouterFixture(RouterProviderError())
    response = client.post("/api/message", json={"session_id": "rollback", "text": "fixture"})
    assert response.status_code == 502
    assert client.get("/api/analytics/sessions/rollback").json()["total"] == 0
    assert built.dialogs.get_conversation("rollback") is None


def test_storage_failure_preserves_customer_and_is_observable(client, monkeypatch, caplog):
    def fail(*args):
        raise OSError("private host path /secret phone +77018887766")

    built = client.app.state.services
    monkeypatch.setattr(built.events.store, "append_many", fail)
    response = client.post("/api/message", json={"session_id": "write-fails", "text": "fixture"})
    assert response.status_code == 200
    assert built.dialogs.get_conversation("write-fails") is not None
    assert client.get("/api/analytics/events").json()["total"] == 0
    health = client.get("/health").json()["analytics"]
    assert health["status"] == "degraded" and health["failure_count"] == 1
    assert "analytics_storage_failure" in caplog.text
    assert "private host" not in caplog.text and "+77018887766" not in caplog.text
    monkeypatch.setattr(built.events.store, "query_events", fail)
    error = client.get("/api/analytics/events")
    assert error.status_code == 503
    assert error.json() == {
        "detail": {
            "code": "analytics_storage_unavailable",
            "message": "Analytics storage unavailable",
        }
    }


def test_unwritable_storage_does_not_block_startup_or_customer(tmp_path):
    blocked = tmp_path / "file-not-directory"
    blocked.write_text("fixture")
    with TestClient(
        create_app(
            Settings(_env_file=None, event_db_path=blocked / "events.db"),
            router_override=RouterFixture(decision()),
        )
    ) as active:
        assert active.get("/health").json()["analytics"]["status"] == "degraded"
        assert active.get("/api/analytics/summary").status_code == 503
        assert (
            active.post(
                "/api/message", json={"session_id": "degraded", "text": "fixture"}
            ).status_code
            == 200
        )


def test_real_core_sales_risk_and_fraud_mapping_preserves_business_state(client):
    built = client.app.state.services
    card = built.registry.get("card_promoter")
    card.agent.decide = AsyncMock(
        return_value=ProductDecision(intent="card_interest", language="ru", response_language="ru")
    )
    response = client.post(
        "/api/conversation/start", json={"session_id": "sales", "scenario_mode": "card_promoter"}
    )
    assert response.status_code == 200
    assert response.json()["trace"]["transcript"] == ""
    assert (
        client.post(
            "/api/message", json={"session_id": "sales", "text": "card fixture"}
        ).status_code
        == 200
    )
    before = (
        built.dialogs.get_conversation("sales")
        .scenario_contexts["card_promoter"]
        .model_copy(deep=True)
    )
    intelligence = built.registry.get("fraud_security").intelligence
    intelligence.agent.analyze = AsyncMock(
        return_value=SecurityDecision(
            intent="concern",
            language="ru",
            response_language="ru",
            risk_relevant=True,
            level="high",
            signals=[RiskSignal.BANK_IMPERSONATION, RiskSignal.OTP_REQUESTED],
            recommended_action="security_review",
            case_type="social_engineering",
        )
    )
    built.messages.risk = intelligence
    assert (
        client.post(
            "/api/message", json={"session_id": "sales", "text": "Звонят из банка и просят SMS-код"}
        ).status_code
        == 200
    )
    after = built.dialogs.get_conversation("sales").scenario_contexts["card_promoter"]
    assert before.state == after.state and before.result == after.result
    journey = client.get("/api/analytics/sessions/sales").json()
    assert sum(e["event_type"] == "sales_lead" for e in journey["events"]) == 2
    assert sum(e["event_type"] == "risk_signal" for e in journey["events"]) == 1
    assert (
        client.post(
            "/api/message",
            json={
                "session_id": "fraud",
                "scenario_mode": "fraud_security",
                "text": "caller fixture",
            },
        ).status_code
        == 200
    )
    assert (
        client.get("/api/analytics/events", params={"event_type": "fraud_case"}).json()["total"]
        == 1
    )


def test_restart_application_keeps_events(tmp_path):
    config = Settings(_env_file=None, event_db_path=tmp_path / "persistent.db")
    with TestClient(create_app(config, router_override=RouterFixture(decision()))) as first:
        assert (
            first.post(
                "/api/message", json={"session_id": "restart", "text": "fixture"}
            ).status_code
            == 200
        )
        stored = first.get("/api/analytics/sessions/restart").json()
    with TestClient(create_app(config, router_override=RouterFixture())) as second:
        assert second.get("/api/analytics/sessions/restart").json() == stored
        assert second.app.state.services.dialogs.get_conversation("restart") is None


def test_raw_transcripts_and_private_state_are_not_an_event_archive(client):
    sensitive = (
        "phone +77018887766 IIN 991122334455 OTP 654321 PIN 8437 CVV 987 "
        "password privatePassword API sk-testSecret"
    )
    response = client.post(
        "/api/message", json={"session_id": "transcript-privacy", "text": sensitive}
    )
    assert response.status_code == 200
    journey = client.get("/api/analytics/sessions/transcript-privacy").json()
    assert journey["total"] == 4
    serialized = str(journey)
    for value in ("+77018887766", "991122334455", "privatePassword", "sk-testSecret"):
        assert value not in serialized
    assert "654321" not in str([event["payload"] for event in journey["events"]])
    assert "transcript" not in journey["events"][0]["payload"]


def test_terminal_security_guidance_persists_updated_sales_result(client):
    built = client.app.state.services
    assert (
        client.post(
            "/api/conversation/start",
            json={
                "session_id": "risk-terminal",
                "scenario_mode": "card_promoter",
            },
        ).status_code
        == 200
    )
    intelligence = built.registry.get("fraud_security").intelligence
    intelligence.agent.analyze = AsyncMock(
        return_value=SecurityDecision(
            intent="operator_request",
            language="ru",
            response_language="ru",
            risk_relevant=True,
            level="high",
            signals=[RiskSignal.OTP_REQUESTED],
            recommended_action="operator_handoff",
        )
    )
    built.messages.risk = intelligence
    response = client.post(
        "/api/message",
        json={
            "session_id": "risk-terminal",
            "text": "Просят SMS код. Соедините с оператором.",
        },
    )
    assert response.status_code == 200 and response.json()["conversation_status"] == "handoff"
    journey = client.get("/api/analytics/sessions/risk-terminal").json()
    result = [e for e in journey["events"] if e["event_type"] == "sales_lead"][-1]
    assert result["result_status"] == "handoff" and result["payload"]["handoff"]
    assert journey["events"][-1]["event_type"] == "operator_handoff"
