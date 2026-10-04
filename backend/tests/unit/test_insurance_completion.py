"""Application lifecycle regressions with semantic model fixtures, not live quality scores."""

import asyncio
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agents import AgentOutputSchema
from pydantic import ValidationError
from scripts.evaluate_insurance_conversation import completion_checks

from app.agent.errors import RouterOutputError
from app.core.config import Settings
from app.core.services import build_services
from app.packs.insurance_manager.agent.schemas import RouterAgentOutput, RouterDecision
from app.packs.insurance_manager.composer import (
    ComposedReply,
    ConversationComposer,
    fallback_composition,
    validate_composition,
)
from app.packs.insurance_manager.conversation_flow import (
    discovery_question,
    is_relationship_question,
    relationship_choice_allowed,
)
from app.packs.insurance_manager.state import ConversationState, DialogState
from app.risk.models import RiskSignal, SecurityDecision
from app.speech.structured.context import context_for_slot
from app.speech.structured.recognition import resolve_recognition


class SemanticRouter:
    def __init__(self, decisions):
        self.decisions = deque(decisions)
        self.contexts = []

    async def route(self, text, state):
        self.contexts.append(state)
        return self.decisions.popleft().model_copy(deep=True)


class FallbackComposer:
    async def compose(self, payload):
        return fallback_composition(
            payload, SimpleNamespace(text=payload.get("slot_description") or "")
        )


def decision(sid="SYS_UNCLEAR", *, lang="ru", signal="none", relationship="unknown", **kw):
    return RouterDecision(
        language=lang,
        response_language=lang,
        conversation_signal=signal,
        policy_relationship=relationship,
        scenarios=[]
        if signal in {"acknowledgement", "more_questions", "no_more_questions"}
        else [dict(scenario_id=sid, confidence=0.99, reason="Semantic fixture")],
        **kw,
    )


def build(*decisions, lang="ru"):
    router = SemanticRouter(decisions)
    built = build_services(Settings(_env_file=None, demo_test_phone=None), router_override=router)
    built.insurance.processor.composer = FallbackComposer()
    risk = built.registry.get("fraud_security").intelligence
    risk.agent = SimpleNamespace(
        analyze=AsyncMock(
            return_value=SecurityDecision(
                intent="concern",
                language=lang,
                response_language=lang,
                risk_relevant=True,
                confidence=0.99,
                level="high",
                signals=[RiskSignal.OTP_REQUESTED],
                recommended_action="security_review",
            )
        )
    )
    built.messages.risk = risk
    return built, router


def assert_metrics(turn, **spec):
    checks = completion_checks({"allow_relationship_question": False, **spec}, turn)
    assert checks and all(checks.values()), checks


@pytest.mark.parametrize("lang", ["ru", "kk"])
@pytest.mark.parametrize("source", ["SC31", "SC33", "security"])
def test_resolved_answer_ack_more_questions_and_end(lang, source):
    choices = (
        []
        if source == "security"
        else [
            decision(
                source,
                lang=lang,
                slots={"city": "Almaty"} if source == "SC33" else {},
            )
        ]
    )
    built, router = build(
        *choices,
        decision(lang=lang, signal="acknowledgement"),
        decision(lang=lang, signal="more_questions"),
        decision("SYS_GOODBYE", lang=lang, signal="no_more_questions"),
        lang=lang,
    )

    async def run():
        text = (
            "Оператор банка сказал сообщить четырёхзначный код из SMS"
            if source == "security"
            else "Как оплатить страховку?"
            if source == "SC31"
            else "Где ваш офис в Алматы?"
        )
        turn = await built.messages.process("wrap", text)
        assert_metrics(turn, wrap_up=True, relationship="not_applicable")
        assert turn.conversation_status == "awaiting_user"
        assert not turn.state.active_scenario and not turn.state.conversation.expected_slot
        if source == "security":
            assert turn.trace.actions == []
            assert "security.policy.do_not_share_secrets" in turn.trace.source_keys
        for text, spec in [
            ("Хорошо" if lang == "ru" else "Жақсы", {"resolved_acknowledgement": True}),
            ("Есть ещё вопрос" if lang == "ru" else "Тағы сұрағым бар", {"open_followup": True}),
            ("Нет, спасибо" if lang == "ru" else "Жоқ, рақмет", {"no_more_questions": True}),
        ]:
            turn = await built.messages.process("wrap", text)
            assert_metrics(turn, **spec)
            assert turn.trace.actions == []
        assert not router.decisions

    asyncio.run(run())


@pytest.mark.parametrize("lang", ["ru", "kk"])
def test_direct_new_request_after_wrap_up_routes_without_classification(lang):
    built, _ = build(decision("SC31", lang=lang), decision("SC06", lang=lang), lang=lang)

    async def run():
        await built.messages.process(
            "direct", "Как оплатить?" if lang == "ru" else "Қалай төлеуге болады?"
        )
        turn = await built.messages.process(
            "direct", "Хочу страховку для поездки" if lang == "ru" else "Сапарға сақтандыру керек"
        )
        assert_metrics(turn, wrap_up=False, relationship="new", scenario="SC06")
        assert turn.state.conversation.expected_slot == "trip_country"

    asyncio.run(run())


