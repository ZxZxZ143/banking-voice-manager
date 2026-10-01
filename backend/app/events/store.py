from collections import deque
from typing import Protocol

from app.core.channels import Channel
from app.events.models import ConversationEvent, EventType


class EventStore(Protocol):
    def append(self, event: ConversationEvent) -> None: ...

    def get_by_session(self, session_id: str) -> list[ConversationEvent]: ...

    def list(
        self,
        *,
        session_id: str | None = None,
        channel: Channel | None = None,
        event_type: EventType | None = None,
        limit: int | None = None,
    ) -> list[ConversationEvent]: ...


class InMemoryEventStore:
    def __init__(self, max_events: int = 5000):
        if type(max_events) is not int or max_events < 1:
            raise ValueError("max_events must be a positive integer")
        self._events: deque[ConversationEvent] = deque(maxlen=max_events)

    def append(self, event: ConversationEvent) -> None:
        self._events.append(event.model_copy(deep=True))

    def get_by_session(self, session_id: str) -> list[ConversationEvent]:
        return self.list(session_id=session_id)

    def list(
        self,
        *,
        session_id: str | None = None,
        channel: Channel | None = None,
        event_type: EventType | None = None,
        limit: int | None = None,
    ) -> list[ConversationEvent]:
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("limit must be a nonnegative integer")
        matches = [
            event
            for event in self._events
            if (session_id is None or event.session_id == session_id)
            and (channel is None or event.channel == channel)
            and (event_type is None or event.event_type == event_type)
        ]
        return [event.model_copy(deep=True) for event in matches[:limit]]
