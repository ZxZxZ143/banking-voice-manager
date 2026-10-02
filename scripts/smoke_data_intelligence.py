"""Offline DEMO-only analytics smoke; no app/network/customer configuration."""

import json
from datetime import UTC, datetime

from app.analytics.demo import seed_demo
from app.analytics.service import AnalyticsService
from app.core.config import Settings
from app.events.store import InMemoryEventStore


def main() -> None:
    now = datetime(2026, 10, 2, 12, tzinfo=UTC)
    store = InMemoryEventStore()
    count = seed_demo(store, now)
    analytics = AnalyticsService(store, Settings(_env_file=None))
    overview = analytics.overview()
    journey = analytics.get_journey("DEMO-journey")
    anomalies = analytics.anomalies(now=now)
    scenario = next(a for a in anomalies if a.metric == "scenario")
    assert overview.total_sessions == 38
    assert overview.risk.high_risk_sessions == 12
    assert scenario.baseline_expected_count == 4 and scenario.current_count == 12
    assert [stage.scenario for stage in journey[:3]] == [
        "LOGIN_PROBLEM",
        "SUSPICIOUS_TRANSACTION",
        "CARD_BLOCK",
    ]
    print(
        json.dumps(
            {
                "mode": "DEMO — synthetic data, no real calls or risk analysis",
                "retained_events": count,
                "sessions": overview.total_sessions,
                "high_risk_sessions": overview.risk.high_risk_sessions,
                "journey_stages": len(journey),
                "anomalies": [a.model_dump(mode="json") for a in anomalies],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
