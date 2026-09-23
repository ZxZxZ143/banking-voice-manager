from time import perf_counter

from app.agent.errors import RouterOutputError
from app.agent.router import Router
from app.agent.schemas import RouterDecision
from app.core.contracts import Contract
from app.dialog.models import ConversationStatus, DialogState, DialogTurn
from app.dialog.state import append_turn
from app.dialog.store import InMemoryDialogStore
from app.response.routing import RoutingReplyGenerator
from app.scenarios.decision_policy import DecisionPolicy, PolicyResult
from app.tracing.collector import TraceCollector
from app.tracing.models import LatencyRecord, TraceRecord


class SessionClosedError(Exception):
    pass


class MessageResult(Contract):
    session_id: str
    response_text: str
    routing: RouterDecision
    state: DialogState
    trace: TraceRecord
    conversation_status: ConversationStatus


class MessageService:
    def __init__(
        self,
        router: Router,
        dialogs: InMemoryDialogStore,
        traces: TraceCollector,
        policy: DecisionPolicy,
        replies: RoutingReplyGenerator,
    ) -> None:
        self.router = router
        self.dialogs = dialogs
        self.traces = traces
        self.policy = policy
        self.replies = replies

    async def process(self, session_id: str, text: str) -> MessageResult:
        started = perf_counter()
        async with self.dialogs.session(session_id):
            previous = self.dialogs.get(session_id) or DialogState(session_id=session_id)
            if previous.conversation_status in ("ended", "handoff"):
                raise SessionClosedError("Session is closed; use a new session_id")
            router_started = perf_counter()
            # Snapshot isolation: a failed/misbehaving router cannot mutate stored state.
            decision = await self.router.route(text, previous.model_copy(deep=True))
            router_ms = (perf_counter() - router_started) * 1000
            policy_started = perf_counter()
            try:
                policy = self.policy.decide(decision, previous)
            except ValueError as exc:
                raise RouterOutputError() from exc
            state = self._transition(previous, decision, policy)
            state = append_turn(state, DialogTurn(role="user", text=text))
            policy_ms = (perf_counter() - policy_started) * 1000
            response_started = perf_counter()
            reply = self.replies.generate_result(state, policy, decision)
            response = reply.text
            completed_scenario = state.active_scenario if reply.completed else None
            if reply.completed:
                self._finish_scenario(state, policy.scenario_ids[1:])
                if state.active_scenario:
                    response += {
                        "ru": " Вернёмся к оставшемуся запросу?",
                        "kk": " Қалған сұраққа оралайық па?",
                    }[state.response_language]
            state = append_turn(state, DialogTurn(role="assistant", text=response))
            response_ms = (perf_counter() - response_started) * 1000
            trace = TraceRecord(
                session_id=session_id,
                turn=state.turn_number,
                turn_number=state.turn_number,
                transcript=text,
                language=decision.language,
                scenarios=decision.scenarios,
                alternatives=decision.alternatives,
                reason=policy.reason,
                slots=decision.slots,
                actions=reply.actions,
                source_keys=reply.source_keys,
                policy_outcome=policy.outcome,
                completed_scenario=completed_scenario,
                clarification=policy.outcome == "clarify",
                active_scenario=state.active_scenario,
                pending_scenarios=state.pending_scenarios,
                conversation_status=state.conversation_status,
                handoff=state.conversation_status == "handoff",
                latency_ms=LatencyRecord(
                    router=router_ms,
                    policy=policy_ms,
                    response=response_ms,
                    total=(perf_counter() - started) * 1000,
                ),
            )
            # No awaits between these writes: readers see a complete successful turn.
            self.dialogs.save(state)
            if previous.turn_number == 0:
                self.traces.delete(session_id)
            self.traces.add(session_id, trace)
            return MessageResult(
                session_id=session_id,
                response_text=response,
                routing=decision,
                state=state,
                trace=trace,
                conversation_status=state.conversation_status,
            )

    def _transition(
        self, previous: DialogState, decision: RouterDecision, policy: PolicyResult
    ) -> DialogState:
        state = previous.model_copy(deep=True)
        state.language = decision.language
        state.response_language = decision.response_language or (
            decision.language if decision.language in ("ru", "kk") else previous.response_language
        )
        state.consecutive_low_confidence = policy.consecutive_low_confidence
        state.awaiting_confirmation = False
        if policy.outcome == "handoff":
            if not any(
                selection.scenario_id == "SC37"
                and selection.confidence >= self.policy.settings.accept_threshold
                for selection in decision.scenarios
            ):
                state.unclear_count += 1
            state.clarification_options = []
            state.conversation_status = "handoff"
            return state
        if policy.outcome == "clarify":
            state.unclear_count += 1
            candidates = sorted(
                [*decision.scenarios, *decision.alternatives],
                key=lambda item: item.confidence,
                reverse=True,
            )
            state.clarification_options = list(
                dict.fromkeys(
                    item.scenario_id
                    for item in candidates
                    if not item.scenario_id.startswith("SYS_")
                )
            )[:2]
            state.conversation_status = "awaiting_user"
            return state
        state.unclear_count = 0
        state.clarification_options = []
        selected = policy.scenario_ids[0]
        if selected == "SYS_GOODBYE":
            state.conversation_status = "ended"
            return state
        if selected == "SYS_OUT_OF_SCOPE":
            state.conversation_status = "awaiting_user"
            return state
        if state.active_scenario and state.active_scenario != selected:
            state.scenario_stack = list(
                dict.fromkeys([*state.scenario_stack, state.active_scenario])
            )
        state.scenario_stack = [item for item in state.scenario_stack if item != selected]
        state.active_scenario = selected
        state.pending_scenarios = list(
            dict.fromkeys(
                item
                for item in [*policy.scenario_ids[1:], *state.pending_scenarios]
                if item != selected
            )
        )
        self._merge_slots(state, decision)
        state.conversation_status = "awaiting_user"
        return state

    @staticmethod
    def _merge_slots(state: DialogState, decision: RouterDecision) -> None:
        incoming = {name: value for name, value in decision.slots.items() if value is not None}
        identity = {name for name in ("phone", "iin") if name in incoming}
        prior_identity = {name for name in ("phone", "iin") if name in state.slots}
        if identity:
            # Demo lookup identifiers are not authentication. A corrected one-sided
            # identifier supersedes its old counterpart instead of trapping the user.
            changed = bool(prior_identity) and any(
                state.slots.get(name) != incoming[name] for name in identity
            )
            for name in {"phone", "iin"} - identity:
                state.slots.pop(name, None)
            if changed:
                state.client_id = None
                for name in ("policy_number", "claim_number"):
                    if name not in incoming:
                        state.slots.pop(name, None)
        state.slots.update(incoming)

    @staticmethod
    def _finish_scenario(state: DialogState, current_requests: list[str]) -> None:
        """Complete a read-only answer, not the conversation; resume deferred work."""
        finished = state.active_scenario
        state.scenario_stack = [value for value in state.scenario_stack if value != finished]
        state.pending_scenarios = [value for value in state.pending_scenarios if value != finished]
        next_requested = next(
            (value for value in current_requests if value in state.pending_scenarios), None
        )
        if next_requested:
            state.active_scenario = next_requested
            state.scenario_stack = [
                value for value in state.scenario_stack if value != next_requested
            ]
        elif state.scenario_stack:
            state.active_scenario = state.scenario_stack.pop()
        elif state.pending_scenarios:
            state.active_scenario = state.pending_scenarios.pop(0)
        else:
            state.active_scenario = None
        state.pending_scenarios = [
            value for value in state.pending_scenarios if value != state.active_scenario
        ]
        state.conversation_status = "awaiting_user" if state.active_scenario else "active"
