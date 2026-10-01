"""The existing public response schema, projected from the shared turn result."""

from app.conversation.status import ConversationStatus
from app.core.contracts import Contract
from app.packs.insurance_manager.agent.schemas import RouterDecision
from app.packs.insurance_manager.state import DialogState
from app.tracing.models import TraceRecord


class InsuranceMessageResponse(Contract):
    session_id: str
    response_text: str
    routing: RouterDecision
    state: DialogState
    trace: TraceRecord
    conversation_status: ConversationStatus
