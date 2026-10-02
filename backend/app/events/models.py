from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.core.channels import Channel
from app.dialog.models import ConversationStatus
from app.events.normalize import instant

EventType = Literal[
    "session.started",
    "transcript.final",
    "agent.response",
    "scenario.selected",
    "clarification.requested",
    "handoff.requested",
    "conversation.ended",
]


class ConversationEvent(BaseModel):
    """JSON-compatible with the frontend event envelope; Agent payloads stay opaque."""

    model_config = ConfigDict(extra="allow", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(min_length=1, max_length=128)
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    event_type: EventType
    channel: Channel
    language: str | None = None
    text: str | None = None
    scenario: JsonValue | None = None
    action: JsonValue | None = None
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    conversation_status: ConversationStatus | None = None
    clarification: bool | str | None = None
    handoff: bool | None = None
    risk: JsonValue | None = None
    routing: JsonValue | None = None
    state: JsonValue | None = None
    trace: JsonValue | None = None
    latency: JsonValue | None = None
    metadata: dict[str, JsonValue] | None = None

    @field_validator("timestamp")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        instant(value)
        return value
