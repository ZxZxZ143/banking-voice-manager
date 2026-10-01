from typing import Annotated

from pydantic import Field

from app.conversation.status import ConversationStatus
from app.core.contracts import Contract, Language, Slots
from app.tracing.selections import ScenarioScore, ScenarioSelection

Milliseconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class LatencyRecord(Contract):
    """Null means unmeasured/unavailable, not zero milliseconds."""

    stt: Milliseconds | None = None
    triage: Milliseconds | None = None
    router: Milliseconds | None = None
    policy: Milliseconds | None = None
    tools: Milliseconds | None = None
    response: Milliseconds | None = None
    tts_first_audio: Milliseconds | None = None
    total: Milliseconds | None = None


class TraceRecord(Contract):
    session_id: str | None = None
    turn: int = Field(ge=1)
    turn_number: int | None = Field(default=None, ge=1)
    transcript: str
    language: Language | None = None
    scenarios: list[ScenarioSelection] = Field(default_factory=list)
    alternatives: list[ScenarioScore] = Field(default_factory=list)
    reason: str = Field(default="", max_length=500)
    routing_error: str | None = None
    slots: Slots = Field(default_factory=dict)
    actions: list[str] = Field(default_factory=list)
    source_keys: list[str] = Field(default_factory=list)
    policy_outcome: str | None = None
    completed_scenario: str | None = None
    clarification: bool = False
    active_scenario: str | None = None
    pending_scenarios: list[str] = Field(default_factory=list)
    scenario_stack: list[str] = Field(default_factory=list)
    scenario_mode: str | None = None
    scenario_pack_id: str | None = None
    interaction_mode: str | None = None
    context_lifecycle: str | None = None
    conversation_status: ConversationStatus = "active"
    handoff: bool = False
    latency_ms: LatencyRecord = Field(default_factory=LatencyRecord)
