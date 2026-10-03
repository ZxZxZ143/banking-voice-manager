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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    store = SQLiteEventStore(args.db_path or Settings().event_db_path)
    if args.reset:
        print(f"Removed synthetic events: {store.reset_synthetic()}")
    inserted = store.append_many(synthetic_events())
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
