"""Synthetic, deterministic analytics contracts; no real customers or network calls."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.schemas import RouterDecision, ScenarioSelection
from app.analytics.demo import demo_events, seed_demo
from app.analytics.service import AnalyticsService
from app.core.config import Settings
from app.events.models import ConversationEvent
from app.events.normalize import latency_values, risk_details, turn_latencies
from app.events.response import response_events
from app.events.store import InMemoryEventStore
from app.main import create_app
from app.telephony.base import CallStarted
from app.telephony.bench import FakePhoneTTS, ScriptedPhoneSTT
from app.telephony.providers.mock import MockTelephonyProvider
from app.telephony.runtime import PhoneRuntime

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
AUTH = {"Authorization": "Bearer offline-test-token"}
PREFIX = "/api/v1/analytics"


def config(**fields):
    return Settings(
        _env_file=None,
        analytics_enabled=True,
        analytics_api_token="offline-test-token",
        openai_api_key=None,
        openai_router_model=None,
        **fields,
    )


def event(kind="scenario.selected", *, minute=0, session="DEMO-test", **fields):
    return ConversationEvent(
        session_id=session,
        timestamp=(NOW + timedelta(minutes=minute)).isoformat(),
        channel=fields.pop("channel", "phone"),
        event_type=kind,
        **fields,
    )


def service(events=(), **settings):
    store = InMemoryEventStore()
    for item in events:
        store.append(item)
    return AnalyticsService(store, config(**settings))


def test_store_order_session_capacity_and_defensive_copies():
    store = InMemoryEventStore(2)
    a = event(id="a", minute=1, risk={"level": "high", "signals": []})
    store.append(a)
    a.risk["signals"].append("external mutation")
    store.append(event(id="b", minute=-1, session="DEMO-other"))
    assert [e.id for e in store.list()] == ["a", "b"]  # append order, not clock order
    result = store.get_by_session("DEMO-test")[0]
    result.risk["signals"].append("read mutation")
    assert store.list()[0].risk["signals"] == []
    store.append(event(id="c"))
    assert [e.id for e in store.list()] == ["b", "c"]
    assert store.evicted_events == 1
    assert store.get_by_session("absent") == []


@pytest.mark.parametrize(
    "query,expected",
    [
        ({"channel": "web"}, ["web"]),
        ({"scenario": "CARD_BLOCK"}, ["phone"]),
        ({"risk_level": "high"}, ["phone"]),
        ({"event_type": "agent.response"}, ["web"]),
        ({"session_id": "DEMO-other"}, ["web"]),
        ({"from_time": NOW}, ["phone"]),
        ({"to_time": NOW - timedelta(minutes=1)}, ["web"]),
        ({"from_time": NOW, "to_time": NOW}, ["phone"]),
        ({"limit": 0}, []),
    ],
)
def test_store_dimensions(query, expected):
    store = service(
        [
            event(id="phone", scenario={"scenario_id": "CARD_BLOCK"}, risk={"level": "high"}),
            event("agent.response", id="web", channel="web", session="DEMO-other", minute=-1),
        ]
    ).store
    assert [e.id for e in store.list(**query)] == expected


@pytest.mark.parametrize(
    "query",
    [
        {"limit": -1},
        {"from_time": datetime(2026, 1, 1)},
        {"from_time": NOW, "to_time": NOW - timedelta(seconds=1)},
    ],
)
def test_invalid_store_filters(query):
    with pytest.raises(ValueError):
        InMemoryEventStore().list(**query)


@pytest.mark.parametrize("channel", ["mobile", "sms", "unsupported"])
def test_exact_channels(channel):
    with pytest.raises(ValidationError):
        event(channel=channel)


@pytest.mark.parametrize("stamp", ["bad", "2026-10-02T12:00:00"])
def test_event_timestamp_validation(stamp):
    with pytest.raises(ValidationError):
        ConversationEvent(
            session_id="DEMO", event_type="session.started", channel="web", timestamp=stamp
        )


def test_event_size_bound_and_latency_update():
    store = InMemoryEventStore(1)
    with pytest.raises(ValueError, match="64KiB"):
        store.append(event(text="x" * 65536))
    store.append(event(id="a", latency={"agent_ms": 4}))
    assert store.update_latency("a", {"tts_ms": 8})
    assert store.list()[0].latency == {"agent_ms": 4, "tts_ms": 8}
    assert not store.update_latency("missing", {})
    assert store.evicted_events == 0


def test_summary_and_ordered_journey_with_action_change_and_handoff():
    records = [event("session.started", minute=-3, metadata={"provider": "vonage"})]
    for scenario, action in [
        ("LOGIN_PROBLEM", None),
        ("LOGIN_PROBLEM", None),
        ("SUSPICIOUS_TRANSACTION", None),
        ("CARD_BLOCK", ["block"]),
        ("CARD_BLOCK", ["review"]),
    ]:
        records.append(event(scenario=scenario, action=action))
    records.extend(
        [
            event("agent.response", risk={"level": "high", "signals": ["DEMO_SIGNAL"]}),
            event("agent.response"),
            event("clarification.requested", clarification=True),
            event("handoff.requested", handoff=True),
            event("conversation.ended", conversation_status="handoff"),
        ]
    )
    analytics = service(records)
    summary = analytics.sessions(now=NOW)[0]
    assert summary.scenarios == ["LOGIN_PROBLEM", "SUSPICIOUS_TRANSACTION", "CARD_BLOCK"]
    assert summary.primary_scenario == "CARD_BLOCK"  # deterministic alphabetical tie
    assert summary.last_scenario == "CARD_BLOCK"
    assert summary.risk_level == "high" and summary.latest_risk is None
    assert summary.risk_signals == ["DEMO_SIGNAL"]
    assert summary.clarification_count == 1 and summary.handoff
    assert summary.turn_count == 2 and not summary.completed and not summary.active
    assert summary.total_duration_ms == 180000
    assert summary.provider_metadata == {"provider": "vonage"}
    journey = analytics.get_journey("DEMO-test")
    assert [s.scenario for s in journey[:4]] == [
        "LOGIN_PROBLEM",
        "SUSPICIOUS_TRANSACTION",
        "CARD_BLOCK",
        "CARD_BLOCK",
    ]
    assert journey[-2].handoff and not journey[-1].completion
    assert journey[-2].scenario is None  # never fabricate an OPERATOR scenario
    assert journey[0].source_event_id == records[1].id
    assert analytics.get_journey("absent") == [] and analytics.detail("absent") is None


@pytest.mark.parametrize(
    "status,completed", [("ended", True), ("error", False), ("cancelled", False)]
)
def test_phone_terminal_metadata_and_completion(status, completed):
    analytics = service(
        [
            event("session.started"),
            event(
                "conversation.ended", conversation_status="ended", metadata={"phone_status": status}
            ),
        ]
    )
    summary = analytics.sessions(now=NOW)[0]
    assert summary.status == status and summary.completed == completed
    assert analytics.get_journey("DEMO-test")[-1].completion == completed


def test_recent_active_partial_history_and_session_filters():
    analytics = service(
        [
            event("session.started", session="DEMO-new", minute=-1),
            event("agent.response", session="DEMO-new", conversation_status="awaiting_user"),
            event("session.started", session="DEMO-old", minute=-10, channel="web"),
            event("agent.response", session="DEMO-partial", risk={"level": "low"}),
        ]
    )
    assert [s.session_id for s in analytics.sessions(now=NOW, active=True)] == ["DEMO-new"]
    assert len(analytics.sessions(now=NOW, channel="web")) == 1
    assert analytics.sessions(now=NOW, risk_level="low")[0].partial_history
    assert analytics.sessions(now=NOW, risk_level="unknown")[0].risk_level == "unknown"
    assert len(analytics.sessions(now=NOW, from_time=NOW)) == 2
    assert len(analytics.sessions(now=NOW, limit=1)) == 1


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "unknown"),
        ({}, "unknown"),
        ({"level": "bogus"}, "unknown"),
        ({"level": "low"}, "low"),
        ({"level": "high"}, "high"),
        ({"level": "critical"}, "critical"),
    ],
)
def test_risk_normalization_does_not_infer(value, expected):
    assert risk_details(value)[0] == expected


def test_risk_counts_unique_per_session_and_tie_order():
    analytics = service(
        [
            event(
                "agent.response",
                session="DEMO-a",
                risk={
                    "level": "high",
                    "signals": ["B", "A", {"code": "A"}, {"type": "B"}, {"id": "A"}],
                },
            ),
            event("agent.response", session="DEMO-a", risk={"level": "medium", "signals": ["A"]}),
            event(session="DEMO-a", scenario="CARD_BLOCK"),
            event("agent.response", session="DEMO-b"),
            event("agent.response", session="DEMO-c", risk={"level": "low"}),
        ]
    )
    result = analytics.overview().risk
    assert result.levels == {"unknown": 1, "low": 1, "medium": 0, "high": 1, "critical": 0}
    assert result.high_risk_sessions == 1
    assert [(s.key, s.count) for s in result.top_signals] == [("A", 1), ("B", 1)]
    assert result.high_risk_scenarios[0].key == "CARD_BLOCK"


def test_latencies_per_turn_not_copied_scenarios_and_distinct_semantics():
    records = [
        event("transcript.final", latency={"stt": 100}, metadata={"turn": 1}),
        event(
            "agent.response",
            metadata={"turn": 1},
            latency={
                "total": 20,
                "tts_ms": 40,
                "speech_end_to_playback_submit_ms": 1500,
                "speech_end_to_playback_complete_ms": 2500,
                "final_to_playback_complete_ms": 2300,
            },
        ),
        event(scenario="CARD_BLOCK", metadata={"turn": 1}, latency={"total": 999}),
        event("agent.response", metadata={"turn": 2}, latency={"agent_ms": 60}),
        event("agent.response", metadata={"turn": 3}),
    ]
    result = service(records).overview()
    assert result.latency["agent_ms"].average_ms == 40
    assert result.latency["agent_ms"].samples == 2
    assert result.latency["tts_ms"].average_ms == 40
    assert result.latency["stt_final_ms"].average_ms == 100
    assert result.latency["speech_end_to_playback_submit_ms"].average_ms == 1500
    assert result.latency["speech_end_to_playback_complete_ms"].average_ms == 2500
    assert result.latency["final_to_playback_complete_ms"].average_ms == 2300
    assert result.latency["endpointing_ms"].average_ms is None
    assert len(turn_latencies(records)) == 3
    assert latency_values({"agent_ms": True, "tts_ms": -1, "endpointing_ms": "100"}) == {}


def counts(baseline, current):
    return [event(minute=-90, scenario="DEMO_SCENARIO") for _ in range(baseline)] + [
        event(minute=-1, scenario="DEMO_SCENARIO") for _ in range(current)
    ]


@pytest.mark.parametrize(
    "baseline,current,expected,severity,ratio",
    [
        (24, 4, 0, None, None),
        (24, 12, 1, "low", 3),
        (24, 16, 1, "medium", 4),
        (24, 24, 1, "high", 6),
        (0, 4, 0, None, None),
        (0, 5, 1, "medium", None),
    ],
)
def test_anomaly_thresholds_and_zero_baseline(baseline, current, expected, severity, ratio):
    analytics = service(counts(baseline, current))
    result = analytics.anomalies(now=NOW)
    assert len(result) == expected
    assert result == analytics.anomalies(now=NOW)
    if result:
        anomaly = result[0]
        assert (anomaly.severity, anomaly.ratio) == (severity, ratio)
        assert (
            anomaly.baseline_count == baseline and anomaly.baseline_expected_count == baseline / 6
        )
        assert "abnormal increase" in anomaly.explanation
        assert "confirmed" not in anomaly.explanation
        assert anomaly.window["seconds"] == 3600


def test_anomaly_window_boundaries_signal_counts_configuration_and_eviction():
    records = [
        event(minute=-420, scenario="DEMO_A"),
        event(minute=-420.01, scenario="DEMO_A"),
        event(minute=-60, scenario="DEMO_A"),
        event(minute=0, scenario="DEMO_A"),
        event(minute=0.01, scenario="DEMO_A"),
    ]
    analytics = service(records, analytics_min_volume=2, analytics_baseline_windows=6)
    result = analytics.anomalies(now=NOW)[0]
    assert (result.current_count, result.baseline_count) == (2, 1)
    signal = service(
        [event("agent.response", risk={"signals": ["DEMO_R", "DEMO_R"]}) for _ in range(5)]
    ).anomalies(now=NOW)[0]
    assert signal.metric == "risk_signal" and signal.current_count == 5
    store = InMemoryEventStore(5)
    for item in counts(1, 5):
        store.append(item)
    assert AnalyticsService(store, config()).anomalies(now=NOW)[0].partial_history
    assert service(counts(24, 12), analytics_anomaly_multiplier=4).anomalies(now=NOW) == []


def test_demo_is_deterministic_synthetic_and_has_all_representative_flows():
    first = demo_events(NOW)
    assert first == demo_events(NOW)
    assert all(e.session_id.startswith("DEMO-") and e.metadata["demo"] is True for e in first)
    assert all(e.text is None or e.text.startswith("[DEMO]") for e in first)
    assert {e.channel for e in first} == {"web", "phone"}
    analytics = service(first)
    result = analytics.overview()
    assert result.total_sessions == 38
    assert result.risk.levels["high"] == 12 and result.risk.levels["unknown"] == 2
    assert result.clarification_count == 1 and result.handoff_count == 13
    anomaly = next(a for a in analytics.anomalies(now=NOW) if a.metric == "scenario")
    assert (anomaly.baseline_expected_count, anomaly.current_count, anomaly.ratio) == (4, 12, 3)
    assert [s.scenario for s in analytics.get_journey("DEMO-journey")[:3]] == [
        "LOGIN_PROBLEM",
        "SUSPICIOUS_TRANSACTION",
        "CARD_BLOCK",
    ]
    store = InMemoryEventStore()
    assert seed_demo(store, NOW) == len(first)


@pytest.mark.parametrize("suffix", ["overview", "sessions", "scenarios", "risk", "anomalies"])
def test_empty_api_typed_shapes(suffix):
    with TestClient(create_app(config())) as client:
        response = client.get(f"{PREFIX}/{suffix}", headers=AUTH)
        assert response.status_code == 200
        body = response.json()
        if suffix == "overview":
            assert body["total_sessions"] == 0 and body["handoff_rate"] == 0
            assert body["clarification_rate"] == 0
            assert body["latency"]["agent_ms"] == {"average_ms": None, "samples": 0}
        elif suffix == "risk":
            assert body["high_risk_sessions"] == 0
        else:
            assert body == []
        assert len(client.app.state.event_store.list()) == 0  # demo opt-in only


def test_api_demo_filters_detail_journey_missing_and_auth():
    with TestClient(create_app(config(analytics_demo_enabled=True))) as client:
        assert client.get(f"{PREFIX}/overview").status_code == 403
        assert (
            client.get(f"{PREFIX}/overview", headers={"Authorization": "Bearer wrong"}).status_code
            == 403
        )
        overview = client.get(f"{PREFIX}/overview", headers=AUTH).json()
        assert overview["total_sessions"] == 38
        phones = client.get(f"{PREFIX}/sessions?channel=phone&active=true", headers=AUTH).json()
        assert len(phones) == 1 and phones[0]["session_id"] == "DEMO-recent"
        assert phones[0]["latest_latency"] == {} and phones[0]["risk_level"] == "unknown"
        high = client.get(f"{PREFIX}/sessions?risk_level=high&limit=3", headers=AUTH).json()
        assert len(high) == 3
        assert (
            client.get(f"{PREFIX}/sessions?channel=web&scenario=CARD_BLOCK", headers=AUTH).json()[
                0
            ]["session_id"]
            == "DEMO-journey"
        )
        detail = client.get(f"{PREFIX}/sessions/DEMO-journey", headers=AUTH).json()
        assert len(detail["timeline"]) == 12 and detail["summary"]["turn_count"] == 4
        assert len(client.get(f"{PREFIX}/sessions/DEMO-journey/journey", headers=AUTH).json()) == 6
        assert client.get(f"{PREFIX}/anomalies", headers=AUTH).json()
        for suffix in ["sessions/absent", "sessions/absent/journey"]:
            assert client.get(f"{PREFIX}/{suffix}", headers=AUTH).status_code == 404


@pytest.mark.parametrize(
    "query",
    [
        "channel=mobile",
        "risk_level=fraud",
        "limit=0",
        "limit=501",
        "from=2026-10-02T12:00:00",
        "from=2026-10-03T00:00:00Z&to=2026-10-02T00:00:00Z",
        "scenario=",
        "session_id=",
    ],
)
def test_api_query_validation(query):
    with TestClient(create_app(config())) as client:
        assert client.get(f"{PREFIX}/sessions?{query}", headers=AUTH).status_code == 422


@pytest.mark.parametrize("fields", [{"analytics_enabled": False}, {"analytics_api_token": None}])
def test_analytics_disabled_or_unconfigured_fails_closed(fields):
    settings = config().model_copy(update=fields)
    with TestClient(create_app(settings)) as client:
        assert client.get(f"{PREFIX}/overview", headers=AUTH).status_code == 503


class RouterFixture:
    async def route(self, text, state):
        return RouterDecision(
            language="ru",
            scenarios=[
                ScenarioSelection(
                    scenario_id="SC33", confidence=0.95, reason="[DEMO] Offline contract"
                )
            ],
            slots={},
        )


def test_web_server_events_risk_preservation_and_untrusted_metadata():
    with TestClient(create_app(config(), router_override=RouterFixture())) as client:
        original = client.app.state.services.messages.process

        async def with_agent_risk(session_id, text):
            result = await original(session_id, text)
            return result.model_copy(update={"risk": {"level": "high", "signals": ["DEMO_R"]}})

        client.app.state.services.messages.process = with_agent_risk
        response = client.post(
            "/api/message",
            json={
                "session_id": "DEMO-web",
                "text": "[DEMO]",
                "transport": {"language": "kk", "stt_after_commit_ms": 25},
            },
        )
        assert response.status_code == 200 and response.json()["risk"]["level"] == "high"
        events = client.app.state.event_store.get_by_session("DEMO-web")
        assert [e.event_type for e in events[:4]] == [
            "session.started",
            "transcript.final",
            "agent.response",
            "scenario.selected",
        ]
        assert all(e.channel == "web" for e in events)
        assert events[1].latency == {"client_stt_final_ms": 25}
        assert events[3].scenario["scenario_id"] == "SC33"
        assert client.app.state.analytics.sessions()[0].risk_level == "high"
        for transport in [
            {"scenario": "CARD_BLOCK"},
            {"risk": {"level": "low"}},
            {"routing": {}},
            {"channel": "phone"},
            {"language": "unsupported"},
            {"stt_after_commit_ms": -1},
            {"stt_after_commit_ms": 150001},
        ]:
            assert (
                client.post(
                    "/api/message",
                    json={"session_id": "DEMO-web", "text": "[DEMO]", "transport": transport},
                ).status_code
                == 422
            )
        client.app.state.event_store.append(event("session.started", session="DEMO-phone"))
        assert (
            client.post(
                "/api/message", json={"session_id": "DEMO-phone", "text": "[DEMO]"}
            ).status_code
            == 409
        )


@pytest.mark.parametrize("provider", ["vonage", "twilio"])
def test_phone_runtime_uses_canonical_application_store_and_exposes_existing_timings(provider):
    class Agent:
        async def process(self, session_id, text):
            return {
                "session_id": session_id,
                "response_text": "[DEMO]",
                "conversation_status": "active",
                "risk": {"level": "high", "signals": ["DEMO_PHONE_SIGNAL"]},
                "routing": {"scenarios": [{"scenario_id": "CARD_BLOCK", "confidence": 0.9}]},
            }

    runtime = PhoneRuntime(Agent(), ScriptedPhoneSTT(), FakePhoneTTS(), MockTelephonyProvider())
    gateway = SimpleNamespace(runtime=runtime, shutdown=runtime.shutdown)
    overrides = {f"{provider}_override": gateway}
    with TestClient(create_app(config(), router_override=RouterFixture(), **overrides)) as client:
        assert runtime.event_store is client.app.state.event_store

        async def run():
            session = runtime.start_call(CallStarted("DEMO-call", {"provider": provider}))
            assert await runtime.handle_transcript(
                "DEMO-call",
                {"type": "utterance.final", "text": "[DEMO]", "stt_after_commit_ms": 10},
            )
            async with asyncio.timeout(1):
                while not runtime.provider.outgoing["DEMO-call"]:
                    await asyncio.sleep(0)
            await asyncio.sleep(0)
            return session.session_id

        session_id = client.portal.call(run)
        detail = client.get(f"{PREFIX}/sessions/{session_id}", headers=AUTH).json()
        assert detail["summary"]["channel"] == "phone"
        assert detail["summary"]["provider_metadata"]["provider"] == provider
        assert detail["summary"]["last_scenario"] == "CARD_BLOCK"
        latency = detail["summary"]["latest_latency"]
        assert latency["agent_ms"] >= 0 and latency["tts_ms"] >= 0
        assert latency["stt_final_ms"] == 10 and latency["final_to_playback_complete_ms"] >= 0
        assert "speech_end_to_playback_complete_ms" not in latency
        client.portal.call(runtime.end_call, "DEMO-call")
        assert not client.app.state.analytics.sessions(session_id=session_id)[0].active
        response = client.post(
            "/api/message", json={"session_id": "DEMO-shared-web", "text": "[DEMO]"}
        )
        assert response.status_code == 200 and "risk" not in response.json()
        overview = client.get(f"{PREFIX}/overview", headers=AUTH).json()
        assert overview["sessions_by_channel"] == {"web": 1, "phone": 1}


def test_optional_response_payloads_do_not_require_risk_routing_state_trace():
    records = list(
        response_events(
            "DEMO-minimal", "web", {"response_text": "[DEMO]", "conversation_status": "active"}
        )
    )
    assert len(records) == 1 and records[0].risk is None
    summary = service(records).sessions()[0]
    assert summary.risk_level == "unknown" and summary.scenarios == []


def test_extraction_priority_and_opaque_passthrough():
    payload = {
        "response_text": "[DEMO]",
        "conversation_status": "active",
        "routing": {"scenarios": [{"scenario_id": "WRONG_FALLBACK"}], "language": "kk"},
        "trace": {
            "scenarios": [{"scenario_id": "CARD_BLOCK", "confidence": 0.9}],
            "actions": ["operator_review"],
            "language": "ru",
            "clarification": True,
        },
        "state": {"language": "mixed", "active_scenario": "NOT_A_TRANSITION"},
        "risk": {"level": "high", "recommended_action": "operator_review"},
    }
    records = list(response_events("DEMO-extraction", "web", payload))
    assert records[0].risk == payload["risk"] and records[0].state == payload["state"]
    assert records[0].language == "ru" and records[0].action == ["operator_review"]
    assert records[1].scenario == payload["trace"]["scenarios"][0]
    assert records[-1].event_type == "clarification.requested"
    payload["trace"] = None
    payload["routing"] = {"selections": ["CARD_BLOCK"]}
    records = list(response_events("DEMO-extraction", "web", payload))
    assert records[0].language == "mixed" and records[1].scenario == "CARD_BLOCK"


def test_web_recording_failure_is_safe_and_does_not_break_message(caplog):
    with TestClient(create_app(config(), router_override=RouterFixture())) as client:

        def broken_store(value):
            raise RuntimeError("PRIVATE_EXCEPTION_CONTENT")

        client.app.state.event_store.append = broken_store
        response = client.post("/api/message", json={"session_id": "DEMO-error", "text": "[DEMO]"})
        assert response.status_code == 200
        assert "event_recording_failed exception_type=RuntimeError" in caplog.text
        assert "PRIVATE_EXCEPTION_CONTENT" not in caplog.text


def test_api_time_membership_preserves_full_retained_session_history():
    with TestClient(create_app(config())) as client:
        for item in [
            event("session.started", minute=-10),
            event(scenario="CARD_BLOCK", minute=-9),
            event("agent.response", minute=-1, risk={"level": "high"}),
        ]:
            client.app.state.event_store.append(item)
        result = client.get(
            f"{PREFIX}/sessions",
            params={
                "from": (NOW - timedelta(minutes=2)).isoformat(),
                "to": NOW.isoformat(),
                "risk_level": "high",
            },
            headers=AUTH,
        )
        assert result.status_code == 200 and len(result.json()) == 1
        assert result.json()[0]["scenarios"] == ["CARD_BLOCK"]
        assert result.json()[0]["started_at"] == (NOW - timedelta(minutes=10)).isoformat()
        assert client.get(f"{PREFIX}/scenarios", headers=AUTH).json() == [
            {"key": "CARD_BLOCK", "count": 1}
        ]
        assert client.get(f"{PREFIX}/risk", headers=AUTH).json()["high_risk_sessions"] == 1


def test_latest_turn_without_metrics_does_not_reuse_older_latency():
    summary = service(
        [
            event("agent.response", metadata={"turn": 1}, latency={"agent_ms": 100}),
            event("agent.response", metadata={"turn": 2}),
        ]
    ).sessions()[0]
    assert summary.average_agent_ms == 100 and summary.latest_latency == {}


def test_evicted_web_history_does_not_fabricate_a_new_session_start():
    with TestClient(create_app(config(), router_override=RouterFixture())) as client:
        payload = {"session_id": "DEMO-retention", "text": "[DEMO]"}
        assert client.post("/api/message", json=payload).status_code == 200
        # Simulate entire history eviction without resetting the actual Agent session.
        client.app.state.event_store = InMemoryEventStore()
        client.app.state.analytics.store = client.app.state.event_store
        response = client.post("/api/message", json=payload)
        assert response.status_code == 200 and response.json()["trace"]["turn"] == 2
        summary = client.app.state.analytics.sessions()[0]
        assert summary.partial_history and summary.started_at is None
        assert summary.total_duration_ms is None
