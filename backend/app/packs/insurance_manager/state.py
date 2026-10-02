from typing import Literal

from pydantic import Field

from app.conversation.status import ConversationStatus
from app.core.contracts import Contract, Language, Slots
from app.packs.contracts import GlobalConversationContext


class DialogTurn(Contract):
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(min_length=1, max_length=10000)


class ConversationState(Contract):
    last_assistant_act: str | None = None
    last_question: str | None = None
    expected_answer_type: str | None = None
    expected_slot: str | None = None
    repair_attempts: int = Field(default=0, ge=0)
    phase: Literal["discover", "collect", "resolve", "confirm", "handoff"] = "discover"
    acknowledged_information: list[str] = Field(default_factory=list, max_length=8)
    travel_duration_days: int | None = Field(default=None, ge=1, le=365)
    last_acknowledgement: str = ""


class DialogueState(Contract):
    session_id: str = Field(min_length=1, max_length=128)
    scenario_mode: str = "insurance_manager"
    language: Language | None = None
    response_language: Literal["ru", "kk"] = "ru"
    client_id: str | None = None
    client_lookup_attempts: list[str] = Field(
        default_factory=list, max_length=2, exclude_if=lambda v: not v
    )
    active_scenario: str | None = None
    scenario_stack: list[str] = Field(default_factory=list)
    pending_scenarios: list[str] = Field(default_factory=list)
    slots: Slots = Field(default_factory=dict)
    scenario_slots: dict[str, Slots] = Field(default_factory=dict)
    awaiting_confirmation: bool = False
    turn_number: int = Field(default=0, ge=0)
    consecutive_low_confidence: int = Field(default=0, ge=0)
    unclear_count: int = Field(default=0, ge=0)
    clarification_options: list[str] = Field(default_factory=list, max_length=2)
    conversation_status: ConversationStatus = "active"
    history: list[DialogTurn] = Field(default_factory=list, max_length=20)
    conversation: ConversationState | None = Field(default=None, exclude_if=lambda v: v is None)


# Keep the foundation's public name compatible with existing integrations.
DialogState = DialogueState


class InsuranceScenarioContext(Contract):
    response_language: Literal["ru", "kk"] = "ru"
    client_id: str | None = None
    client_lookup_attempts: list[str] = Field(
        default_factory=list, max_length=2, exclude_if=lambda v: not v
    )
    active_scenario: str | None = None
    scenario_stack: list[str] = Field(default_factory=list)
    pending_scenarios: list[str] = Field(default_factory=list)
    slots: Slots = Field(default_factory=dict)
    scenario_slots: dict[str, Slots] = Field(default_factory=dict)
    awaiting_confirmation: bool = False
    consecutive_low_confidence: int = Field(default=0, ge=0)
    unclear_count: int = Field(default=0, ge=0)
    clarification_options: list[str] = Field(default_factory=list, max_length=2)
    history: list[DialogTurn] = Field(default_factory=list, max_length=20)
    conversation: ConversationState | None = Field(default_factory=ConversationState)

    def to_dialog(self, global_context: GlobalConversationContext) -> DialogState:
        return DialogState(
            **self.model_dump(),
            session_id=global_context.session_id,
            turn_number=global_context.turn_number,
            language=global_context.language,
            conversation_status=global_context.conversation_status,
        )

    @classmethod
    def from_dialog(cls, state: DialogState) -> "InsuranceScenarioContext":
        data = state.model_dump(include=set(cls.model_fields))
        data["conversation"] = state.conversation
        return cls.model_validate(data)