def test_existing_relationship_survives_missing_policy_and_related_app_investigation():
    built, router = build(
        decision(signal="partial_answer", relationship="existing"),
        decision(signal="partial_answer"),
        decision("SC30"),
        decision("SC34"),
    )

    async def run():
        for text in [
            "У меня уже есть полис",
            "Он не появился в приложении",
            "Оплатил, но его нет",
            "Не могу войти в приложение",
        ]:
            turn = await built.messages.process("existing", text)
            assert_metrics(turn, relationship="existing")
        assert router.contexts[1].conversation.policy_relationship == "existing"
        # Conversational ownership never creates verified customer/business records.
        assert turn.state.client_id is None and turn.trace.actions == ["kb_lookup"]

    asyncio.run(run())


@pytest.mark.parametrize("relation", ["new", "existing"])
def test_risk_detour_ack_resumes_exact_question_and_relation_even_after_failed_voice(relation):
    sid, slot = ("SC06", "trip_country") if relation == "new" else ("SC25", "phone")
    built, _ = build(decision(sid), decision(sid, signal="acknowledgement"))

    async def run():
        first = await built.messages.process(
            "resume", "Нужна страховка" if relation == "new" else "Проверьте срок полиса"
        )
        question = first.state.conversation.last_question
        await built.messages.process("resume", "Звонящий просит код из SMS")
        stored = (
            built.dialogs.get_conversation("resume").scenario_contexts["insurance_manager"].state
        )
        assert stored.conversation.resume_after_risk
        assert stored.conversation.expected_slot == slot
        previous = stored.to_dialog(built.dialogs.get_conversation("resume").global_context)
        # An acceptance of risk advice is not a failed attempt to dictate a phone.
        speech = await resolve_recognition("Хорошо", b"", context_for_slot("phone", "ru"))
        state, _, trace, _, _, _ = await built.insurance.processor.process(
            previous, "Хорошо", speech=speech
        )
        assert state.conversation.last_question == question
        assert state.conversation.expected_slot == slot
        assert state.conversation.policy_relationship == relation
        assert not state.conversation.recognition_attempts
        assert not state.conversation.resume_after_risk and trace.actions == []
        assert state.active_scenario == sid and state.slots == stored.slots

    asyncio.run(run())


def test_risk_preserves_partial_existing_goal_without_selected_scenario():
    built, _ = build(
        decision(signal="partial_answer", relationship="existing"),
        decision(signal="acknowledgement"),
    )

    async def run():
        before = await built.messages.process("partial", "У меня уже есть полис")
        risk = await built.messages.process("partial", "Звонящий просит код из SMS")
        assert risk.state.conversation.resume_after_risk
        after = await built.messages.process("partial", "Спасибо")
        assert after.state.conversation.last_question == before.state.conversation.last_question
        assert_metrics(after, relationship="existing", wrap_up=False)

    asyncio.run(run())


def test_completion_resumes_deferred_task_and_its_relationship_instead_of_wrap_up():
    built, _ = build(decision("SC25"), decision("SC31"))

    async def run():
        await built.messages.process("stack", "Проверьте мой полис")
        turn = await built.messages.process("stack", "Какие способы оплаты?")
        assert_metrics(turn, relationship="existing", wrap_up=False)
        assert turn.state.active_scenario == "SC25"

    asyncio.run(run())


@pytest.mark.parametrize("active", [False, True])
def test_identity_reply_preserves_unfinished_existing_goal(active):
    built, _ = build(
        decision("SC25") if active else decision(signal="partial_answer", relationship="existing"),
        decision("SYS_OUT_OF_SCOPE", relationship="not_applicable", scope_kind="identity"),
    )

    async def run():
        first = await built.messages.process(
            "identity", "Проверьте полис" if active else "У меня полис"
        )
        turn = await built.messages.process("identity", "Вы бот?")
        assert_metrics(turn, relationship="existing", wrap_up=False)
        assert turn.state.active_scenario == first.state.active_scenario
        assert turn.state.conversation.expected_slot == first.state.conversation.expected_slot

    asyncio.run(run())


@pytest.mark.parametrize("lang", ["ru", "kk"])
def test_standalone_identity_answer_enters_wrap_up(lang):
    built, _ = build(
        decision(
            "SYS_OUT_OF_SCOPE", lang=lang, relationship="not_applicable", scope_kind="identity"
        )
    )
    turn = asyncio.run(
        built.messages.process("identity", "Вы бот?" if lang == "ru" else "Сіз ботсыз ба?")
    )
    assert_metrics(turn, relationship="not_applicable", wrap_up=True)
    assert turn.response_text.count("?") == 1


