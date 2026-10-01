from time import perf_counter

from pydantic import Field, SerializeAsAny

from app.conversation.status import ConversationStatus
from app.conversation.store import ConversationStore
from app.core.contracts import Contract
from app.packs.contracts import ConversationContext, GlobalConversationContext, ScenarioResult
from app.packs.lifecycle import ScenarioLifecycle
from app.packs.registry import ScenarioRegistry
from app.tracing.collector import TraceCollector
from app.tracing.models import TraceRecord


class SessionClosedError(Exception):
    pass


class MessageResult(Contract):
    session_id: str
    response_text: str
    routing: SerializeAsAny[Contract]
    state: SerializeAsAny[Contract]
    trace: TraceRecord
    conversation_status: ConversationStatus
    scenario_pack_id: str = Field(exclude=True)
    scenario_result: SerializeAsAny[ScenarioResult] = Field(exclude=True)


class MessageService:
    def __init__(
        self, registry: ScenarioRegistry, dialogs: ConversationStore, traces: TraceCollector
    ) -> None:
        self.registry = registry
        self.dialogs = dialogs
        self.traces = traces
        self.lifecycle = ScenarioLifecycle(registry)

    async def process(
        self, session_id: str, text: str, scenario_mode: str | None = None
    ) -> MessageResult:
        started = perf_counter()
        pack = self.registry.get(scenario_mode)
        async with self.dialogs.session(session_id):
            conversation = self.dialogs.get_conversation(session_id) or ConversationContext(
                global_context=GlobalConversationContext(session_id=session_id)
            )
            global_context = conversation.global_context
            if global_context.conversation_status in ("ended", "handoff"):
                raise SessionClosedError("Session is closed; use a new session_id")
            entry = self.lifecycle.activate(conversation, pack.manifest.id)
            # A pack receives only its own context and a global snapshot. It cannot
            # receive the other contexts, registry, store or application Settings.
            turn = await pack.handle_turn(
                text, global_context.model_copy(deep=True), entry.state.model_copy(deep=True)
            )
            if type(turn.context) is not pack.state_schema:
                raise ValueError("Scenario returned an invalid context schema")
            if type(turn.result) is not pack.output_schema:
                raise ValueError("Scenario returned an invalid result schema")
            entry.state = turn.context.model_copy(deep=True)
            entry.result = turn.result.model_copy(deep=True)
            global_context.turn_number += 1
            global_context.language = turn.language
            global_context.conversation_status = turn.result.status
            if turn.result.status in ("handoff", "ended"):
                self.lifecycle.complete(conversation)
            trace = turn.trace.model_copy(deep=True)
            trace.session_id = session_id
            trace.turn = global_context.turn_number
            trace.turn_number = global_context.turn_number
            trace.conversation_status = global_context.conversation_status
            trace.handoff = global_context.conversation_status == "handoff"
            trace.scenario_pack_id = pack.manifest.id
            trace.interaction_mode = pack.manifest.interaction_mode.value
            trace.context_lifecycle = entry.lifecycle
            trace.scenario_mode = pack.manifest.id
            trace.latency_ms.total = (perf_counter() - started) * 1000
            # No awaits between commits; failed turns leave stored snapshots unchanged.
            self.dialogs.save_conversation(conversation)
            if global_context.turn_number == 1:
                self.traces.delete(session_id)
            self.traces.add(session_id, trace)
            return MessageResult(
                session_id=session_id,
                response_text=turn.response_text,
                routing=turn.routing,
                state=turn.public_state,
                trace=trace,
                conversation_status=turn.result.status,
                scenario_pack_id=pack.manifest.id,
                scenario_result=turn.result,
            )
