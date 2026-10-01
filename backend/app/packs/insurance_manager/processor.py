import re
from time import perf_counter

from app.agent.errors import RouterOutputError
from app.packs.insurance_manager.agent.router import Router
from app.packs.insurance_manager.agent.schemas import RouterDecision
from app.packs.insurance_manager.history import append_turn
from app.packs.insurance_manager.response.routing import RoutingReplyGenerator
from app.packs.insurance_manager.scenarios.decision_policy import DecisionPolicy, PolicyResult
from app.packs.insurance_manager.state import DialogState, DialogTurn
from app.tracing.models import LatencyRecord, TraceRecord


def reply_language_for_turn(text: str, decision: RouterDecision) -> str | None:
    """Protect a clearly Kazakh turn from a stale Russian context label.

    This is only a reply-language guard, not intent classification. A borrowed
    Kazakh place name or greeting in a longer Russian sentence does not suffice.
    Mixed-language turns retain the router's predominant-language choice.
    """
    words = re.findall(r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]+", text)
    marked = sum(bool(re.search(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]", word)) for word in words)
    # Conservative language-only evidence, never business/intent keywords.
    russian_markers = {
        "и",
        "в",
        "на",
        "по",
        "как",
        "где",
        "когда",
        "что",
        "или",
        "ли",
        "мой",
        "мне",
        "меня",
        "моего",
        "ваш",
        "хочу",
        "нужно",
        "можно",
        "ещё",
    }
    if (
        decision.language == "kk"
        and not marked
        and sum(word.casefold() in russian_markers for word in words) >= 2
    ):
        return "ru"
    if (
        decision.language == "ru"
        and marked
        and ((len(words) == 1) or (marked >= 2 and marked * 2 >= len(words)))
    ):
        return "kk"
    if decision.language in ("ru", "kk"):
        return decision.language
    return decision.response_language


class InsuranceTurnProcessor:
    def __init__(
        self,
        router: Router,
        policy: DecisionPolicy,
        replies: RoutingReplyGenerator,
    ) -> None:
        self.router = router
        self.policy = policy
        self.replies = replies

    async def process(self, previous: DialogState, text: str):
        started = perf_counter()
        session_id = previous.session_id
        router_started = perf_counter()
        routing_error = None
        # Snapshot isolation: a failed/misbehaving router cannot mutate stored state.
        try:
            decision = await self.router.route(text, previous.model_copy(deep=True))
        except RouterOutputError as exc:
            # Do not repair, execute or invent a rejected business decision. The
            # application records a safe clarification outcome; repeated failures
            # follow the same bounded handoff policy as unresolved uncertainty.
            routing_error = exc.validation_reason
            language = previous.language or "ru"
            decision = RouterDecision(
                language=language,
                response_language=previous.response_language,
                scenarios=[
                    dict(
                        scenario_id="SYS_UNCLEAR",
                        confidence=0,
                        reason="Invalid routing output; clarification required",
                    )
                ],
                segments=[
                    dict(
                        scenario_id="SYS_UNCLEAR",
                        confidence=0,
                        text=text,
                        reason="Invalid routing output; clarification required",
                    )
                ],
            )
        # The current request language wins over a stale conversation preference.
        # Do not reuse a clarification generated in the wrong reply language.
        reply_language = reply_language_for_turn(text, decision)
        if reply_language is not None and decision.response_language != reply_language:
            decision = decision.model_copy(
                update={
                    "response_language": reply_language,
                    "clarification_question": None,
                },
                deep=True,
            )
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
        if reply.handoff:
            state.conversation_status = "handoff"
        response = reply.text
        collected_data = dict(state.slots)
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
            reason=(
                f"Routing output rejected ({routing_error}); {policy.reason}"
                if routing_error
                else policy.reason
            ),
            routing_error=routing_error,
            slots=decision.slots,
            actions=reply.actions,
            source_keys=reply.source_keys,
            policy_outcome=policy.outcome,
            completed_scenario=completed_scenario,
            clarification=policy.outcome == "clarify",
            active_scenario=state.active_scenario,
            pending_scenarios=state.pending_scenarios,
            scenario_stack=state.scenario_stack,
            scenario_mode=state.scenario_mode,
            conversation_status=state.conversation_status,
            handoff=state.conversation_status == "handoff",
            latency_ms=LatencyRecord(
                router=router_ms,
                policy=policy_ms,
                response=response_ms,
                total=(perf_counter() - started) * 1000,
            ),
        )
        return state, decision, trace, reply, completed_scenario, collected_data

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
        if previous.active_scenario != selected:
            if previous.active_scenario:
                state.scenario_slots[previous.active_scenario] = dict(previous.slots)
            # Personal identifiers can be reused; scenario-specific parameters cannot
            # silently leak from a previous trip/quote into a new independent request.
            shared = {
                key: value
                for key, value in previous.slots.items()
                if key in {"phone", "iin", "policy_number", "claim_number"}
            }
            state.slots = {**state.scenario_slots.get(selected, {}), **shared}
        self._merge_slots(state, decision)
        # Keep slots supplied for independently requested deferred scenarios.
        for scenario_id in policy.scenario_ids[1:]:
            scenario = self.replies.catalog.get_by_id(scenario_id)
            if scenario:
                allowed = {*scenario.slots.required, *scenario.slots.optional}
                state.scenario_slots[scenario_id] = {
                    **state.scenario_slots.get(scenario_id, {}),
                    **{key: value for key, value in decision.slots.items() if key in allowed},
                }
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
                state.scenario_slots = {}
                for name in ("policy_number", "claim_number"):
                    if name not in incoming:
                        state.slots.pop(name, None)
        state.slots.update(incoming)

    @staticmethod
    def _finish_scenario(state: DialogState, current_requests: list[str]) -> None:
        """Complete a read-only answer, not the conversation; resume deferred work."""
        finished = state.active_scenario
        state.scenario_slots.pop(finished, None)
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
        if state.active_scenario:
            state.slots = {
                **state.scenario_slots.get(state.active_scenario, {}),
                **{
                    key: value
                    for key, value in state.slots.items()
                    if key in {"phone", "iin", "policy_number", "claim_number"}
                },
            }
        else:
            state.slots = {
                key: value
                for key, value in state.slots.items()
                if key in {"phone", "iin", "policy_number", "claim_number"}
            }
        state.conversation_status = "awaiting_user" if state.active_scenario else "active"
