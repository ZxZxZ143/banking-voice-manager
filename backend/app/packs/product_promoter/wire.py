from app.conversation.status import ConversationStatus
from app.core.contracts import Contract
from app.packs.product_promoter.models import ProductDecision, ProductPublicState
from app.tracing.models import TraceRecord


class ProductMessageResponse(Contract):
    session_id: str
    response_text: str
    routing: ProductDecision
    state: ProductPublicState
    trace: TraceRecord
    conversation_status: ConversationStatus
