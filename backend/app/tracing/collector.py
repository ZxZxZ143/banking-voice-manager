from collections import OrderedDict, deque

from app.tracing.models import TraceRecord


class TraceCollector:
    """Bounded memory only. A future supervisor API must authorize access by session."""

    def __init__(self, max_sessions: int = 100, max_turns: int = 100) -> None:
        if min(max_sessions, max_turns) < 1:
            raise ValueError("Trace bounds must be positive")
        self._max_sessions = max_sessions
        self._max_turns = max_turns
        self._records: OrderedDict[str, deque[TraceRecord]] = OrderedDict()

    def add(self, session_id: str, record: TraceRecord) -> None:
        records = self._records.setdefault(session_id, deque(maxlen=self._max_turns))
        records.append(record.model_copy(deep=True))
        self._records.move_to_end(session_id)
        while len(self._records) > self._max_sessions:
            self._records.popitem(last=False)

    def get(self, session_id: str) -> list[TraceRecord]:
        return [record.model_copy(deep=True) for record in self._records.get(session_id, [])]

    def delete(self, session_id: str) -> None:
        self._records.pop(session_id, None)
