"""Deterministic boundary/progression regressions; not live dialogue-quality scores."""

import asyncio
import json
from collections import deque
from unittest.mock import AsyncMock

import pytest

from app.agent.errors import RouterProviderError
from app.core.config import Settings
from app.core.services import build_services
from app.packs.insurance_manager.agent.schemas import RouterDecision
from app.packs.insurance_manager.composer import (
    ComposedReply,
    ConversationComposer,
    normalized_question,
    validate_composition,
)
from app.packs.insurance_manager.expected_answers import expected_identifier, expected_trip_duration
from app.packs.insurance_manager.privacy import redact_text, safe_slots
from app.packs.insurance_manager.processor import reply_language_for_turn
from app.packs.insurance_manager.state import ConversationState, DialogState


class RouterFixture:
    def __init__(self, *decisions):
        self.decisions = deque(decisions)
        self.calls = []

    async def route(self, text, state):
        self.calls.append(state)
        return self.decisions.popleft()


def decision(sid="SYS_UNCLEAR", signal="none", slots=None, continuation=False, confidence=0.9):
    return RouterDecision(
        language="ru",
        response_language="ru",
        conversation_signal=signal,
        scenarios=[dict(scenario_id=sid, confidence=confidence, reason="Offline fixture")],
        slots=slots or {},
        is_continuation=continuation,
    )


def services(router, outputs):
    built = build_services(Settings(_env_file=None), router_override=router)
    composer = ConversationComposer(None)
    composer.agent.run = AsyncMock(side_effect=outputs)
    built.insurance.processor.composer = composer
    return built


def follow(question, info=()):
    return ComposedReply(
        conversation_act="ask_followup",
        acknowledgement="Понял.",
        question=question,
        acknowledged_information=list(info),
        expected_answer_type="problem_description",
    )


def test_real_bad_journey_has_no_repeat_handoff_or_comprehension_failure_on_progress():
    router = RouterFixture(
        decision(signal="greeting"),
        decision(),
        decision(signal="partial_answer"),
        decision(signal="partial_answer"),
    )
    built = services(
        router,
        [
            ComposedReply(
                conversation_act="greet",
                acknowledgement="Здравствуйте!",
                question="Как могу помочь со страховкой?",
                expected_answer_type="problem_description",
            ),
            follow("Новый полис или действующий?"),
            follow("Что хотите сделать с действующим полисом?", ["existing_policy"]),
            follow("Нужны документы, изменение данных или что-то другое?", ["existing_policy"]),
        ],
    )

    async def run():
        opened = await built.messages.process("bad", "", "insurance_manager", start_scenario=True)
        assert router.calls == []
        assert [t.role for t in opened.state.history] == ["assistant"]
        questions = []
        for text in [
            "здравствуйте",
            "У меня проблема с полисом",
            "разобраться с существующим",
            "у меня уже есть полис",
        ]:
            turn = await built.messages.process("bad", text)
            assert turn.conversation_status == "awaiting_user"
            question = normalized_question(turn.state.conversation.last_question)
            assert question not in questions[-1:]
            questions.append(question)
        assert turn.state.conversation.repair_attempts == 0
        assert turn.state.unclear_count == turn.state.consecutive_low_confidence == 0
        assert "existing_policy" in turn.state.conversation.acknowledged_information

    asyncio.run(run())


@pytest.mark.parametrize(
    "slot,value",
    [
        ("phone", "+77010000001"),
        ("iin", "850314300121"),
        ("policy_number", "SQ-OGPO-104501"),
        ("claim_number", "CL-500198"),
    ],
)
def test_valid_expected_identifier_is_progress_even_at_low_confidence(slot, value):
    built = build_services(Settings(_env_file=None), router_override=RouterFixture())
    state = DialogState(
        session_id="id",
        active_scenario="SC25",
        unclear_count=2,
        consecutive_low_confidence=1,
        conversation=ConversationState(
            expected_slot=slot, expected_answer_type="slot", repair_attempts=2
        ),
    )
    routed = decision("SC25", slots={slot: value}, continuation=True, confidence=0.2)
    policy = built.policy.decide(routed, state)
    assert policy.outcome == "continue"
    updated = built.insurance.processor._transition(state, routed, policy)
    assert updated.slots[slot] == value
    assert updated.unclear_count == updated.consecutive_low_confidence == 0
    assert updated.conversation.repair_attempts == 0


