import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.analytics.mapping import map_turn_events
from app.analytics.models import (
    ConversationEvent,
    EventQuery,
    RiskPayload,
    StartedPayload,
    TurnPayload,
    make_event,
)
from app.analytics.sqlite import SQLiteEventStore
from app.packs.contracts import GlobalConversationContext
from app.packs.fraud_security.models import FraudCaseResult
from app.packs.insurance_manager.pack import InsuranceResult
from app.packs.product_promoter.models import SalesLeadResult
from app.risk.models import RiskAssessment, RiskSignal

EPOCH = datetime(2026, 10, 3, tzinfo=UTC)
PRIVATE = [
    "+77018887766",
    "991122334455",
    "654321",
    "8437",
    "987",
    "privatePassword",
    "sk-testSecret",
]


def event(session="storage-test", turn=1, **overrides):
    return make_event(
        **{
            "created_at": EPOCH + timedelta(minutes=turn),
            "session_id": session,
            "turn_number": turn,
            "sequence": 0,
            "channel": "text",
            "assistant_id": "card_promoter",
            "event_type": "conversation_turn",
            "conversation_status": "active",
            "payload": TurnPayload(assistant_initiated=False),
            **overrides,
        }
    )


@pytest.fixture
def store(tmp_path):
    return SQLiteEventStore(tmp_path / "nested" / "events.db")


def test_initialization_schema_indexes_and_wal(store):
    store.initialize()
    store.initialize()
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        indexes = {row[1] for row in db.execute("PRAGMA index_list(events)")}
        assert {
            "events_created",
            "events_session",
            "events_assistant",
            "events_type",
            "events_risk",
        } <= indexes
    store.probe()


def test_append_duplicate_and_recreation(store):
    first = event()
    assert store.append(first) == 1
    assert store.append(first) == 0
    assert store.append(first.model_copy(update={"event_id": uuid4()})) == 0
    recreated = SQLiteEventStore(store.path)
    assert recreated.get_event(first.event_id) == first
    assert recreated.get_recent_events().total == 1
    assert recreated.get_event(uuid4()) is None


def test_atomic_batch_rolls_back_on_constraint_error(store):
    first = event()
    collision = event(turn=2).model_copy(update={"event_id": first.event_id})
    with pytest.raises(sqlite3.IntegrityError):
        store.append_many([first, collision])
    assert store.get_recent_events().total == 0


def test_schema_boundary_revalidates_payloads(store):
    bad = event().model_copy(update={"payload": {"kind": "conversation_turn", "phone": PRIVATE[0]}})
    with pytest.raises(ValidationError):
        store.append_many([event("valid"), bad])
    assert store.get_recent_events().total == 0


def test_session_order_and_pagination(store):
    events = [event(turn=n, sequence=i) for n, i in [(2, 2), (1, 3), (1, 0), (2, 0)]]
    # One event of each type per turn: use distinct result/signal discriminators.
    events[0] = event(
        turn=2,
        sequence=2,
        event_type="risk_signal",
        payload=RiskPayload(analysis_status="analyzed", recommended_action="security_review"),
    )
    events[1] = event(
        turn=1,
        sequence=3,
        event_type="risk_signal",
        payload=RiskPayload(analysis_status="analyzed", recommended_action="security_review"),
    )
    assert store.append_many(events) == 4
    page = store.get_session_events("storage-test", limit=2)
    assert [(e.turn_number, e.sequence) for e in page.events] == [(1, 0), (1, 3)]
    assert page.total == 4 and page.next_offset == 2
    assert store.get_session_events("storage-test", offset=2).next_offset is None
    assert store.get_session_events("missing").events == []
    assert store.get_recent_events(1).events[0].turn_number == 2


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({"from_time": EPOCH + timedelta(minutes=2)}, 2),
        ({"to_time": EPOCH + timedelta(minutes=2)}, 1),
        ({"assistant_id": "insurance_manager"}, 1),
        ({"event_type": "risk_signal"}, 1),
        ({"risk_level": "high"}, 1),
        ({"channel": "voice"}, 1),
        ({"source": "synthetic_demo"}, 1),
        ({"session_id": "other"}, 1),
        ({"assistant_id": "fraud_security"}, 0),
    ],
)
def test_query_filters(store, filters, expected):
    store.append_many(
        [
            event(),
            event("other", 2, assistant_id="insurance_manager", channel="voice"),
            event(
                turn=3,
                source="synthetic_demo",
                risk_level="high",
                event_type="risk_signal",
                risk_signals=[RiskSignal.OTP_REQUESTED],
                payload=RiskPayload(
                    analysis_status="analyzed", recommended_action="security_review"
                ),
            ),
        ]
    )
    assert store.query_events(EventQuery(**filters)).total == expected


@pytest.mark.parametrize(
    "values",
    [
        {"limit": 0},
        {"limit": 501},
        {"offset": -1},
        {"offset": 1000001},
        {"from_time": EPOCH, "to_time": EPOCH},
        {"from_time": datetime(2026, 1, 1)},
        {"channel": "web"},
        {"risk_level": "certain_attack"},
    ],
)
def test_query_validation(values):
    with pytest.raises(ValidationError):
        EventQuery(**values)


def test_concurrent_writes_use_separate_connections(store):
    store.initialize()
    with ThreadPoolExecutor(max_workers=4) as executor:
        counts = list(executor.map(store.append, [event(f"thread-{n}") for n in range(20)]))
    assert sum(counts) == store.get_recent_events().total == 20


