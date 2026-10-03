from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import JsonValue

PhoneStatus = Literal[
    "active", "transcribing", "processing", "speaking", "handoff", "ended", "cancelled", "error"
]


@dataclass
class PhoneSession:
    call_id: str
    session_id: str
    started_at: datetime
    channel: Literal["voice"] = "voice"
    status: PhoneStatus = "active"
    language: str | None = None
    provider_metadata: dict[str, JsonValue] = field(default_factory=dict)
    conversation_status: str | None = None
    error_code: str | None = None


class ActiveCallRegistry:
    """One event-loop/process. Closed-call tombstones prevent replay reopening a call.

    At the total-call budget, refuse new calls instead of evicting identity mappings.
    """

    def __init__(self, *, max_active: int = 100, max_calls: int = 1000):
        if not 0 < max_active <= max_calls:
            raise ValueError("Call limits must be positive and max_active <= max_calls")
        self.max_active = max_active
        self.max_calls = max_calls
        self._active: dict[str, PhoneSession] = {}
        self._seen: set[str] = set()

    def get(self, call_id: str) -> PhoneSession | None:
        return self._active.get(call_id)

    def start(self, call_id: str, metadata: dict[str, JsonValue]) -> PhoneSession:
        if not isinstance(call_id, str) or not call_id.strip() or len(call_id) > 128:
            raise ValueError("call_id must be a nonblank string of at most 128 characters")
        if existing := self.get(call_id):
            return existing
        if call_id in self._seen:
            raise ValueError("Closed call cannot be reopened")
        if len(self._active) >= self.max_active or len(self._seen) >= self.max_calls:
            raise ValueError("Phone call registry capacity exceeded")
        session = PhoneSession(
            call_id=call_id,
            session_id=str(uuid4()),
            started_at=datetime.now(UTC),
            provider_metadata=deepcopy(metadata),
        )
        self._active[call_id] = session
        self._seen.add(call_id)
        return session

    def remove(self, call_id: str) -> None:
        self._active.pop(call_id, None)