@pytest.mark.parametrize("failure", [RouterProviderError(), ValueError("invalid_composition")])
def test_composer_failure_preserves_slots_and_state_without_fake_handoff(failure):
    router = RouterFixture(decision("SC36", slots={"phone": "+77010000001"}))
    built = services(router, [failure])
    turn = asyncio.run(built.messages.process("failure", "Номер для обратного звонка"))
    stored = built.dialogs.get_conversation("failure").scenario_contexts["insurance_manager"].state
    assert stored.slots["phone"] == "+77010000001"
    assert turn.conversation_status == "awaiting_user"
    assert turn.trace.composer_error
    assert turn.trace.expected_slot == "callback_time"
    assert "+77010000001" not in json.dumps(turn.model_dump(), ensure_ascii=False)


def test_explicit_operator_bypasses_composer_and_keeps_exact_friendly_phrase():
    built = services(RouterFixture(decision("SC37")), [])
    turn = asyncio.run(built.messages.process("operator", "Соедините меня с оператором"))
    assert turn.response_text == "Конечно, передаю диалог оператору."
    assert turn.conversation_status == "handoff"
    built.insurance.processor.composer.agent.run.assert_not_awaited()


@pytest.mark.parametrize("text", ["Цена 100 тенге.", "Платёж прошёл.", "Полис оформлен."])
def test_free_composer_wording_cannot_add_facts_or_success(text):
    with pytest.raises(ValueError, match="unsupported_composer_claim"):
        validate_composition(
            ComposedReply(conversation_act="answer", acknowledgement=text),
            {"allowed_action": "answer", "conversation": {"last_question": None}},
        )


def test_grounded_fact_block_survives_composer_wording_and_payload_has_no_identifiers():
    router = RouterFixture(decision("SC32", slots={"iin": "850314300121"}))
    built = services(
        router, [ComposedReply(conversation_act="answer", acknowledgement="Проверил.")]
    )
    turn = asyncio.run(built.messages.process("facts", "850314300121"))
    payload = built.insurance.processor.composer.agent.run.call_args.args[0]
    assert payload["grounded_facts"] in turn.response_text
    assert "850314300121" not in json.dumps(payload, ensure_ascii=False)
    assert "850314300121" not in json.dumps(turn.trace.model_dump(), ensure_ascii=False)
    assert turn.trace.source_keys == ["mock_backend.clients", "mock_backend.defaults"]


def test_rejected_question_preserves_understood_goal_and_resets_repairs():
    router = RouterFixture(decision(), decision())
    built = services(
        router,
        [
            follow("Нужен новый полис или помощь с действующим?"),
            ComposedReply(
                conversation_act="ask_followup",
                acknowledgement="Понял.",
                question="Что произошло? Какой результат нужен?",
                acknowledged_information=["existing_policy"],
                expected_answer_type="problem_description",
            ),
        ],
    )

    async def run():
        await built.messages.process("retained-goal", "Нужна помощь со страховкой")
        return await built.messages.process("retained-goal", "По действующему")

    turn = asyncio.run(run())
    assert turn.trace.composer_error == "composer_one_question_required"
    assert turn.state.conversation.acknowledged_information == ["existing_policy"]
    assert turn.state.conversation.repair_attempts == turn.state.unclear_count == 0
    assert turn.state.consecutive_low_confidence == 0
    assert turn.conversation_status == "awaiting_user"
    assert turn.trace.actions == []
    assert "Что произошло? Какой результат нужен?" not in turn.response_text
    assert turn.state.conversation.expected_answer_type == "problem_description"


def test_nonexplicit_handoff_requires_distinct_prior_repairs_and_no_progress():
    built = build_services(Settings(_env_file=None), router_override=RouterFixture())
    state = DialogState(
        session_id="repairs",
        conversation=ConversationState(repair_attempts=1),
        consecutive_low_confidence=1,
        unclear_count=1,
    )
    assert built.policy.decide(decision(confidence=0.2), state).outcome == "clarify"
    state.conversation.repair_attempts = 2
    state.unclear_count = 2
    assert built.policy.decide(decision(confidence=0.2), state).outcome == "handoff"
    state.conversation.expected_answer_type = "choice"
    assert (
        built.policy.decide(decision(signal="partial_answer", confidence=0.2), state).outcome
        == "clarify"
    )


@pytest.mark.parametrize("value", ["SQ-OGPO-100231", "sq-ogpo-100231", "CL-500198", "cl-500198"])
def test_policy_and_claim_redaction_preserves_privacy_across_case_normalization(value):
    assert value not in redact_text(f"Проверьте {value}")
    assert value not in redact_text(f"Проверьте {value}", {"policy_number": value.upper()})


