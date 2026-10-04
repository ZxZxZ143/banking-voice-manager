import asyncio
import re
from datetime import date, timedelta
from time import perf_counter

from app.agent.errors import RouterError, RouterOutputError
from app.packs.insurance_manager.agent.router import Router
from app.packs.insurance_manager.agent.schemas import RouterDecision
from app.packs.insurance_manager.composer import (
    CompositionError,
    composer_payload,
    fallback_composition,
)
from app.packs.insurance_manager.conversation_flow import (
    CONTEXT_SIGNALS,
    discovery_question,
    enter_wrap_up,
    is_relationship_question,
    more_questions,
    remember_relationship,
    scenario_relationship,
    unfinished_request,
    update_relationship,
)
from app.packs.insurance_manager.expected_answers import (
    expected_identifier,
    expected_trip_duration,
    expected_unavailable,
    identifier_answers,
)
from app.packs.insurance_manager.history import append_turn
from app.packs.insurance_manager.response.lookup import IDENTIFIERS, remember
from app.packs.insurance_manager.response.routing import RoutingReplyGenerator
from app.packs.insurance_manager.scenarios.decision_policy import DecisionPolicy, PolicyResult
from app.packs.insurance_manager.speech_capture import advance_capture
from app.packs.insurance_manager.state import DialogState, DialogTurn, IdentificationState
from app.speech.structured.context import SLOT_KINDS, kind_for_slot
from app.speech.structured.normalization import pricing_region
from app.speech.structured.repair import repair_question
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
        decision.language in {"kk", "mixed"}
        and not marked
        and (
            sum(word.casefold() in russian_markers for word in words) >= 2
            or (len(words) <= 5 and any(word.casefold() in russian_markers for word in words))
        )
    ):
        return "ru"
    if (
        decision.language in {"ru", "mixed"}
        and marked
        and (
            (len(words) <= 3 and marked * 2 >= len(words))
            or (marked >= 2 and marked * 2 >= len(words))
            or (len(words) <= 5 and not any(word.casefold() in russian_markers for word in words))
        )
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
        composer=None,
    ) -> None:
        self.router = router
        self.policy = policy
        self.replies = replies
        self.composer = composer

    async def process(
        self,
        previous: DialogState,
        text: str,
        *,
        speech=None,
        channel="text",
        manual_input_available=False,
    ):
        started = perf_counter()
        verifying = bool(previous.conversation and previous.conversation.structured_capture)
        capture = advance_capture(
            previous, text, speech, channel, manual_input_available=manual_input_available
        )
        if capture:
            if capture.question:
                return self._capture_reply(capture, text)
            previous, speech = capture.state, capture.speech
        session_id = previous.session_id
        router_started = perf_counter()
        routing_error = None
        # Snapshot isolation: a failed/misbehaving router cannot mutate stored state.
        try:
            routing_text = text
            if (
                speech
                and (speech.accepted_value or speech.candidate)
                and speech.kind != "region_code"
            ):
                routing_text = "[получен ответ: " + speech.kind + "]"
            routing_state = previous.model_copy(deep=True)
            if verifying and routing_state.conversation:
                from app.packs.insurance_manager.privacy import redact_text

                routing_state.conversation.last_question = "[проверка произнесённого номера]"
                for turn in routing_state.history:
                    turn.text = redact_text(turn.text)
            decision = await self.router.route(routing_text, routing_state)
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
        control = self._context_control(previous, text, decision, started, speech)
        if control is not None:
            return control
        alternatives = identifier_answers(text, previous, self.replies.slots)
        supplied = expected_identifier(text, previous, self.replies.slots)
        if not supplied and (
            self.replies.catalog.get_by_id(decision.scenarios[0].scenario_id)
            or (previous.active_scenario and decision.scenarios[0].scenario_id == "SYS_UNCLEAR")
        ):
            # Read only literal phone data locally; the model need not receive the demo phone.
            phone_context = previous.model_copy(deep=True)
            from app.packs.insurance_manager.state import ConversationState

            phone_context.conversation = ConversationState(expected_slot="phone")
            supplied = expected_identifier(text, phone_context, self.replies.slots)
        if supplied:
            name, value = supplied
            decision.slots[name] = value
            decision.conversation_signal = "answer"
        decision.slots.update(alternatives)
        if alternatives:
            decision.conversation_signal = "answer"
        phone_change = (
            decision.slots.get("contact_field", previous.slots.get("contact_field")) == "phone"
        )
        if channel == "voice" and phone_change:
            decision.slots.pop("new_value", None)
        if speech:
            # Source-validated speech owns these values; no model digit repair is admitted.
            for name in (set(SLOT_KINDS) - {"region"}) | (
                {"region"} if speech.metadata.expected_kind == "region_code" else set()
            ):
                decision.slots.pop(name, None)
            if speech.accepted_value:
                name = "region" if speech.kind == "region_code" else speech.kind
                expected_slot = (
                    previous.conversation.expected_slot if previous.conversation else None
                )
                if kind_for_slot(expected_slot, previous.slots.get("contact_field")) == speech.kind:
                    name = expected_slot
                value = pricing_region(speech.value) if name == "region" else speech.value
                definition = self.replies.slots[name]
                if (
                    name == "region"
                    or (name == "new_value" and speech.kind == "phone")
                    or re.fullmatch(definition.pattern, value)
                ):
                    decision.slots[name] = [value] if definition.type == "list" else value
                    decision.conversation_signal = "answer"
        elif channel == "voice":
            # Ordinary STT/legacy clients have no verified identifier evidence.
            # Preserve semantic routing, but collect those fields through the gate.
            for name in set(SLOT_KINDS) - {"region"}:
                decision.slots.pop(name, None)
        from app.packs.insurance_manager.agent.schemas import IdentifierAnswer

        unavailable = expected_unavailable(text, previous)
        if unavailable and decision.identifier_answer is None:
            decision.identifier_answer = IdentifierAnswer(status="unavailable", field=unavailable)
        if decision.identifier_answer and decision.identifier_answer.status == "unavailable":
            decision.conversation_signal = "partial_answer"
        if (
            (speech or (previous.conversation and previous.conversation.structured_capture))
            and not (speech and speech.accepted_value)
            and not unavailable
            and not (
                decision.identifier_answer and decision.identifier_answer.status == "unavailable"
            )
            and previous.active_scenario
            and all(
                s.scenario_id in {previous.active_scenario, "SYS_UNCLEAR"}
                for s in decision.scenarios
            )
        ):
            capture = advance_capture(
                previous,
                text,
                speech,
                channel,
                allow_unrecognized=True,
                manual_input_available=manual_input_available,
            )
            if capture:
                if capture.question:
                    return self._capture_reply(capture, text)
                previous, speech = capture.state, capture.speech
            else:
                return self._recognition_repair(previous, text, speech)
        duration = expected_trip_duration(text, previous)
        known_duration = duration or (
            previous.conversation.travel_duration_days if previous.conversation else None
        )
        if duration:
            decision.conversation_signal = "partial_answer"
            # A literal duration supplies no calendar dates. Reject model guesses based
            # on today's date; the start must be supplied separately by the customer.
            decision.slots.pop("trip_start", None)
            decision.slots.pop("trip_end", None)
        supplied_end = "trip_end" in decision.slots
        if (
            previous.active_scenario == "SC06"
            and known_duration
            and all(s.scenario_id in {"SC06", "SYS_UNCLEAR"} for s in decision.scenarios)
        ):
            known_dates = {**previous.slots, **decision.slots}
            if known_dates.get("trip_start") and (
                duration
                or ("trip_start" in decision.slots and "trip_end" not in decision.slots)
                or not known_dates.get("trip_end")
            ):
                # The quote counts both start and end dates: an explicit fortnight is 14 days.
                decision.slots["trip_end"] = (
                    date.fromisoformat(known_dates["trip_start"])
                    + timedelta(days=known_duration - 1)
                ).isoformat()
        # The current request language wins over a stale conversation preference.
        # Do not reuse a clarification generated in the wrong reply language.
        reply_language = reply_language_for_turn(text, decision)
        if previous.history and re.fullmatch(r"[\d\s()+-]+|(?:SQ-[A-Za-z]+|CL)-\d+", text.strip()):
            # Numeric identifiers have no spoken-language preference of their own.
            reply_language = previous.response_language
            decision.language = previous.language or previous.response_language
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
        if state.conversation and state.conversation.structured_capture:
            # A non-verification turn reached business routing. Recollect the field
            # after that detour; a later yes must not approve an old read-back.
            state.conversation.structured_capture = None
            if state.conversation.expected_slot:
                state.conversation.last_question = self.replies._ask(
                    state, state.conversation.expected_slot
                ).text
        update_relationship(previous, state, decision, policy)
        if state.conversation:
            state.conversation.resume_after_risk = False
        if state.active_scenario != previous.active_scenario and state.conversation:
            state.conversation.recognition_attempts.clear()
        if speech and speech.metadata.accepted and state.conversation:
            expected_slot = previous.conversation.expected_slot if previous.conversation else None
            if SLOT_KINDS.get(expected_slot) == speech.kind:
                state.conversation.recognition_attempts.pop(expected_slot, None)
        if state.active_scenario and policy.outcome in {"accept", "continue"}:
            memory = state.identification
            answer = decision.identifier_answer
            if answer and answer.status == "unavailable":
                field = answer.field or (
                    previous.conversation.expected_slot if previous.conversation else None
                )
                if field in IDENTIFIERS and field not in decision.slots:
                    remember(memory.unavailable_fields, field)
            for name in IDENTIFIERS & decision.slots.keys():
                value = decision.slots[name]
                known = memory.provided_values.setdefault(name, [])
                if value not in known:
                    known.append(value)
                    memory.exhausted = False
                if name in memory.unavailable_fields:
                    memory.unavailable_fields.remove(name)
        if duration and state.conversation:
            state.conversation.travel_duration_days = duration
        elif supplied_end and state.conversation:
            state.conversation.travel_duration_days = None
        state = append_turn(state, DialogTurn(role="user", text=text))
        policy_ms = (perf_counter() - policy_started) * 1000
        response_started = perf_counter()
        reply = self.replies.generate_result(state, policy, decision)
        state.client_id = reply.resolved_client_id
        state.client_lookup_attempts = reply.lookup_attempts
        state.identification = reply.identification
        state.slots = reply.resolved_slots
        if reply.manager_summary:
            state.manager_summary = reply.manager_summary
        if (
            policy.outcome == "clarify"
            and previous.conversation
            and previous.conversation.expected_slot
            and state.active_scenario == previous.active_scenario
        ):
            reply.expected_slot = previous.conversation.expected_slot
        if (
            self.composer is not None
            and policy.outcome == "handoff"
            and not any(
                s.scenario_id == "SC37" and s.confidence >= self.policy.settings.accept_threshold
                for s in decision.scenarios
            )
        ):
            reply.text = (
                "После нескольких уточнений я не смог понять, какая помощь нужна. "
                "Специалист сможет разобраться подробнее. "
                if state.response_language == "ru"
                else "Бірнеше нақтылаудан кейін қандай көмек керегін түсіне алмадым. "
                "Маман мәселені толығырақ анықтай алады. "
            ) + reply.text
        if reply.handoff:
            state.conversation_status = "handoff"
        response = reply.text
        if self.composer is None and state.conversation:
            state.conversation.expected_slot = reply.expected_slot
            state.conversation.expected_answer_type = "slot" if reply.expected_slot else None
            state.conversation.last_question = reply.text if reply.expected_slot else None
        business_ms = (perf_counter() - response_started) * 1000
        composer_ms, composer_error = None, None
        if self.composer is not None and state.conversation is not None:
            explicit_operator = policy.outcome == "handoff" and any(
                s.scenario_id == "SC37" and s.confidence >= self.policy.settings.accept_threshold
                for s in decision.scenarios
            )
            payload = composer_payload(previous, state, text, decision, policy, reply, self.replies)
            if explicit_operator:
                composed = fallback_composition(payload, reply)
            else:
                composer_started = perf_counter()
                try:
                    async with asyncio.timeout(max(0.001, 55 - (perf_counter() - started))):
                        composed = await self.composer.compose(payload)
                except (RouterError, ValueError, TimeoutError) as exc:
                    if isinstance(exc, CompositionError) and exc.goal_context:
                        # A rejected question must not erase an understood partial goal.
                        # Only typed conversational context survives, never rejected prose.
                        payload["conversation"]["acknowledged_information"] = exc.goal_context
                        payload["relationship_choice_allowed"] = False
                    composer_error = (
                        exc.code
                        if isinstance(exc, RouterError)
                        else "composer_timeout"
                        if isinstance(exc, TimeoutError)
                        else "composer_" + str(exc)
                        if str(exc)
                        in {
                            "unsupported_composer_claim",
                            "one_question_required",
                            "terminal_composition",
                            "unauthorized_handoff",
                            "unexpected_collection_target",
                            "unexpected_slot",
                            "missing_next_question",
                            "repeated_question",
                            "unsupported_fact_variant",
                            "unnecessary_policy_classification",
                        }
                        else "composer_validation"
                    )
                    composed = fallback_composition(payload, reply)
                composer_ms = (perf_counter() - composer_started) * 1000
            response = " ".join(
                part
                for part in (composed.acknowledgement, payload["grounded_facts"], composed.question)
                if part
            )
            meta = state.conversation
            if payload["allowed_action"] == "ask_slot" and payload["next_slot"] in IDENTIFIERS:
                # Identifier requests are an application-owned step. Free wording (including
                # indirect pronouns) must never reopen an unavailable or failed path.
                from app.packs.insurance_manager.privacy import redact_text

                composed.question = redact_text(reply.text, state.slots)
                composed.acknowledgement = ""
            variant = getattr(composed, "fact_variant", "default")
            if variant in payload["grounded_variants"]:
                payload["grounded_facts"] = payload["grounded_variants"][variant]
            if not payload["allow_followup"]:
                composed.question = None
                composed.acknowledgement = ""
            if set(composed.acknowledged_information) & {"existing_policy", "new_policy"}:
                # Communicative progress is not business authorization. It only resets
                # misunderstanding; neither scenarios nor facts are chosen here.
                meta.repair_attempts = 0
                state.consecutive_low_confidence = 0
                state.unclear_count = 0
            # Omit mechanical reactions, including a repeated acknowledgement prefix.
            from app.packs.insurance_manager.composer import optional_acknowledgement

            ack = optional_acknowledgement(composed.acknowledgement, meta.last_acknowledgement)
            if payload["allowed_action"] in {"handoff", "goodbye", "scope_reply"}:
                ack = ""
            response = " ".join(
                part for part in (ack, payload["grounded_facts"], composed.question) if part
            )
            meta.last_acknowledgement = ack
            meta.last_assistant_act = composed.conversation_act
            meta.last_question = composed.question
            meta.expected_answer_type = (
                "slot" if payload["next_slot"] else composed.expected_answer_type
            )
            meta.expected_slot = payload["next_slot"]
            meta.acknowledged_information = list(
                dict.fromkeys([*meta.acknowledged_information, *composed.acknowledged_information])
            )[-8:]
            if meta.policy_relationship == "unknown":
                for relationship in ("existing", "new"):
                    if relationship + "_policy" in meta.acknowledged_information:
                        remember_relationship(meta, relationship)
                        break
            if is_relationship_question(composed.question):
                meta.expected_answer_type = "policy_relationship"
            meta.phase = (
                "handoff"
                if state.conversation_status == "handoff"
                else "collect"
                if payload["next_slot"]
                else "resolve"
                if reply.completed
                else "discover"
            )
        collected_data = dict(state.slots)
        completed_scenario = state.active_scenario if reply.completed else None
        if reply.completed:
            self._finish_scenario(state, policy.scenario_ids[1:])
            if state.active_scenario:
                response += {
                    "ru": " Вернёмся к оставшемуся запросу?",
                    "kk": " Қалған сұраққа оралайық па?",
                }[state.response_language]
        if state.conversation and state.conversation_status not in {"handoff", "ended"}:
            resolved = reply.completed or (
                policy.scenario_ids == ["SYS_OUT_OF_SCOPE"] and not unfinished_request(previous)
            )
            if resolved and not (
                state.active_scenario
                or state.pending_scenarios
                or state.scenario_stack
                or state.awaiting_confirmation
                or reply.expected_slot
            ):
                enter_wrap_up(state.conversation, state.response_language)
                state.conversation.last_assistant_act = "answer"
                state.conversation_status = "awaiting_user"
                # Facts are immutable; the application owns this lifecycle question.
                if not reply.completed and self.composer is not None:
                    response = payload["grounded_facts"]
                response += " " + more_questions(state.response_language)
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
            composer_error=composer_error,
            recognition=speech.metadata if speech else None,
            conversation_act=state.conversation.last_assistant_act if state.conversation else None,
            expected_answer_type=(
                state.conversation.expected_answer_type if state.conversation else None
            ),
            expected_slot=state.conversation.expected_slot if state.conversation else None,
            conversation_phase=state.conversation.phase if state.conversation else None,
            policy_relationship=(
                state.conversation.policy_relationship if state.conversation else None
            ),
            repair_attempts=state.conversation.repair_attempts if state.conversation else None,
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
            manager_summary=reply.manager_summary.model_dump() if reply.manager_summary else None,
            latency_ms=LatencyRecord(
                router=router_ms,
                policy=policy_ms,
                response=response_ms,
                business=business_ms,
                composer=composer_ms,
                total=(perf_counter() - started) * 1000,
            ),
        )
        return state, decision, trace, reply, completed_scenario, collected_data

    def _context_control(self, previous, text, decision, started, speech):
        """Semantic control signals operate only in the application-authorized phase."""
        meta = previous.conversation
        signal = decision.conversation_signal
        if not meta or decision.slots or signal not in CONTEXT_SIGNALS:
            return None
        selected = [item.scenario_id for item in decision.scenarios]
        wrap_up = meta.phase == "wrap_up" and not unfinished_request(previous)
        resume = meta.resume_after_risk and signal == "acknowledgement"
        if not (wrap_up or resume) or previous.conversation_status in {"handoff", "ended"}:
            return None
        allowed = (
            {"SYS_UNCLEAR", "SYS_GOODBYE"}
            if wrap_up
            else {
                "SYS_UNCLEAR",
                previous.active_scenario,
            }
        )
        if selected and (len(selected) != 1 or selected[0] not in allowed):
            return None  # A direct business request always takes precedence.
        from app.conversation.terminal import terminal_reply
        from app.packs.insurance_manager.response.routing import RoutingReplyResult

        state = previous.model_copy(deep=True)
        # Acknowledgements are understood controls, not uncertain scenario selections.
        decision = RouterDecision.model_validate(
            {
                **decision.model_dump(),
                "scenarios": [],
                "segments": [],
                "alternatives": [],
                "is_continuation": False,
                "clarification_question": None,
                "relationship_needed": False,
            }
        )
        meta = state.conversation
        language = reply_language_for_turn(text, decision) or previous.response_language
        state.language = decision.language
        state.response_language = language
        decision.response_language = language
        state.unclear_count = state.consecutive_low_confidence = meta.repair_attempts = 0
        meta.resume_after_risk = False
        ended = wrap_up and signal == "no_more_questions"
        state.conversation_status = "ended" if ended else "awaiting_user"
        if resume:
            question = meta.last_question
            if meta.expected_slot and not question:
                question = self.replies._ask(state, meta.expected_slot).text
            question = question or discovery_question(state)
            response = (
                "Продолжим ваш запрос. " if language == "ru" else "Сұрағыңызды жалғастырайық. "
            ) + question
            meta.last_assistant_act = "ask_slot" if meta.expected_slot else "ask_followup"
            meta.last_question = question
        elif ended:
            response = terminal_reply("ended", language)
            meta.last_assistant_act = "goodbye"
            meta.last_question = meta.expected_answer_type = None
        elif signal == "more_questions":
            response = (
                "Конечно. Что ещё хотите узнать?"
                if language == "ru"
                else "Әрине. Тағы не білгіңіз келеді?"
            )
            meta.last_assistant_act = "ask_followup"
            meta.last_question = response
            meta.expected_answer_type = "problem_description"
        else:
            response = ("Пожалуйста. " if language == "ru" else "Оқасы жоқ. ") + more_questions(
                language
            )
            enter_wrap_up(meta, language)
            meta.last_assistant_act = "ask_followup"
        reply = RoutingReplyResult(text=response, expected_slot=meta.expected_slot, completed=ended)
        state = append_turn(state, DialogTurn(role="user", text=text))
        state = append_turn(state, DialogTurn(role="assistant", text=response))
        elapsed = (perf_counter() - started) * 1000
        trace = TraceRecord(
            session_id=state.session_id,
            turn=state.turn_number,
            turn_number=state.turn_number,
            transcript=text,
            language=decision.language,
            scenarios=decision.scenarios,
            reason="Resume unfinished request after security guidance"
            if resume
            else "Resolved request follow-up",
            policy_outcome="continue" if resume else "wrap_up",
            recognition=speech.metadata if speech else None,
            conversation_act=meta.last_assistant_act,
            expected_answer_type=meta.expected_answer_type,
            expected_slot=meta.expected_slot,
            conversation_phase=meta.phase,
            policy_relationship=meta.policy_relationship,
            repair_attempts=0,
            active_scenario=state.active_scenario,
            scenario_stack=state.scenario_stack,
            pending_scenarios=state.pending_scenarios,
            conversation_status=state.conversation_status,
            latency_ms=LatencyRecord(router=elapsed, total=elapsed),
        )
        return state, decision, trace, reply, None, dict(state.slots)

    def _capture_reply(self, capture, text):
        """Recognition-only turn: no Router/Composer/lookup or business mutations."""
        from app.packs.insurance_manager.response.routing import RoutingReplyResult
        from app.packs.insurance_manager.tools.capabilities import ManagerSummary

        state, speech = capture.state, capture.speech
        meta = state.conversation
        state.conversation_status = "handoff" if capture.exhausted else "awaiting_user"
        meta.last_question = None if capture.exhausted else capture.question
        meta.last_assistant_act = "handoff" if capture.exhausted else "verify_identifier"
        meta.expected_answer_type = None if capture.exhausted else "slot"
        # No phase transition into/out of wrap_up; this operates only on pending work.
        if capture.exhausted:
            meta.phase = "handoff"
            meta.expected_slot = None
            state.manager_summary = ManagerSummary(
                reason="specialist_required",
                scenario=state.active_scenario,
                collected_fields=sorted(state.slots),
                known_client=bool(state.client_id),
                next_required_action="verify_spoken_identifier",
            )
        reply = RoutingReplyResult(
            text=capture.question,
            expected_slot=meta.expected_slot,
            handoff=capture.exhausted,
            manager_summary=state.manager_summary,
        )
        decision = RouterDecision(
            language=state.language or state.response_language,
            response_language=state.response_language,
            scenarios=[
                dict(
                    scenario_id=state.active_scenario,
                    confidence=1,
                    reason="Application identifier verification; no business execution",
                )
            ],
            is_continuation=True,
        )
        # Even short partial digits/letters cannot leak through later history projections.
        state = append_turn(state, DialogTurn(role="user", text="[произнесённый номер скрыт]"))
        state = append_turn(state, DialogTurn(role="assistant", text="[проверка номера]"))
        trace = TraceRecord(
            turn=state.turn_number,
            transcript="[произнесённый номер скрыт]",
            recognition=speech.metadata,
            expected_slot=meta.expected_slot,
            conversation_act=meta.last_assistant_act,
            conversation_status=state.conversation_status,
            conversation_phase=meta.phase,
            policy_relationship=meta.policy_relationship,
            handoff=capture.exhausted,
            active_scenario=state.active_scenario,
            reason="Application identifier verification; no lookup attempted",
            manager_summary=state.manager_summary.model_dump() if state.manager_summary else None,
        )
        return state, decision, trace, reply, None, dict(state.slots)

    def _recognition_repair(self, previous, text, speech):
        from app.packs.insurance_manager.response.routing import RoutingReplyResult

        state = previous.model_copy(deep=True)
        meta = state.conversation
        kind = speech.metadata.expected_kind
        slot = meta.expected_slot
        attempts = min(2, meta.recognition_attempts.get(slot, 0) + 1)
        meta.recognition_attempts[slot] = attempts
        policy = PolicyResult(
            outcome="continue",
            scenario_ids=[state.active_scenario],
            consecutive_low_confidence=0,
            reason="Structured speech recognition failed; no lookup attempted",
        )
        decision = RouterDecision(
            language=state.language or state.response_language,
            response_language=state.response_language,
            scenarios=[
                dict(
                    scenario_id="SYS_UNCLEAR",
                    confidence=0,
                    reason="Structured speech requires repair",
                )
            ],
        )
        if attempts == 1:
            response = repair_question(kind, state.response_language)
            reply = RoutingReplyResult(text=response, expected_slot=slot)
            state.conversation_status = "awaiting_user"
        else:
            # Recognition exhaustion excludes this field from lookup collection;
            # failed lookup fingerprints/counters are untouched.
            if slot in IDENTIFIERS:
                remember(state.identification.unavailable_fields, slot)
                reply = self.replies.generate_result(state, policy, decision)
                state.identification = reply.identification
            else:
                reply = RoutingReplyResult(text="", handoff=True)
            if not reply.expected_slot or reply.expected_slot == slot or reply.handoff:
                response = (
                    "Не удалось надёжно распознать данные. Подготовлю обращение для специалиста."
                    if state.response_language == "ru"
                    else "Деректерді сенімді тану мүмкін болмады. Маманға өтініш дайындаймын."
                )
                state.conversation_status = "handoff"
                reply.handoff = True
                reply.expected_slot = None
                from app.packs.insurance_manager.tools.capabilities import ManagerSummary

                reply.manager_summary = reply.manager_summary or ManagerSummary(
                    reason="specialist_required",
                    scenario=state.active_scenario,
                    collected_fields=sorted(state.slots),
                    unavailable_fields=list(state.identification.unavailable_fields),
                    known_client=bool(state.client_id),
                    next_required_action="verify_spoken_identifier",
                )
                state.manager_summary = reply.manager_summary
            else:
                response = (
                    "Этот номер не удалось распознать. "
                    if state.response_language == "ru"
                    else "Бұл нөмірді тану мүмкін болмады. "
                ) + reply.text
                state.conversation_status = "awaiting_user"
        reply.text = response
        meta.last_question = response if not reply.handoff else None
        meta.expected_slot = reply.expected_slot
        meta.expected_answer_type = "slot" if reply.expected_slot else None
        meta.last_assistant_act = "handoff" if reply.handoff else "ask_slot"
        meta.phase = "handoff" if reply.handoff else "collect"
        state = append_turn(state, DialogTurn(role="user", text=text))
        state = append_turn(state, DialogTurn(role="assistant", text=response))
        trace = TraceRecord(
            turn=state.turn_number,
            transcript=text,
            recognition=speech.metadata,
            expected_slot=meta.expected_slot,
            conversation_act=meta.last_assistant_act,
            conversation_status=state.conversation_status,
            handoff=reply.handoff,
            reason=policy.reason,
            active_scenario=state.active_scenario,
        )
        return state, decision, trace, reply, None, dict(state.slots)

    def _transition(
        self, previous: DialogState, decision: RouterDecision, policy: PolicyResult
    ) -> DialogState:
        state = previous.model_copy(deep=True)
        state.language = decision.language
        state.response_language = decision.response_language or (
            decision.language if decision.language in ("ru", "kk") else previous.response_language
        )
        state.consecutive_low_confidence = policy.consecutive_low_confidence
        progress = bool(decision.slots and decision.is_continuation) or bool(
            state.conversation
            and state.conversation.expected_answer_type
            and decision.conversation_signal in {"answer", "partial_answer"}
        )
        greeting = decision.conversation_signal == "greeting"
        if state.conversation and (
            progress or greeting or policy.outcome in {"accept", "continue"}
        ):
            state.conversation.repair_attempts = 0
            state.consecutive_low_confidence = 0
            state.unclear_count = 0
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
            if not progress and not greeting:
                state.unclear_count += 1
                if state.conversation:
                    state.conversation.repair_attempts += 1
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
        if (
            state.conversation
            and selected != "SYS_OUT_OF_SCOPE"
            and previous.active_scenario != selected
        ):
            state.conversation.travel_duration_days = None
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
                state.scenario_identification[previous.active_scenario] = (
                    previous.identification.model_copy(deep=True)
                )
            state.identification = state.scenario_identification.get(
                selected, IdentificationState()
            ).model_copy(deep=True)
            state.manager_summary = None
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
        if identity:
            # Demo lookup identifiers are not authentication. A corrected one-sided
            # identifier supersedes its old counterpart instead of trapping the user.
            changed = bool(state.client_id) and any(
                state.slots.get(name) != incoming[name] for name in identity
            )
            for name in {"phone", "iin"} - identity:
                state.slots.pop(name, None)
            if changed:
                if state.client_id:
                    state.client_lookup_attempts = []
                state.client_id = None
                state.identification.successful_field = None
                state.scenario_slots = {}
                for name in ("policy_number", "claim_number"):
                    if name not in incoming:
                        state.slots.pop(name, None)
        state.slots.update(incoming)

    @staticmethod
    def _finish_scenario(state: DialogState, current_requests: list[str]) -> None:
        """Complete a read-only answer, not the conversation; resume deferred work."""
        finished = state.active_scenario
        if state.conversation:
            state.conversation.scenario_relationships.pop(finished, None)
        state.scenario_identification.pop(finished, None)
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
            if state.conversation:
                remember_relationship(
                    state.conversation,
                    state.conversation.scenario_relationships.get(
                        state.active_scenario, scenario_relationship(state.active_scenario)
                    ),
                )
            state.identification = state.scenario_identification.get(
                state.active_scenario, IdentificationState()
            ).model_copy(deep=True)
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
