import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analytics.dashboard import AnalyticsService
from app.analytics.dashboard_models import DashboardQuery
from app.analytics.models import make_event
from app.analytics.sqlite import SQLiteEventStore
from app.core.config import Settings
from app.main import create_app

spec = importlib.util.spec_from_file_location(
    "dashboard_seed", Path(__file__).parents[3] / "scripts/seed_analytics_demo.py"
)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)
NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


@pytest.fixture
def service(tmp_path):
    store = SQLiteEventStore(tmp_path / "dashboard.db")
    return AnalyticsService(store, Settings(_env_file=None))


@pytest.fixture
def client(service):
    with TestClient(create_app(Settings(_env_file=None))) as active:
        active.app.state.services.analytics = service
        active.app.state.services.events.store = service.store
        yield active


def test_empty_dashboard_and_backwards_compatibility(client):
    overview = client.get("/api/analytics/overview").json()
    assert overview["total_sessions"] == 0
    assert overview["sessions_by_channel"] == {"text": 0, "voice": 0}
    assert overview["latency"]["agent_ms"] == {"average_ms": None, "samples": 0}
    assert client.get("/api/analytics/sessions").json()["sessions"] == []
    assert client.get("/api/analytics/anomalies").json()["history_status"] == "insufficient_history"
    assert client.get("/api/analytics/sessions/absent/detail").status_code == 404
    assert client.get("/api/analytics/sessions/absent").status_code == 200
    assert client.get("/api/analytics/sessions/absent/journey").json()["stages"] == []


def test_seed_overview_aggregates_full_history_not_first_page(service):
    service.store.append_many(seed.synthetic_events())
    data = service.overview(DashboardQuery(limit=1, as_of=NOW))
    assert data.total_sessions == 120 and data.retained_events == 640
    assert data.sources == {"synthetic_demo": 120}
    assert data.sessions_by_channel == {"text": 60, "voice": 60}
    assert data.handoff_count == 12 and data.insurance_completed == 24
    assert sum(x.count for x in data.sales_outcomes) == 72
    assert data.risk.high_risk_sessions == 40
    assert {x.key for x in data.sessions_by_scenario} == {
        "insurance_manager",
        "product_promoter",
        "card_promoter",
        "loan_promoter",
        "fraud_security",
    }


def test_sessions_results_and_journey_order(client, service):
    service.store.append_many(seed.synthetic_events())
    page = client.get("/api/analytics/sessions", params={"limit": 7}).json()
    assert page["total"] == 120 and page["next_offset"] == 7
    following = client.get("/api/analytics/sessions", params={"limit": 7, "offset": 7}).json()
    assert {s["session_id"] for s in page["sessions"]}.isdisjoint(
        s["session_id"] for s in following["sessions"]
    )
    identity = "synthetic-demo-v1-002"
    detail = client.get(f"/api/analytics/sessions/{identity}/detail").json()
    assert detail["summary"]["source"] == "synthetic_demo"
    assert detail["summary"]["results"][0]["payload"]["campaign"] == "card"
    assert detail["summary"]["completed"] and not detail["summary"]["active"]
    stages = client.get(f"/api/analytics/sessions/{identity}/journey").json()["stages"]
    assert [e["event_type"] for e in stages] == [
        "conversation_started",
        "assistant_selected",
        "sales_lead",
        "conversation_ended",
    ]
    assert [e["id"] for e in stages] == [
        e["event_id"] for e in detail["timeline"] if e["event_type"] != "conversation_turn"
    ]
    assert client.get(f"/api/analytics/sessions/{identity}").json()["events"] == detail["timeline"]


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"source": "runtime"}, 0),
        ({"source": "synthetic_demo"}, 120),
        ({"channel": "voice"}, 60),
        ({"assistant_id": "card_promoter"}, 24),
        ({"risk_level": "unknown"}, 80),
        ({"risk_level": "high"}, 28),
        ({"active": "true"}, 0),
        ({"session_id": "synthetic-demo-v1-002"}, 1),
        ({"from": "2026-10-03T09:00:00Z", "to": "2026-10-03T10:00:00Z"}, 60),
    ],
)
def test_dashboard_filters(client, service, params, expected):
    service.store.append_many(seed.synthetic_events())
    response = client.get("/api/analytics/sessions", params=params)
    assert response.status_code == 200 and response.json()["total"] == expected
    assert client.get("/api/analytics/overview", params=params).json()["total_sessions"] == expected


@pytest.mark.parametrize(
    "params",
    [
        {"channel": "phone"},
        {"assistant_id": "CARD_BLOCK"},
        {"source": "demo"},
        {"limit": 501},
        {"offset": -1},
        {"risk_level": "fraud_confirmed"},
        {"as_of": "2026-10-03T12:00:00"},
        {"from": "2026-10-04T00:00:00Z", "to": "2026-10-03T00:00:00Z"},
    ],
)
def test_invalid_filters(client, params):
    assert client.get("/api/analytics/sessions", params=params).status_code == 422


def test_risk_and_scenario_counts_are_backend_authoritative(service):
    service.store.append_many(seed.synthetic_events())
    risk = service.risk(DashboardQuery())
    assert risk.levels["unknown"] == 80 and risk.levels["critical"] == 12
    assert {x.key: x.count for x in risk.top_signals}["otp_requested_by_third_party"] == 40
    assert risk.fraud_case_types[0].count == 24
    assert all(x.count == 24 for x in service.scenarios(DashboardQuery()))


