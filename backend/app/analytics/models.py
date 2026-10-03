from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.conversation.status import ConversationStatus
from app.core.contracts import Contract
from app.packs.product_promoter.models import Category, Interest, NextAction
from app.risk.models import CaseType, Guidance, RiskAction, RiskLevel, RiskSignal

AssistantId = Literal[
    "insurance_manager", "product_promoter", "card_promoter", "loan_promoter", "fraud_security"
]
Channel = Literal["text", "voice"]
Source = Literal["runtime", "synthetic_demo"]
ScenarioId = Annotated[str, Field(pattern=r"^(SC\d{2}|SYS_(UNCLEAR|OUT_OF_SCOPE|GOODBYE))$")]
ProductId = Annotated[str, Field(pattern=r"^(DEP|CARD|LOAN)-[A-Z]{1,32}$")]
ActionName = Literal["kb_lookup", "get_offices", "find_client", "get_policy", "get_claim"]


class EventType(StrEnum):
    CONVERSATION_STARTED = "conversation_started"
    CONVERSATION_TURN = "conversation_turn"
    ASSISTANT_SELECTED = "assistant_selected"
    INSURANCE_RESULT = "insurance_result"
    SALES_LEAD = "sales_lead"
    FRAUD_CASE = "fraud_case"
    RISK_SIGNAL = "risk_signal"
    OPERATOR_HANDOFF = "operator_handoff"
    CONVERSATION_ENDED = "conversation_ended"


class StartedPayload(Contract):
    kind: Literal["conversation_started"] = "conversation_started"
    assistant_initiated: bool


class TurnPayload(Contract):
    kind: Literal["conversation_turn"] = "conversation_turn"
    assistant_initiated: bool


class SelectedPayload(Contract):
    kind: Literal["assistant_selected"] = "assistant_selected"
    previous_assistant_id: AssistantId | None = None


class InsurancePayload(Contract):
    kind: Literal["insurance_result"] = "insurance_result"
    completed: bool
    handoff: bool
    actions: list[ActionName] = Field(default_factory=list, max_length=5)


class SalesPayload(Contract):
    kind: Literal["sales_lead"] = "sales_lead"
    campaign: Category
    product_category: Category | None = None
    selected_product_id: ProductId | None = None
    presented_product_ids: list[ProductId] = Field(default_factory=list, max_length=9)
    outcome: Literal["consulting", "interested", "declined", "handoff", "ended"]
    interest_level: Interest
    next_action: NextAction
    completed: bool
    handoff: bool


class FraudPayload(Contract):
    kind: Literal["fraud_case"] = "fraud_case"
    case_type: CaseType
    case_status: Literal["open", "informed", "needs_review"]
    facts: list[RiskSignal] = Field(default_factory=list, max_length=15)
    recommended_action: RiskAction
    guidance_shown: list[Guidance] = Field(default_factory=list, max_length=11)
    completed: bool
    handoff: bool


class RiskPayload(Contract):
    kind: Literal["risk_signal"] = "risk_signal"
    analysis_status: Literal["analyzed", "unavailable", "invalid_output"]
    recommended_action: RiskAction
    guidance_shown: list[Guidance] = Field(default_factory=list, max_length=11)


class HandoffPayload(Contract):
    kind: Literal["operator_handoff"] = "operator_handoff"


class EndedPayload(Contract):
    kind: Literal["conversation_ended"] = "conversation_ended"


EventPayload = Annotated[
    StartedPayload
    | TurnPayload
    | SelectedPayload
    | InsurancePayload
    | SalesPayload
    | FraudPayload
    | RiskPayload
    | HandoffPayload
    | EndedPayload,
    Field(discriminator="kind"),
]


class ConversationEvent(Contract):
    event_id: UUID
    schema_version: Literal[1] = 1
    created_at: AwareDatetime
    session_id: str = Field(min_length=1, max_length=128)
    turn_number: int = Field(ge=1)
    sequence: int = Field(ge=0, le=8)
    channel: Channel
    assistant_id: AssistantId
    event_type: EventType
    conversation_status: ConversationStatus
    scenario_id: ScenarioId | None = None
    risk_level: RiskLevel | None = None
    risk_signals: list[RiskSignal] = Field(default_factory=list, max_length=15)
    result_status: ConversationStatus | None = None
    source: Source = "runtime"
    payload: EventPayload

    @field_validator("created_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def matching_payload(self):
        if self.payload.kind != self.event_type:
            raise ValueError("Event type and payload kind must match")
        return self

    @property
    def idempotency_key(self) -> str:
        # Terminal/start events are unique across the whole session. Results are
        # snapshots per committed turn, never counts of distinct customers/cases.
        turn = (
            0
            if self.event_type
            in {
                EventType.CONVERSATION_STARTED,
                EventType.OPERATOR_HANDOFF,
                EventType.CONVERSATION_ENDED,
            }
            else self.turn_number
        )
        return sha256(
            f"{self.source}\0{self.session_id}\0{turn}\0{self.event_type}".encode()
        ).hexdigest()


def make_event(**values) -> ConversationEvent:
    event = ConversationEvent(event_id=UUID(int=0), **values)
    event.event_id = uuid5(NAMESPACE_URL, "veyra:event:" + event.idempotency_key)
    return event


class EventQuery(Contract):
    from_time: AwareDatetime | None = None
    to_time: AwareDatetime | None = None
    assistant_id: AssistantId | None = None
    event_type: EventType | None = None
    risk_level: RiskLevel | None = None
    channel: Channel | None = None
    source: Source | None = None
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=1000000)

    @model_validator(mode="after")
    def time_order(self):
        if self.from_time and self.to_time and self.from_time >= self.to_time:
            raise ValueError("from must be before to")
        return self


class EventPage(Contract):
    events: list[ConversationEvent]
    total: int
    limit: int
    offset: int
    next_offset: int | None


class SessionEvents(EventPage):
    session_id: str
    channel: Channel | None


class Period(Contract):
    from_time: AwareDatetime | None = Field(serialization_alias="from")
    to_time: AwareDatetime | None = Field(serialization_alias="to")


class RiskCounts(Contract):
    total: int = 0
    high: int = 0
    critical: int = 0
    levels: dict[RiskLevel, int] = Field(default_factory=dict)
    signals: dict[RiskSignal, int] = Field(default_factory=dict)


class SalesCounts(Contract):
    leads: int = 0
    interested: int = 0
    declined: int = 0
    outcomes: dict[Literal["consulting", "interested", "declined", "handoff", "ended"], int] = (
        Field(default_factory=dict)
    )


class AnalyticsSummary(Contract):
    period: Period
    conversations: int
    handoffs: int
    event_counts: dict[EventType, int]
    results_by_assistant: dict[AssistantId, int]
    risk: RiskCounts
    sales: SalesCounts
    fraud_cases: int
    fraud_case_types: dict[CaseType, int]


class StorageHealth(Contract):
    status: Literal["ok", "degraded"]
    backend: Literal["sqlite"] = "sqlite"
    failure_count: int = 0
    last_error: Literal["storage_unavailable", "event_mapping_failed"] | None = None
    last_failure_at: AwareDatetime | None = None
