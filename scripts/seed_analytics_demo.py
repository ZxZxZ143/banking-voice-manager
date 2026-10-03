"""Deterministic synthetic events. --reset deletes only source=synthetic_demo.

Run from the repository root after installing backend, no credentials/model calls.
"""

import argparse
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.analytics.mapping import map_turn_events
from app.analytics.models import EventQuery, make_event
from app.analytics.sqlite import SQLiteEventStore
from app.core.config import Settings
from app.packs.contracts import GlobalConversationContext
from app.packs.fraud_security.models import FraudCaseResult
from app.packs.insurance_manager.pack import InsuranceResult
from app.packs.product_promoter.models import SalesLeadResult
from app.risk.models import RiskAssessment, RiskSignal


def synthetic_events():
    events = []
    epoch = datetime(2026, 10, 3, 8, tzinfo=UTC)
    for index in range(120):
        assistant = (
            "insurance_manager",
            "product_promoter",
            "card_promoter",
            "loan_promoter",
            "fraud_security",
        )[index % 5]
        status = "handoff" if index % 10 == 4 else "ended"
        risk = (
            RiskAssessment(
                risk_relevant=True,
                level="critical" if status == "handoff" else "high",
                signals=[RiskSignal.BANK_IMPERSONATION, RiskSignal.OTP_REQUESTED],
                recommended_action="operator_handoff"
                if status == "handoff"
                else "security_review",
            )
            if index % 6 == 0 or assistant == "fraud_security"
            else None
        )
        common = {"status": status, "handoff": status == "handoff", "completed": True}
        if assistant == "insurance_manager":
            result = InsuranceResult(
                scenario_id="SC33", actions=["get_offices"], **common
            )
        elif assistant == "fraud_security":
            result = FraudCaseResult(
                case_type="social_engineering",
                case_status="needs_review",
                facts=risk.signals,
                risk=risk,
                **common,
            )
        else:
            category, product = {
                "product_promoter": ("deposit", "DEP-FLEX"),
                "card_promoter": ("card", "CARD-DAILY"),
                "loan_promoter": ("loan", "LOAN-PERSONAL"),
            }[assistant]
            outcome = "declined" if index % 3 == 0 else "interested"
            result = SalesLeadResult(
                outcome=outcome,
                product_category=category,
                selected_product_id=product,
                presented_products=[product],
                interest_level="declined" if outcome == "declined" else "high",
                next_action="declined"
                if outcome == "declined"
                else "application_interest",
                **common,
            )
        context = GlobalConversationContext(
            session_id=f"synthetic-demo-v1-{index:03d}",
            turn_number=1,
            channel="voice" if index % 2 else "text",
            conversation_status=status,
        )
        batch = map_turn_events(
            context,
            assistant,
            result,
            risk,
            previous_assistant=None,
            assistant_initiated=False,
            created_at=epoch + timedelta(minutes=index),
            product_ids=frozenset({"DEP-FLEX", "CARD-DAILY", "LOAN-PERSONAL"}),
            scenario_ids=frozenset({"SC33"}),
        )
        # Rebuild IDs after changing source, maintaining deterministic idempotency.
        for event in batch:
            values = event.model_dump(exclude={"event_id"})
            values["source"] = "synthetic_demo"
            events.append(make_event(**values))
    return events


def anomaly_events(as_of: datetime):
    """Extend the same seed with six hourly baselines and a recent OTP signal spike."""
    start = as_of - timedelta(hours=7)
    events = []
    # One event per baseline window; eighteen events in the current window.
    for index in range(24):
        timestamp = (
            start + timedelta(hours=index)
            if index < 6
            else as_of - timedelta(minutes=10, seconds=index)
        )
        session_id = (
            f"synthetic-anomaly-v1-{as_of.strftime('%Y%m%d%H%M%S')}-{index:02d}"
        )
        for sequence, kind, payload in (
            (
                0,
                "conversation_started",
                {"kind": "conversation_started", "assistant_initiated": False},
            ),
            (
                1,
                "risk_signal",
                {
                    "kind": "risk_signal",
                    "analysis_status": "analyzed",
                    "recommended_action": "security_review",
                },
            ),
        ):
            events.append(
                make_event(
                    created_at=timestamp,
                    session_id=session_id,
                    turn_number=1,
                    sequence=sequence,
                    channel="voice",
                    assistant_id="fraud_security",
                    event_type=kind,
                    conversation_status="awaiting_user",
                    source="synthetic_demo",
                    risk_level="high" if kind == "risk_signal" else None,
                    risk_signals=[RiskSignal.OTP_REQUESTED]
                    if kind == "risk_signal"
                    else [],
                    payload=payload,
                )
            )
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--with-anomaly", action="store_true")
    parser.add_argument(
        "--as-of", help="Timezone-aware ISO timestamp; defaults to current UTC"
    )
    args = parser.parse_args()
    store = SQLiteEventStore(args.db_path or Settings().event_db_path)
    if args.reset:
        print(f"Removed synthetic events: {store.reset_synthetic()}")
    events = synthetic_events()
    if args.with_anomaly:
        as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
        if as_of.tzinfo is None:
            parser.error("--as-of must include a timezone")
        events += anomaly_events(as_of.astimezone(UTC))
    inserted = store.append_many(events)
    summary = store.summary(EventQuery(source="synthetic_demo"))
    print(f"Inserted events: {inserted}")
    print(f"Synthetic conversations: {summary.conversations}")
    for name in (
        "insurance_result",
        "sales_lead",
        "risk_signal",
        "fraud_case",
        "operator_handoff",
    ):
        print(f"{name}: {Counter(summary.event_counts)[name]}")


if __name__ == "__main__":
    main()