@pytest.mark.parametrize("field", ["new_driver_iin", "new_value"])
def test_changed_identity_or_contact_value_stays_private(field):
    assert safe_slots({field: "850314300121"}) == {field: "[получено]"}
    assert "850314300121" not in redact_text("ИИН 850314300121", {field: "850314300121"})


@pytest.mark.parametrize(
    "name,text,value",
    [
        ("phone", "87010000001", "+77010000001"),
        ("phone", "+7 (701) 000-00-01", "+77010000001"),
        ("phone", "Восемь семь ноль один ноль ноль ноль ноль ноль ноль один", "+77010000001"),
        ("phone", "Сегіз жеті нөл бір нөл нөл нөл нөл нөл нөл бір", "+77010000001"),
        ("iin", "850314300121", "850314300121"),
        ("iin", "001234567890", "001234567890"),
        ("iin", "Восемь пять ноль три один четыре три ноль ноль один два один", "850314300121"),
        ("policy_number", "sq-ogpo-104501", "SQ-OGPO-104501"),
        ("claim_number", "CL-500198", "CL-500198"),
    ],
)
def test_numeric_and_spoken_expected_identifiers_use_source_patterns(name, text, value):
    built = build_services(Settings(_env_file=None), router_override=RouterFixture())
    state = DialogState(session_id="format", conversation=ConversationState(expected_slot=name))
    assert expected_identifier(text, state, built.insurance.processor.replies.slots) == (
        name,
        value,
    )


@pytest.mark.parametrize("text", ["123", "87010000001 и 87010000002", "один два три", "2026-10-02"])
def test_partial_or_ambiguous_identifier_is_not_guessed(text):
    built = build_services(Settings(_env_file=None), router_override=RouterFixture())
    state = DialogState(session_id="format", conversation=ConversationState(expected_slot="phone"))
    assert expected_identifier(text, state, built.insurance.processor.replies.slots) is None


@pytest.mark.parametrize(
    "text,days", [("На две недели", 14), ("Екі аптаға", 14), ("14 дней", 14), ("0 дней", None)]
)
def test_literal_duration_only_applies_to_authorized_travel_date_collection(text, days):
    state = DialogState(
        session_id="duration",
        active_scenario="SC06",
        conversation=ConversationState(expected_slot="trip_start"),
    )
    assert expected_trip_duration(text, state) == days
    state.active_scenario = "SC36"
    assert expected_trip_duration(text, state) is None


def test_duration_survives_until_start_date_and_determines_inclusive_end_date():
    router = RouterFixture(
        decision("SC06", slots={"trip_country": "Турция"}),
        decision(
            "SC06",
            signal="partial_answer",
            continuation=True,
            slots={"trip_start": "2026-10-01", "trip_end": "2026-10-15"},
        ),
        decision("SC06", slots={"trip_start": "2026-10-10"}, continuation=True),
        decision("SC06", slots={"trip_end": "2026-10-25"}, continuation=True),
    )
    built = services(
        router,
        [
            ComposedReply(conversation_act="ask_slot", acknowledgement="", question=question)
            for question in [
                "Когда выезжаете?",
                "Какого числа вылет?",
                "Сколько человек едет?",
                "Сколько участников?",
            ]
        ],
    )

    async def run():
        await built.messages.process("duration-flow", "Нужна страховка для поездки")
        await built.messages.process("duration-flow", "На две недели")
        third = await built.messages.process("duration-flow", "Десятого октября")
        corrected = await built.messages.process("duration-flow", "Обратно двадцать пятого октября")
        return third, corrected

    turn, corrected = asyncio.run(run())
    assert turn.state.slots["trip_start"] == "2026-10-10"
    assert turn.state.slots["trip_end"] == "2026-10-23"
    assert turn.state.conversation.travel_duration_days == 14
    assert turn.state.conversation.expected_slot == "travelers_count"
    assert turn.state.conversation.repair_attempts == 0
    assert turn.conversation_status == "awaiting_user"
    assert corrected.state.slots["trip_end"] == "2026-10-25"
    assert corrected.state.conversation.travel_duration_days is None


def test_clear_short_russian_answer_overrides_a_stale_mixed_reply_preference():
    routed = decision()
    routed.language = "mixed"
    routed.response_language = "kk"
    assert reply_language_for_turn("Мне удобно завтра утром", routed) == "ru"
