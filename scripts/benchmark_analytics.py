"""SQLite measurements on an explicit NEW temporary/demo DB, never a runtime DB."""

import argparse
import json
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from statistics import median
from time import perf_counter

from app.analytics.models import EventQuery, TurnPayload, make_event
from app.analytics.sqlite import SQLiteEventStore
from seed_analytics_demo import synthetic_events


def benchmark(path: Path):
    if path.exists():
        raise FileExistsError("Benchmark requires a new database path")
    store = SQLiteEventStore(path)
    store.initialize()
    store.append_many(synthetic_events())
    writes = []
    for index in range(200):
        event = make_event(
            created_at=datetime.now(UTC),
            session_id=f"benchmark-{index}",
            turn_number=1,
            sequence=0,
            channel="text",
            assistant_id="card_promoter",
            event_type="conversation_turn",
            conversation_status="active",
            payload=TurnPayload(assistant_initiated=False),
        )
        before = perf_counter()
        store.append(event)
        writes.append((perf_counter() - before) * 1000)
    result = {
        "rows": store.get_recent_events().total,
        "append_ms": {
            "p50": median(writes),
            "p95": sorted(writes)[ceil(0.95 * len(writes)) - 1],
        },
    }
    for label, operation in (
        ("summary", lambda: store.summary(EventQuery())),
        (
            "filtered_events",
            lambda: store.query_events(
                EventQuery(event_type="risk_signal", risk_level="high")
            ),
        ),
        ("session_events", lambda: store.get_session_events("synthetic-demo-v1-004")),
    ):
        measurements = []
        for _ in range(50):
            before = perf_counter()
            operation()
            measurements.append((perf_counter() - before) * 1000)
        result[label + "_ms"] = {
            "p50": median(measurements),
            "p95": sorted(measurements)[47],
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, required=True)
    benchmark(parser.parse_args().db_path)