@pytest.mark.parametrize(
    "relation,needed,allowed",
    [
        ("unknown", True, True),
        ("unknown", False, False),
        ("existing", True, False),
        ("new", True, False),
        ("not_applicable", True, False),
    ],
)
def test_binary_question_requires_unknown_relevant_semantic_goal(relation, needed, allowed):
    state = DialogState(
        session_id="choice", conversation=ConversationState(policy_relationship=relation)
    )
    routed = decision(relationship_needed=needed)
    assert relationship_choice_allowed(state, routed) == allowed
    assert is_relationship_question(discovery_question(state, routed)) == allowed
    payload = {
        "allowed_action": "discover",
        "relationship_choice_allowed": allowed,
        "conversation": {"last_question": None},
    }
    result = ComposedReply(
        conversation_act="ask_followup",
        acknowledgement="",
        question="Новый полис или существующий?",
        expected_answer_type="choice",
    )
    if allowed:
        validate_composition(result, payload)
    else:
        with pytest.raises(ValueError, match="unnecessary_policy_classification"):
            validate_composition(result, payload)


def test_new_context_and_explicit_correction_override_completed_policy_relationship():
    built, _ = build(
        decision(signal="partial_answer", relationship="existing"),
        decision(signal="partial_answer", relationship="new"),
        decision("SC01"),
        decision("SC01", signal="answer", is_continuation=True, slots={"region": "Алматы"}),
    )

    async def run():
        await built.messages.process("correct", "У меня полис")
        turn = await built.messages.process("correct", "Нет, я хочу оформить новую страховку")
        assert_metrics(turn, relationship="new")
        for text in ["Хочу застраховать автомобиль", "Алматы"]:
            turn = await built.messages.process("correct", text)
            assert_metrics(turn, relationship="new", wrap_up=False)

    asyncio.run(run())


def test_sdk_contract_contains_closed_relationship_and_control_fields():
    schema = AgentOutputSchema(RouterAgentOutput).json_schema()
    assert set(schema["properties"]["policy_relationship"]["enum"]) == {
        "new",
        "existing",
        "not_applicable",
        "unknown",
    }
    assert "no_more_questions" in schema["properties"]["conversation_signal"]["enum"]
    assert "relationship_needed" in schema["required"]


def test_empty_selection_is_only_valid_for_control_in_authorized_context():
    with pytest.raises(ValidationError):
        RouterDecision(language="ru", scenarios=[])
    with pytest.raises(ValidationError):
        RouterDecision(
            language="ru",
            scenarios=[],
            conversation_signal="acknowledgement",
            slots={"city": "Almaty"},
        )
    router = build_services(Settings(_env_file=None)).insurance.processor.router
    routed = decision(signal="acknowledgement")
    fresh = DialogState(session_id="control", conversation=ConversationState())
    with pytest.raises(RouterOutputError):
        router._validate_decision(routed, fresh)
    fresh.conversation.phase = "wrap_up"
    router._validate_decision(routed, fresh)
    fresh.active_scenario = "SC25"
    with pytest.raises(RouterOutputError):
        router._validate_decision(routed, fresh)
    fresh.conversation.phase = "collect"
    fresh.conversation.resume_after_risk = True
    router._validate_decision(routed, fresh)


def test_legacy_model_selection_is_removed_atomically_from_understood_control():
    routed = RouterDecision(
        language="ru",
        conversation_signal="acknowledgement",
        scenarios=[dict(scenario_id="SYS_UNCLEAR", confidence=0.9, reason="Acknowledgement")],
        segments=[
            dict(scenario_id="SYS_UNCLEAR", confidence=0.9, reason="Acknowledgement", text="Хорошо")
        ],
    )
    built, _ = build(routed)
    previous = DialogState(session_id="atomic", conversation=ConversationState(phase="wrap_up"))
    state, decision_out, trace, *_ = asyncio.run(
        built.insurance.processor.process(previous, "Хорошо")
    )
    assert not decision_out.scenarios and not decision_out.segments and not trace.scenarios
    assert not trace.clarification and state.conversation.phase == "wrap_up"


def test_composer_understood_relationship_blocks_binary_even_if_router_left_unknown():
    built, _ = build(decision(relationship_needed=True))
    composer = ConversationComposer(None)
    composer.agent.run = AsyncMock(
        return_value=ComposedReply(
            conversation_act="ask_followup",
            acknowledgement="",
            question="Новый полис или существующий?",
            expected_answer_type="choice",
            acknowledged_information=["existing_policy"],
        )
    )
    built.insurance.processor.composer = composer
    turn = asyncio.run(built.messages.process("known", "Менде полис бар"))
    assert_metrics(turn, relationship="existing")
    assert turn.trace.composer_error == "composer_unnecessary_policy_classification"
