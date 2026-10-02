from typing import Literal

from pydantic import Field

from app.conversation.status import ConversationStatus
from app.core.contracts import Contract
from app.risk.models import RiskAssessment
from app.tracing.models import TraceRecord


class PlatformDecision(Contract):
    kind: Literal["pack_switch_confirmation"] = "pack_switch_confirmation"
    response_language: Literal["ru", "kk"]
    target_pack_id: str
    switch_status: Literal["suggested", "declined", "pending"]


class PlatformState(Contract):
    session_id: str
    scenario_mode: str
    response_language: Literal["ru", "kk"]
    turn_number: int


class PlatformMessageResponse(Contract):
    session_id: str
    response_text: str
    routing: PlatformDecision
    state: PlatformState
    trace: TraceRecord
    conversation_status: ConversationStatus
    risk: RiskAssessment | None = Field(default=None, exclude_if=lambda v: v is None)
