from typing import Annotated

from pydantic import Field

from app.agent.schemas import ScenarioScore, ScenarioSelection
from app.core.contracts import Contract, Language, Slots

Milliseconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class LatencyRecord(Contract):
    """Null means unmeasured/unavailable, not zero milliseconds."""

    stt: Milliseconds | None = None
    triage: Milliseconds | None = None
    router: Milliseconds | None = None
    tools: Milliseconds | None = None
    response: Milliseconds | None = None
    tts_first_audio: Milliseconds | None = None
    total: Milliseconds | None = None


class TraceRecord(Contract):
    turn: int = Field(ge=1)
    transcript: str
    language: Language | None = None
    scenarios: list[ScenarioSelection] = Field(default_factory=list)
    alternatives: list[ScenarioScore] = Field(default_factory=list)
    reason: str = Field(default="", max_length=500)
    slots: Slots = Field(default_factory=dict)
    actions: list[str] = Field(default_factory=list)
    latency_ms: LatencyRecord = Field(default_factory=LatencyRecord)
