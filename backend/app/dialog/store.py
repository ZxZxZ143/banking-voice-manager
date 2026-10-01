"""Legacy flat-state adapter; actual storage holds separated conversation contexts."""

from app.conversation.store import ConversationStore
from app.conversation.store import SessionCapacityError as SessionCapacityError
from app.packs.contracts import ConversationContext, GlobalConversationContext, ScenarioContextEntry
from app.packs.insurance_manager.pack import INSURANCE_MANIFEST
from app.packs.insurance_manager.state import DialogState, InsuranceScenarioContext


class InMemoryDialogStore(ConversationStore):
    def get(self, session_id: str) -> DialogState | None:
        conversation = self.get_conversation(session_id)
        if conversation is None:
            return None
        entry = conversation.scenario_contexts.get(INSURANCE_MANIFEST.id)
        if entry is None or type(entry.state) is not InsuranceScenarioContext:
            return None
        return entry.state.to_dialog(conversation.global_context)

    def save(self, state: DialogState) -> None:
        if state.scenario_mode != INSURANCE_MANIFEST.id:
            raise ValueError("The legacy state adapter supports only Insurance Manager")
        conversation = self.get_conversation(state.session_id) or ConversationContext(
            global_context=GlobalConversationContext(session_id=state.session_id)
        )
        conversation.global_context.turn_number = state.turn_number
        conversation.global_context.language = state.language
        conversation.global_context.conversation_status = state.conversation_status
        conversation.active_scenario_pack = INSURANCE_MANIFEST.id
        conversation.scenario_contexts[INSURANCE_MANIFEST.id] = ScenarioContextEntry(
            state=InsuranceScenarioContext.from_dialog(state),
            lifecycle="completed"
            if state.conversation_status in ("handoff", "ended")
            else "active",
        )
        self.save_conversation(conversation)
