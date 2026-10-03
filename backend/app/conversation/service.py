from time import perf_counter

from pydantic import Field, SerializeAsAny

from app.analytics.recorder import EventRecorder
from app.conversation.status import ConversationStatus
from app.conversation.store import ConversationStore
from app.core.contracts import Contract
from app.packs.contracts import (
    ConversationContext,
    GlobalConversationContext,
    ScenarioResult,
)
from app.packs.lifecycle import ScenarioLifecycle
from app.packs.registry import ScenarioRegistry
from app.risk.guard import guidance_turn
from app.risk.models import RiskAssessment, RiskContext
from app.risk.privacy import redact_authentication
from app.risk.service import RiskIntelligence, RiskRun
from app.speech.structured.context import context_for_slot
from app.speech.structured.recognition import RecognitionReceipts
from app.tracing.collector import TraceCollector
from app.tracing.models import PackSwitch, TraceRecord


class SessionClosedError(Exception):
    pass


class ScenarioOpeningError(Exception):
    pass


class SpeechReceiptError(Exception):
    pass


class MessageResult(Contract):
    session_id: str
    response_text: str
    routing: SerializeAsAny[Contract]
    state: SerializeAsAny[Contract]
    trace: TraceRecord
    conversation_status: ConversationStatus
    risk: RiskAssessment | None = Field(default=None, exclude_if=lambda v: v is None)
    scenario_pack_id: str = Field(exclude=True)
    scenario_result: SerializeAsAny[ScenarioResult] = Field(exclude=True)


