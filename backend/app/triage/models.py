from pydantic import Field

from app.core.contracts import Contract, Language, Slots


class TriageResult(Contract):
    original_text: str
    text: str = Field(min_length=1, max_length=10000)
    language: Language | None = None
    normalized_slots: Slots = Field(default_factory=dict)
    urgency_hints: list[str] = Field(default_factory=list)
    latency_ms: float = Field(ge=0)