@pytest.mark.parametrize(
    "result,assistant,kind",
    [
        (
            InsuranceResult(
                scenario_id="SC33",
                status="active",
                completed=True,
                handoff=False,
                actions=["get_offices", PRIVATE[0]],
                collected_data=dict(
                    zip(["phone", "iin", "otp", "pin", "cvv", "password", "api_key"], PRIVATE)
                ),
                source_keys=PRIVATE,
            ),
            "insurance_manager",
            "insurance_result",
        ),
        (
            SalesLeadResult(
                status="active",
                completed=False,
                handoff=False,
                outcome="interested",
                selected_product_id=PRIVATE[0],
                presented_products=["CARD-DAILY", *PRIVATE],
            ),
            "card_promoter",
            "sales_lead",
        ),
        (
            FraudCaseResult(
                status="handoff",
                completed=True,
                handoff=True,
                case_type="social_engineering",
                facts=[RiskSignal.OTP_REQUESTED],
                risk=RiskAssessment(reason=" ".join(PRIVATE), error=PRIVATE[-1]),
            ),
            "fraud_security",
            "fraud_case",
        ),
    ],
)
def test_result_mapping_and_private_database_content(store, result, assistant, kind):
    context = GlobalConversationContext(
        session_id="privacy-safe-id", turn_number=1, conversation_status=result.status
    )
    original = result.model_copy(deep=True)
    risk = RiskAssessment(
        risk_relevant=True,
        level="high",
        signals=[RiskSignal.OTP_REQUESTED],
        reason=" ".join(PRIVATE),
        error=PRIVATE[-1],
    )
    events = map_turn_events(
        context,
        assistant,
        result,
        risk,
        previous_assistant=None,
        assistant_initiated=False,
        product_ids=frozenset({"CARD-DAILY"}),
        scenario_ids=frozenset({"SC33"}),
    )
    assert kind in {e.event_type for e in events}
    assert events[-1].event_type == ("operator_handoff" if result.handoff else "risk_signal")
    store.append_many(events)
    with sqlite3.connect(store.path) as db:
        rows = db.execute(
            "SELECT payload_json, risk_signals_json, scenario_id, session_id FROM events"
        ).fetchall()
        persisted = str(rows)
    for secret in PRIVATE:
        if len(secret) >= 10:
            assert secret not in persisted
            assert secret.encode() not in store.path.read_bytes()
        # Short numeric secrets can occur coincidentally in UUIDs, hashes or dates.
        # Verify field values, rather than asserting absence of random digit substrings.
        for payload, signals, scenario, session in rows:
            assert secret not in json.loads(payload).values()
            assert secret not in json.loads(signals)
            assert secret not in {scenario, session}
    assert result == original
    mapped = next(e for e in events if e.event_type == kind)
    if kind == "insurance_result":
        assert mapped.scenario_id == "SC33" and mapped.payload.actions == ["get_offices"]
    elif kind == "sales_lead":
        assert mapped.payload.selected_product_id is None
        assert mapped.payload.presented_product_ids == ["CARD-DAILY"]
    else:
        assert mapped.risk_signals == [RiskSignal.OTP_REQUESTED]


def test_terminal_and_start_keys_are_unique_across_turns(store):
    result = InsuranceResult(
        scenario_id="SYS_GOODBYE", status="ended", completed=True, handoff=False
    )
    for turn in (1, 2):
        store.append_many(
            map_turn_events(
                GlobalConversationContext(
                    session_id="terminal", turn_number=turn, conversation_status="ended"
                ),
                "insurance_manager",
                result,
                None,
                previous_assistant=None,
                assistant_initiated=False,
            )
        )
    summary = store.summary(EventQuery())
    assert summary.event_counts["conversation_ended"] == 1
    assert summary.event_counts["conversation_started"] == 1


def test_seed_counts_aggregate_latest_outcome_and_safe_reset(store):
    # Import the actual deterministic seed, without subprocesses or model calls.
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "seed_analytics", Path(__file__).resolve().parents[3] / "scripts/seed_analytics_demo.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    synthetic = module.synthetic_events()
    assert store.append_many(synthetic) == 640
    assert store.append_many(module.synthetic_events()) == 0
    summary = store.summary(EventQuery(source="synthetic_demo"))
    assert (summary.conversations, summary.sales.leads, summary.fraud_cases, summary.handoffs) == (
        120,
        72,
        24,
        12,
    )
    assert summary.risk.total == 40 and summary.risk.signals[RiskSignal.OTP_REQUESTED] == 40
    store.append(event("real-runtime"))
    assert store.reset_synthetic() == 640
    assert store.get_recent_events().total == 1


def test_aggregate_latest_sales_outcome_not_every_snapshot(store):
    for turn, outcome in [(1, "consulting"), (2, "interested")]:
        result = SalesLeadResult(status="active", completed=False, handoff=False, outcome=outcome)
        store.append_many(
            map_turn_events(
                GlobalConversationContext(session_id="lead", turn_number=turn),
                "card_promoter",
                result,
                None,
                previous_assistant=None if turn == 1 else "card_promoter",
                assistant_initiated=False,
            )
        )
    summary = store.summary(EventQuery(limit=1, offset=99))
    assert summary.event_counts["sales_lead"] == 2
    assert summary.sales.leads == summary.sales.interested == 1
    assert summary.results_by_assistant == {"card_promoter": 1}


def test_payload_kind_must_match_event_type():
    with pytest.raises(ValidationError):
        ConversationEvent.model_validate(
            event().model_dump() | {"payload": StartedPayload(assistant_initiated=True)}
        )