def test_persistent_anomaly_source_separation_and_boundaries(service):
    service.store.append_many(seed.anomaly_events(NOW))
    query = DashboardQuery(as_of=NOW, source="synthetic_demo")
    page = service.anomalies(query)
    assert page.history_status == "ready" and page.total == 2
    otp = next(a for a in page.anomalies if a.metric == "risk_signal")
    assert otp.current_count == 18 and otp.baseline_count == 6 and otp.ratio == 18
    assert "Cause is not established" in otp.explanation
    reopened = AnalyticsService(SQLiteEventStore(service.store.path), service.settings)
    assert reopened.anomalies(query) == page
    assert (
        service.anomalies(DashboardQuery(as_of=NOW, source="runtime")).history_status
        == "insufficient_history"
    )
    # Current upper bound exclusive.
    after = seed.anomaly_events(NOW)[-1].model_dump(exclude={"event_id"})
    after.update(session_id="upper-bound", created_at=NOW)
    service.store.append(make_event(**after))
    assert service.anomalies(query) == page


def test_cold_start_zero_baseline_and_minimum_volume(service):
    recent = seed.anomaly_events(NOW)[12:]
    service.store.append_many(recent)
    assert service.anomalies(DashboardQuery(as_of=NOW)).history_status == "insufficient_history"
    # Old lifecycle data alone does not establish a positive metric baseline.
    first = seed.anomaly_events(NOW)[0]
    service.store.append(first)
    assert service.anomalies(DashboardQuery(as_of=NOW)).anomalies == []
    service.store.append_many(seed.anomaly_events(NOW)[:12])
    service.settings.analytics_min_volume = 19
    assert service.anomalies(DashboardQuery(as_of=NOW)).anomalies == []


def test_latest_result_snapshot_and_unknown_analysis(service):
    event = seed.synthetic_events()[0]
    values = event.model_dump(exclude={"event_id"})
    values.update(created_at=NOW - timedelta(minutes=1), conversation_status="awaiting_user")
    service.store.append(make_event(**values))
    summary = service.sessions(DashboardQuery(as_of=NOW)).sessions[0]
    assert summary.active and summary.risk_level == "unknown" and not summary.completed
    assert summary.average_agent_ms is None


def test_storage_degraded_is_503_not_zero(client, service, monkeypatch):
    def fail(_query):
        raise OSError("PRIVATE_PATH_AND_ERROR")

    monkeypatch.setattr(service.store, "analytics_snapshot", fail)
    for route in (
        "overview",
        "sessions",
        "risk",
        "scenarios",
        "anomalies",
        "sessions/x/detail",
        "sessions/x/journey",
    ):
        response = client.get("/api/analytics/" + route)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "analytics_storage_unavailable"
        assert "PRIVATE" not in response.text


def test_read_only_openapi_and_anomaly_filter_errors(client):
    paths = client.get("/openapi.json").json()["paths"]
    for suffix in (
        "overview",
        "sessions",
        "risk",
        "scenarios",
        "anomalies",
        "sessions/{session_id}/detail",
        "sessions/{session_id}/journey",
    ):
        assert set(paths["/api/analytics/" + suffix]) == {"get"}
    assert client.get("/api/analytics/anomalies", params={"active": True}).status_code == 422
    assert client.post("/api/analytics/sessions").status_code == 405


@pytest.mark.parametrize(
    "analysis_status,level,expected",
    [
        ("analyzed", "none", "none"),
        ("unavailable", None, "unknown"),
        ("invalid_output", None, "unknown"),
    ],
)
def test_analyzed_none_is_distinct_from_unavailable(service, analysis_status, level, expected):
    values = seed.anomaly_events(NOW)[1].model_dump(exclude={"event_id"})
    values.update(
        risk_level=level,
        risk_signals=[],
        payload={
            "kind": "risk_signal",
            "analysis_status": analysis_status,
            "recommended_action": "none",
        },
    )
    service.store.append(make_event(**values))
    summary = service.sessions(DashboardQuery(as_of=NOW)).sessions[0]
    assert summary.risk_level == expected and summary.partial_history


def test_latest_sales_result_counts_once_per_assistant_and_session(service):
    events = [e for e in seed.synthetic_events() if e.session_id == "synthetic-demo-v1-002"]
    service.store.append_many(events)
    lead = next(e for e in events if e.event_type == "sales_lead")
    values = lead.model_dump(exclude={"event_id"})
    values.update(turn_number=2, created_at=NOW)
    values["payload"].update(outcome="declined", interest_level="declined", next_action="declined")
    service.store.append(make_event(**values))
    data = service.overview(DashboardQuery())
    assert data.sales_outcomes[0].key == "declined" and data.sales_outcomes[0].count == 1
    assert data.total_sessions == 1
    assert service.detail(lead.session_id, DashboardQuery()).summary.results[0].turn_number == 2


def test_mixed_source_scope_and_real_storage_failure(client, service, tmp_path):
    service.store.append_many(seed.synthetic_events())
    event = seed.synthetic_events()[0].model_dump(exclude={"event_id"})
    event.update(session_id="runtime-only", source="runtime")
    service.store.append(make_event(**event))
    data = client.get("/api/analytics/overview").json()
    assert data["sources"] == {"runtime": 1, "synthetic_demo": 120}
    assert client.get("/api/analytics/sessions", params={"source": "runtime"}).json()["total"] == 1
    service.store = SQLiteEventStore(tmp_path)  # Directory cannot be opened as SQLite DB.
    response = client.get("/api/analytics/overview")
    assert (
        response.status_code == 503
        and response.json()["detail"]["code"] == "analytics_storage_unavailable"
    )
