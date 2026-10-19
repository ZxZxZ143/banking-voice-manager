"""Versioned synthetic fixtures and bounded, request-driven rolling replay."""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
from threading import Lock

from pydantic import AwareDatetime, Field

from app.analytics.models import ConversationEvent, make_event
from app.analytics.store import EventStore
from app.core.contracts import Contract

logger = logging.getLogger(__name__)
REFRESH_SECONDS = 300


class DemoFixture(Contract):
    dataset_id: str = Field(pattern=r"^veyra-dashboard-demo$")
    version: str = Field(pattern=r"^[0-9]+$")
    reference_as_of: AwareDatetime
    core: list[ConversationEvent]
    anomalies: list[ConversationEvent]


@dataclass(frozen=True)
class DemoDataset:
    fixture: DemoFixture
    fingerprint: str

    def events_at(self, anchor: datetime, *, with_anomaly: bool = True):
        delta = anchor - self.fixture.reference_as_of
        events = self.fixture.core + (self.fixture.anomalies if with_anomaly else [])
        return [
            event.model_copy(deep=True, update={"created_at": event.created_at + delta})
            for event in events
        ]


@lru_cache(maxsize=1)
def load_demo_dataset() -> DemoDataset:
    raw = files("app.analytics").joinpath("fixtures/demo-v1.json").read_bytes()
    fixture = DemoFixture.model_validate_json(raw)
    events = fixture.core + fixture.anomalies
    if not events or len({e.idempotency_key for e in events}) != len(events):
        raise ValueError("Invalid demo dataset identities")
    for event in events:
        if (
            event.source != "synthetic_demo"
            or event.event_type == "performance_sample"
            or not event.session_id.startswith(("synthetic-demo-v1-", "synthetic-anomaly-v1-"))
            or event.event_id != make_event(**event.model_dump(exclude={"event_id"})).event_id
        ):
            raise ValueError("Invalid demo dataset event")
    return DemoDataset(fixture, sha256(raw).hexdigest())


def synthetic_events():
    """Compatibility for local development; dates remain the canonical October snapshot."""
    return [event.model_copy(deep=True) for event in load_demo_dataset().fixture.core]


def anomaly_events(as_of: datetime):
    """Stable session identities, including when the development CLI changes its clock."""
    dataset = load_demo_dataset()
    delta = as_of - dataset.fixture.reference_as_of
    return [
        event.model_copy(deep=True, update={"created_at": event.created_at + delta})
        for event in dataset.fixture.anomalies
    ]


def utc_now():
    return datetime.now(UTC)


class DemoDataLoader:
    def __init__(self, store: EventStore, *, dataset: DemoDataset | None = None, clock=None):
        self.store = store
        try:
            self.dataset = dataset or load_demo_dataset()
        except Exception:
            logger.error("analytics_demo_fixture_invalid")
            raise RuntimeError("analytics_demo_fixture_invalid") from None
        self.clock = clock or utc_now
        self._anchor: datetime | None = None
        self._lock = Lock()

    def ensure_current(self) -> bool:
        """Startup and analytics reads only. Same five-minute bucket does no database work."""
        try:
            with self._lock:
                now = self.clock()
                anchor = datetime.fromtimestamp(
                    int(now.timestamp()) // REFRESH_SECONDS * REFRESH_SECONDS, UTC
                )
                if self._anchor == anchor:
                    return False
                fixture = self.dataset.fixture
                changed = self.store.install_demo_dataset(
                    fixture.dataset_id,
                    fixture.version,
                    self.dataset.fingerprint,
                    anchor,
                    self.dataset.events_at(anchor),
                )
                self._anchor = anchor
                logger.info(
                    "analytics_demo_ready dataset=%s version=%s events=%s changed=%s",
                    fixture.dataset_id,
                    fixture.version,
                    len(fixture.core) + len(fixture.anomalies),
                    changed,
                )
                return changed
        except Exception:
            logger.error("analytics_demo_load_failed")
            raise RuntimeError("analytics_demo_load_failed") from None


def seed_cli():
    """Optional local command. The running backend never imports scripts/."""
    import argparse
    from pathlib import Path

    from app.analytics.models import EventQuery
    from app.analytics.sqlite import SQLiteEventStore
    from app.core.config import Settings

    parser = argparse.ArgumentParser(description="Atomically install the versioned synthetic demo")
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--reset", action="store_true", help="Repair only this owned dataset")
    parser.add_argument("--with-anomaly", action="store_true")
    parser.add_argument("--as-of", help="Aware ISO timestamp; default is the canonical snapshot")
    args = parser.parse_args()
    dataset = load_demo_dataset()
    anchor = datetime.fromisoformat(args.as_of) if args.as_of else dataset.fixture.reference_as_of
    if anchor.tzinfo is None:
        parser.error("--as-of must include a timezone")
    store = SQLiteEventStore(args.db_path or Settings().event_db_path)
    changed = store.install_demo_dataset(
        dataset.fixture.dataset_id,
        dataset.fixture.version,
        dataset.fingerprint + (":anomalies" if args.with_anomaly else ":core"),
        anchor,
        dataset.events_at(anchor, with_anomaly=args.with_anomaly),
    )
    summary = store.summary(EventQuery(source="synthetic_demo"))
    print(
        json.dumps(
            {
                "changed": changed,
                "synthetic_conversations": summary.conversations,
                "event_counts": summary.event_counts,
            }
        )
    )
