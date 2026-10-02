import asyncio
import re
from time import perf_counter

from pydantic import Field, SerializeAsAny

from app.agent.errors import RouterOutputError, RouterProviderError
from app.conversation.status import ConversationStatus
from app.conversation.store import ConversationStore
from app.conversation.wire import PlatformDecision, PlatformState
from app.core.contracts import Contract
from app.packs.contracts import (
    ConversationContext,
    GlobalConversationContext,
    PendingPackSwitch,
    ScenarioResult,
)
from app.packs.lifecycle import ScenarioLifecycle
from app.packs.registry import ScenarioRegistry
from app.tracing.collector import TraceCollector
from app.tracing.models import PackSwitch, TraceRecord


class SessionClosedError(Exception):
    pass


class ScenarioOpeningError(Exception):
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
        self.selector = None

    async def process(
        self,
        session_id: str,
        text: str,
        scenario_mode: str | None = None,
        *,
        start_scenario: bool = False,
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
            switch_source = "explicit"
            routed_text = text
            pending = conversation.pending_switch
            if pending and (scenario_mode is None or scenario_mode == previous_pack):
                answer = _confirmation(text)
                if answer is False:
                    conversation.pending_switch = None
                    global_context.conversation_status = pending.previous_status
                    return self._platform_turn(conversation, text, pending, "declined", started)
                if answer is True:
                    pack = self.registry.get(pending.to_pack)
                    routed_text = pending.request_text
                    switch_source = "confirmed"
                global_context.conversation_status = pending.previous_status
            conversation.pending_switch = None
            entry = self.lifecycle.activate(conversation, pack.manifest.id, preserve_completed=True)
            # A pack receives only its own context and a global snapshot. It cannot
            # receive the other contexts, registry, store or application Settings.
            if start_scenario:
                opener = getattr(pack, "open_turn", None)
                if opener is None:
                    raise ScenarioOpeningError("This scenario does not initiate a conversation")
                turn = await opener(
                    global_context.model_copy(deep=True), entry.state.model_copy(deep=True)
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
            if turn.out_of_domain and self.selector is not None:
                try:
                    # Conditional selection shares a deadline below the browser's 60s timeout.
                    async with asyncio.timeout(max(0.001, 55 - (perf_counter() - started))):
                        selection = await self.selector.select(
                            text,
                            pack.manifest.id,
                            [
                                {
                                    "id": p.manifest.id,
                                    "name": p.manifest.name,
                                    "description": p.manifest.public_description,
                                }
                                for p in self.registry.list()
                            ],
                            global_context.language,
                        )
                except RouterOutputError:
                    selection = None
                except TimeoutError as exc:
                    raise RouterProviderError(timeout=True) from exc
                if (
                    selection
                    and selection.target_pack_id
                    and selection.confidence >= 0.75
                    and selection.target_pack_id != pack.manifest.id
                ):
                    self.registry.get(selection.target_pack_id)
                    pending = PendingPackSwitch(
                        from_pack=pack.manifest.id,
                        to_pack=selection.target_pack_id,
                        request_text=text,
                        response_language=selection.response_language,
                        previous_status=global_context.conversation_status,
                    )
                    conversation.pending_switch = pending
                    global_context.conversation_status = "awaiting_confirmation"
                    return self._platform_turn(conversation, text, pending, "suggested", started)
            entry.state = turn.context.model_copy(deep=True)
            entry.result = turn.result.model_copy(deep=True)
            if entry.lifecycle == "completed" and not turn.complete_pack:
                entry.lifecycle = "active"
            global_context.turn_number += 1
            global_context.language = turn.language
            global_context.conversation_status = turn.result.status
            if turn.complete_pack or turn.result.status in ("handoff", "ended"):
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
            trace.transcript = text
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

    def _platform_turn(self, conversation, text, pending, switch_status, started):
        global_context = conversation.global_context
        global_context.turn_number += 1
        global_context.language = pending.response_language
        current = self.registry.get(conversation.active_scenario_pack)
        entry = conversation.scenario_contexts[current.manifest.id]
        name = self.registry.get(pending.to_pack).manifest.name
        if switch_status == "declined":
            response = (
                "Хорошо, остаёмся в текущем сценарии. Продолжим с вашего вопроса."
                if pending.response_language == "ru"
                else "Жақсы, қазіргі сценарийде қаламыз. Сұрағыңызды жалғастырайық."
            )
        else:
            response = (
                f"Этот вопрос относится к {name}. Переключить сценарий и передать ваш вопрос?"
                if pending.response_language == "ru"
                else f"Бұл сұрақ {name} бағытына жатады. "
                "Сценарийді ауыстырып, сұрағыңызды жіберейін бе?"
            )
        trace = TraceRecord(
            session_id=global_context.session_id,
            turn=global_context.turn_number,
            turn_number=global_context.turn_number,
            transcript=text,
            language=global_context.language,
            reason="Platform switch requires confirmation"
            if switch_status != "declined"
            else "Customer declined switch",
            clarification=switch_status != "declined",
            scenario_mode=current.manifest.id,
            scenario_pack_id=current.manifest.id,
            interaction_mode=current.manifest.interaction_mode.value,
            context_lifecycle=entry.lifecycle,
            conversation_status=global_context.conversation_status,
            pack_switch=PackSwitch(
                from_pack=current.manifest.id,
                to_pack=pending.to_pack,
                source="natural",
                status=switch_status,
            ),
        )
        trace.latency_ms.total = (perf_counter() - started) * 1000
        self.dialogs.save_conversation(conversation)
        if global_context.turn_number == 1:
            self.traces.delete(global_context.session_id)
        self.traces.add(global_context.session_id, trace)
        return MessageResult(
            session_id=global_context.session_id,
            response_text=response,
            routing=PlatformDecision(
                response_language=pending.response_language,
                target_pack_id=pending.to_pack,
                switch_status=switch_status,
            ),
            state=PlatformState(
                session_id=global_context.session_id,
                scenario_mode=current.manifest.id,
                response_language=pending.response_language,
                turn_number=global_context.turn_number,
            ),
            trace=trace,
            conversation_status=global_context.conversation_status,
            scenario_pack_id=current.manifest.id,
            scenario_result=entry.result
            or ScenarioResult(
                status=global_context.conversation_status, completed=False, handoff=False
            ),
        )


def _confirmation(text: str) -> bool | None:
    """Only confirmation of an already explicit switch proposal; no domain classification."""
    value = text.strip().casefold()
    if re.match(r"^(да|иә|ия|yes|согласен|согласна|переключай|ауыстыр)(\b|[.!?,])", value):
        return True
    if re.match(r"^(нет|жоқ|no|не надо|не переключай)(\b|[.!?,])", value):
        return False
    return None
