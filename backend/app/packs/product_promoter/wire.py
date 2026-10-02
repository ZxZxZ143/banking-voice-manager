from pydantic import Field

from app.conversation.status import ConversationStatus
from app.core.contracts import Contract
from app.packs.product_promoter.models import ProductDecision, ProductPublicState
from app.risk.models import RiskAssessment
from app.tracing.models import TraceRecord


class ProductMessageResponse(Contract):
    session_id: str
    response_text: str
    routing: ProductDecision
    state: ProductPublicState
    trace: TraceRecord
    conversation_status: ConversationStatus
    risk: RiskAssessment | None = Field(default=None, exclude_if=lambda v: v is None)
