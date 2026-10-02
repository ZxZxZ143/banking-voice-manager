from pydantic import Field

from app.conversation.status import ConversationStatus
from app.core.contracts import Contract
from app.packs.fraud_security.models import FraudPublicState
from app.risk.models import RiskAssessment, SecurityDecision
from app.tracing.models import TraceRecord


class FraudMessageResponse(Contract):
    session_id: str
    response_text: str
    routing: SecurityDecision
    state: FraudPublicState
    trace: TraceRecord
    conversation_status: ConversationStatus
    risk: RiskAssessment | None = Field(default=None, exclude_if=lambda v: v is None)
