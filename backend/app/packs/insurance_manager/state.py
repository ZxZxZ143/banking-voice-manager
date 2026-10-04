from typing import Literal

from pydantic import Field

from app.conversation.status import ConversationStatus
from app.core.contracts import Contract, Language, Slots
from app.packs.contracts import GlobalConversationContext
from app.packs.insurance_manager.tools.capabilities import ManagerSummary
from app.speech.structured.capture import StructuredCapture

IdentifierKind = Literal["phone", "iin", "policy_number", "claim_number", "vehicle_plate"]
PolicyRelationship = Literal["new", "existing", "not_applicable", "unknown"]


class IdentificationState(Contract):
    """Private, per-scenario lookup memory; values/fingerprints never cross projections."""

    unavailable_fields: list[IdentifierKind] = Field(default_factory=list)
    attempted_fields: list[IdentifierKind] = Field(default_factory=list)
    failed_fields: list[IdentifierKind] = Field(default_factory=list)
    requested_fields: list[IdentifierKind] = Field(default_factory=list)
    successful_field: IdentifierKind | None = None
    exhausted: bool = False
    failed_attempts: list[str] = Field(default_factory=list, repr=False, exclude_if=lambda v: not v)
    provided_values: dict[IdentifierKind, list[str]] = Field(
        default_factory=dict, repr=False, exclude_if=lambda v: not v
    )
    completed_read_only_checks: list[str] = Field(default_factory=list)

    def safe_view(self) -> dict:
        return self.model_dump(exclude={"failed_attempts", "provided_values"})


class DialogTurn(Contract):
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(min_length=1, max_length=10000)


class ConversationState(Contract):
    last_assistant_act: str | None = None
    last_question: str | None = None
    expected_answer_type: str | None = None
    expected_slot: str | None = None
    repair_attempts: int = Field(default=0, ge=0)
    recognition_attempts: dict[str, int] = Field(default_factory=dict, max_length=9)
    structured_capture: StructuredCapture | None = Field(default=None, exclude=True, repr=False)
    phase: Literal["discover", "collect", "resolve", "wrap_up", "confirm", "handoff"] = "discover"
    policy_relationship: PolicyRelationship = "unknown"
    scenario_relationships: dict[str, PolicyRelationship] = Field(
        default_factory=dict, max_length=40
    )
    resume_after_risk: bool = False
    acknowledged_information: list[str] = Field(default_factory=list, max_length=8)
    travel_duration_days: int | None = Field(default=None, ge=1, le=365)
    last_acknowledgement: str = ""


class DialogueState(Contract):
    session_id: str = Field(min_length=1, max_length=128)
    scenario_mode: str = "insurance_manager"
    language: Language | None = None
    response_language: Literal["ru", "kk"] = "ru"
    client_id: str | None = None
    identification: IdentificationState = Field(default_factory=IdentificationState)
    scenario_identification: dict[str, IdentificationState] = Field(default_factory=dict)
    manager_summary: ManagerSummary | None = None
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
    identification: IdentificationState = Field(default_factory=IdentificationState)
    scenario_identification: dict[str, IdentificationState] = Field(default_factory=dict)
    manager_summary: ManagerSummary | None = None
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
        data = self.model_dump()
        data["conversation"] = (
            self.conversation.model_copy(deep=True) if self.conversation else None
        )
        return DialogState(
            **data,
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
