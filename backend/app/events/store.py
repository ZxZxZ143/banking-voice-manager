from collections import deque
from datetime import datetime
from threading import RLock
from typing import Protocol

from app.core.channels import Channel
from app.events.models import ConversationEvent, EventType
from app.events.normalize import instant, risk_details, scenario_keys


class EventStore(Protocol):
    def append(self, event: ConversationEvent) -> None: ...
    def get_by_session(self, session_id: str) -> list[ConversationEvent]: ...
    def list(
        self,
        *,
        session_id: str | None = None,
        channel: Channel | None = None,
        event_type: EventType | None = None,
        scenario: str | None = None,
        risk_level: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: int | None = None,
    ) -> list[ConversationEvent]: ...
    def update_latency(self, event_id: str, values: dict[str, float]) -> bool: ...


class InMemoryEventStore:
    def __init__(self, max_events: int = 5000):
        if type(max_events) is not int or max_events < 1:
            raise ValueError("max_events must be a positive integer")
        self._lock = RLock()
        self.max_events = max_events
        self.evicted_events = 0
        self._events: deque[ConversationEvent] = deque(maxlen=max_events)

    def append(self, event: ConversationEvent) -> None:
        if len(event.model_dump_json().encode()) > 65536:
            raise ValueError("Event exceeds 64KiB")
        copy = event.model_copy(deep=True)
        with self._lock:
            if len(self._events) == self.max_events:
                self.evicted_events += 1
            self._events.append(copy)

    def update_latency(self, event_id: str, values: dict[str, float]) -> bool:
        with self._lock:
            for index, event in enumerate(self._events):
                if event.id == event_id:
                    previous = event.latency if isinstance(event.latency, dict) else {}
                    self._events[index] = event.model_copy(
                        update={"latency": previous | values}, deep=True
                    )
                    return True
            return False

    def get_by_session(self, session_id: str) -> list[ConversationEvent]:
        return self.list(session_id=session_id)

    def list(
        self,
        *,
        session_id: str | None = None,
        channel: Channel | None = None,
        event_type: EventType | None = None,
        scenario: str | None = None,
        risk_level: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: int | None = None,
    ) -> list[ConversationEvent]:
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("limit must be a nonnegative integer")
        for value in (from_time, to_time):
            if value is not None and value.tzinfo is None:
                raise ValueError("Time filter must include timezone")
        if from_time and to_time and from_time > to_time:
            raise ValueError("Invalid time range")
        with self._lock:
            snapshot = list(self._events)
        matches = [
            e
            for e in snapshot
            if (session_id is None or e.session_id == session_id)
            and (channel is None or e.channel == channel)
            and (event_type is None or e.event_type == event_type)
            and (scenario is None or scenario in scenario_keys(e))
            and (risk_level is None or risk_details(e.risk)[0] == risk_level)
            and (from_time is None or instant(e.timestamp) >= from_time)
            and (to_time is None or instant(e.timestamp) <= to_time)
        ]
        return [e.model_copy(deep=True) for e in matches[:limit]]