class MessageService:
    def __init__(
        self,
        registry: ScenarioRegistry,
        dialogs: ConversationStore,
        traces: TraceCollector,
        risk: RiskIntelligence | None = None,
        events: EventRecorder | None = None,
    ) -> None:
        self.registry = registry
        self.dialogs = dialogs
        self.traces = traces
        self.lifecycle = ScenarioLifecycle(registry)
        self.selector = None
        self.risk = risk
        self.events = events
        self.recognitions = RecognitionReceipts()

    def transcription_snapshot(self, session_id):
        conversation = self.dialogs.get_conversation(session_id)
        if (
            conversation
            and conversation.active_scenario_pack == "insurance_manager"
            and conversation.global_context.conversation_status not in {"ended", "handoff"}
        ):
            entry = conversation.scenario_contexts.get("insurance_manager")
            meta = getattr(entry.state, "conversation", None) if entry else None
            slot = meta.expected_slot if meta else None
            language = getattr(entry.state, "response_language", None) if entry else None
            return context_for_slot(slot, language), conversation.global_context.turn_number, slot
        return context_for_slot(None), 0, None

    def record_recognition(self, session_id, turn, slot, text, outcome):
        return self.recognitions.put(session_id, turn, slot, text, outcome)

    async def end_session(self, session_id: str) -> None:
        """Close a transport session without inventing another customer/Agent turn."""
        async with self.dialogs.session(session_id):
            conversation = self.dialogs.get_conversation(session_id)
            if conversation is None or not conversation.global_context.turn_number:
                return  # No committed conversation to project into analytics.
            context = conversation.global_context
            if context.conversation_status not in ("ended", "handoff"):
                context.conversation_status = "ended"
                self.lifecycle.complete(conversation)
                self.dialogs.save_conversation(conversation)
            if self.events:
                await self.events.record_end(context, conversation.active_scenario_pack)

    async def process(
        self,
        session_id: str,
        text: str,
        scenario_mode: str | None = None,
        *,
        start_scenario: bool = False,
        channel: str = "text",
        recognition_id: str | None = None,
    ) -> MessageResult:
        started = perf_counter()
        if scenario_mode is not None:
            self.registry.get(scenario_mode)  # Validate before acquiring/mutating a session.
        async with self.dialogs.session(session_id):
            conversation = self.dialogs.get_conversation(session_id) or ConversationContext(
                global_context=GlobalConversationContext(session_id=session_id)
            )
            global_context = conversation.global_context
            if global_context.conversation_status in ("ended", "handoff"):
                raise SessionClosedError("Session is closed; use a new session_id")
            previous_pack = conversation.active_scenario_pack
            pack = self.registry.get(scenario_mode or previous_pack)
            speech_answer = None
            if recognition_id:
                _, expected_turn, expected_slot = self.transcription_snapshot(session_id)
                if channel != "voice" or pack.manifest.id != "insurance_manager":
                    raise SpeechReceiptError()
                speech_answer = self.recognitions.take(
                    recognition_id, session_id, expected_turn, expected_slot, text
                )
                if speech_answer is None:
                    raise SpeechReceiptError()
            switch_source = "explicit"
            routed_text = redact_authentication(text)[:10000]
            global_context.channel = channel
            # Assistant changes require explicit API/UI selection. Never forward a turn.
            conversation.pending_switch = None
            entry = self.lifecycle.activate(conversation, pack.manifest.id, preserve_completed=True)
            global_context.speech_answer = speech_answer
            own_risk_context = getattr(entry.state, "risk_context", None)
            if own_risk_context:
                routed_text = redact_authentication(
                    routed_text, own_risk_context().pending_question
                )[:10000]
            run = RiskRun(None, None, 0)
            assessed_handler = getattr(pack, "handle_assessed_turn", None)
            if self.risk and not start_scenario:
                risk_context = (
                    entry.state.risk_context() if assessed_handler else conversation.risk_context
                )
                run = await self.risk.analyze(
                    routed_text,
                    active_assistant=pack.manifest.id,
                    language=global_context.language,
                    channel=global_context.channel,
                    context=risk_context,
                    force=bool(assessed_handler),
                )
            # A pack receives only its own context and a global snapshot. It cannot
            # receive the other contexts, registry, store or application Settings.
            if start_scenario:
                opener = getattr(pack, "open_turn", None)
                if opener is None:
                    raise ScenarioOpeningError("This scenario does not initiate a conversation")
                turn = await opener(
                    global_context.model_copy(deep=True), entry.state.model_copy(deep=True)
                )
            elif assessed_handler and self.risk:
                turn = await assessed_handler(
                    routed_text,
                    global_context.model_copy(deep=True),
                    entry.state.model_copy(deep=True),
                    run,
                )
            elif run.assessment and run.assessment.guidance_shown:
                turn = await guidance_turn(
                    pack, global_context, entry, run, routed_text, self.risk.policy
                )
            else:
                turn = await pack.handle_turn(
                    routed_text,
                    global_context.model_copy(deep=True),
                    entry.state.model_copy(deep=True),
                )
            if type(turn.context) is not pack.state_schema:
                raise ValueError("Scenario returned an invalid context schema")
            if type(turn.result) is not pack.output_schema:
                raise ValueError("Scenario returned an invalid result schema")
            entry.state = turn.context.model_copy(deep=True)
            global_context.speech_answer = None
            entry.result = turn.result.model_copy(deep=True)
            entry.public_state = turn.public_state.model_copy(deep=True)
            if self.risk:
                if assessed_handler:
                    conversation.risk_context = turn.context.risk_context()
                else:
                    # Business replies cannot inherit a pending specialist question.
                    conversation.risk_context = RiskContext(
                        previous_signals=run.assessment.signals
                        if run.assessment and run.assessment.risk_relevant
                        else [],
                        response_language=getattr(turn.routing, "response_language", "ru"),
                    )
            if (
                entry.lifecycle == "completed"
                and not turn.complete_pack
                and getattr(turn.routing, "kind", None) != "security_guidance"
            ):
                entry.lifecycle = "active"
            global_context.turn_number += 1
            global_context.language = turn.language
            global_context.conversation_status = turn.result.status
            if turn.complete_pack or turn.result.status in ("handoff", "ended"):
                self.lifecycle.complete(conversation)
            trace = turn.trace.model_copy(deep=True)
            if speech_answer:
                trace.recognition = speech_answer.metadata
            trace.session_id = session_id
            trace.turn = global_context.turn_number
            trace.turn_number = global_context.turn_number
            trace.conversation_status = global_context.conversation_status
            trace.handoff = global_context.conversation_status == "handoff"
            trace.scenario_pack_id = pack.manifest.id
            trace.interaction_mode = pack.manifest.interaction_mode.value
            trace.context_lifecycle = entry.lifecycle
            trace.scenario_mode = pack.manifest.id
            trace.transcript = routed_text
            trace.risk = run.assessment
            if self.risk and not start_scenario:
                trace.latency_ms.risk_precheck = run.precheck_ms
                trace.latency_ms.risk_agent = run.agent_ms
            redact_trace = getattr(pack, "redact_trace", None)
            if redact_trace:
                redact_trace(trace)
            if previous_pack is not None and previous_pack != pack.manifest.id:
                trace.pack_switch = PackSwitch(
                    from_pack=previous_pack,
                    to_pack=pack.manifest.id,
                    source=switch_source,
                    status="switched",
                )
            trace.latency_ms.total = (perf_counter() - started) * 1000
            # No awaits between commits; failed turns leave stored snapshots unchanged.
            self.dialogs.save_conversation(conversation)
            if global_context.turn_number == 1:
                self.traces.delete(session_id)
            self.traces.add(session_id, trace)
            if self.events:
                await self.events.record(
                    global_context,
                    pack.manifest.id,
                    turn.result,
                    run.assessment,
                    previous_assistant=previous_pack,
                    assistant_initiated=start_scenario,
                    emit_result=(
                        getattr(turn.routing, "kind", None) != "security_guidance"
                        or turn.result.status in ("handoff", "ended")
                    ),
                )
            return MessageResult(
                session_id=session_id,
                response_text=turn.response_text,
                routing=turn.routing,
                state=turn.public_state,
                trace=trace,
                conversation_status=turn.result.status,
                risk=run.assessment,
                scenario_pack_id=pack.manifest.id,
                scenario_result=turn.result,
            )
