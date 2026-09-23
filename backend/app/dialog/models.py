from typing import Literal

from pydantic import Field

from app.core.contracts import Contract, Language, Slots


class DialogTurn(Contract):
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(min_length=1, max_length=10000)


ConversationStatus = Literal["active", "awaiting_user", "awaiting_confirmation", "handoff", "ended"]


class DialogueState(Contract):
    session_id: str = Field(min_length=1, max_length=128)
    language: Language | None = None
    response_language: Literal["ru", "kk"] = "ru"
    client_id: str | None = None
    active_scenario: str | None = None
    scenario_stack: list[str] = Field(default_factory=list)
    pending_scenarios: list[str] = Field(default_factory=list)
    slots: Slots = Field(default_factory=dict)
    awaiting_confirmation: bool = False
    turn_number: int = Field(default=0, ge=0)
    consecutive_low_confidence: int = Field(default=0, ge=0)
    unclear_count: int = Field(default=0, ge=0)
    clarification_options: list[str] = Field(default_factory=list, max_length=2)
    conversation_status: ConversationStatus = "active"
    history: list[DialogTurn] = Field(default_factory=list, max_length=20)


# Keep the foundation's public name compatible with existing integrations.
DialogState = DialogueState
