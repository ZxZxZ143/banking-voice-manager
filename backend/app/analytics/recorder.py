import asyncio
import logging
from datetime import UTC, datetime
from threading import Lock

from app.analytics.mapping import map_turn_events
from app.analytics.models import EndedPayload, HandoffPayload, StorageHealth, make_event
from app.analytics.store import EventStore

logger = logging.getLogger(__name__)


class EventRecorder:
    """Best effort post-commit writes. Operational errors never include exception text."""

    def __init__(self, store: EventStore, *, product_ids=frozenset(), scenario_ids=frozenset()):
        self.store = store
        self.product_ids = product_ids
        self.scenario_ids = scenario_ids
        self._lock = Lock()
        self._failures = 0
        self._last_error = None
        self._last_failure = None
        try:
            store.initialize()
        except Exception:
            self.failure("storage_unavailable")

    def failure(self, code):
        with self._lock:
            self._failures += 1
            self._last_error = code
            self._last_failure = datetime.now(UTC)
        logger.error("analytics_storage_failure code=%s", code)

    async def record(self, context, assistant_id, result, risk, **options):
        try:
            events = map_turn_events(
                context,
                assistant_id,
                result,
                risk,
                product_ids=self.product_ids,
                scenario_ids=self.scenario_ids,
                **options,
            )
        except Exception:
            self.failure("event_mapping_failed")
            return
        await self._append(events)

    async def record_end(self, context, assistant_id):
        """Safe, idempotent transport close; no provider IDs, reason text or transcript."""
        try:
            payload = (
                HandoffPayload() if context.conversation_status == "handoff" else EndedPayload()
            )
            event = make_event(
                created_at=datetime.now(UTC),
                session_id=context.session_id,
                turn_number=context.turn_number,
                sequence=8,
                channel=context.channel,
                assistant_id=assistant_id,
                conversation_status=context.conversation_status,
                event_type=payload.kind,
                payload=payload,
            )
        except Exception:
            self.failure("event_mapping_failed")
            return
        await self._append([event])

    async def _append(self, events):
        try:
            # SQLite lock waits/fsync never block the async customer/STT event loop.
            await asyncio.to_thread(self.store.append_many, events)
        except Exception:
            self.failure("storage_unavailable")
            return
        with self._lock:
            self._last_error = None

    def health(self) -> StorageHealth:
        try:
            self.store.probe()
            reachable = True
        except Exception:
            reachable = False
        with self._lock:
            error = self._last_error if reachable else "storage_unavailable"
            return StorageHealth(
                status="degraded" if error else "ok",
                failure_count=self._failures,
                last_error=error,
                last_failure_at=self._last_failure,
            )
