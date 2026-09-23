import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.dialog.models import DialogState


class SessionCapacityError(Exception):
    """The bounded in-memory session lock pool is busy."""


@dataclass
class _SessionLease:
    lock: asyncio.Lock
    users: int = 0


class InMemoryDialogStore:
    """Single-process LRU store. In-flight sessions are pinned until their turns finish."""

    def __init__(self, max_sessions: int = 100) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self._max_sessions = max_sessions
        self._states: OrderedDict[str, DialogState] = OrderedDict()
        self._leases: dict[str, _SessionLease] = {}

    @asynccontextmanager
    async def session(self, session_id: str):
        lease = self._leases.get(session_id)
        if lease is None:
            if len(self._leases) >= self._max_sessions:
                raise SessionCapacityError("Too many active sessions; retry later")
            lease = _SessionLease(asyncio.Lock())
            self._leases[session_id] = lease
        lease.users += 1
        try:
            async with lease.lock:
                yield
        finally:
            lease.users -= 1
            if lease.users == 0:
                del self._leases[session_id]

    def get(self, session_id: str) -> DialogState | None:
        state = self._states.get(session_id)
        if state is None:
            return None
        self._states.move_to_end(session_id)
        return state.model_copy(deep=True)

    def save(self, state: DialogState) -> None:
        if state.session_id not in self._states and len(self._states) >= self._max_sessions:
            victim = next((key for key in self._states if key not in self._leases), None)
            if victim is None:
                raise SessionCapacityError("All stored sessions are in use; retry later")
            del self._states[victim]
        self._states[state.session_id] = state.model_copy(deep=True)
        self._states.move_to_end(state.session_id)

    def delete(self, session_id: str) -> None:
        self._states.pop(session_id, None)
