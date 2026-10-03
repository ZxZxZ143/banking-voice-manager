"""Synthetic identifiers only: regressions for monotonic Insurance identification."""

import asyncio
import json
import os
from collections import deque

import pytest

from app.core.config import Settings
from app.core.services import build_services
from app.packs.insurance_manager.agent.schemas import IdentifierAnswer, RouterDecision
from app.packs.insurance_manager.composer import ComposedReply, validate_composition
from app.packs.insurance_manager.data.demo_profile import normalize_phone
from app.packs.insurance_manager.state import ConversationState, DialogState

SCREENSHOT_PHONE = os.environ.get("INSURANCE_REGRESSION_PHONE", "87770001234")


class SameScenarioRouter:
    async def route(self, text, state):
        return RouterDecision(
            language="ru", scenarios=[dict(scenario_id="SC27", confidence=0.95, reason="Fixture")]
        )


class FallbackComposer:
    async def compose(self, payload):
        raise ValueError("offline_composer")


def test_screenshot_phone_alternative_advances_instead_of_asking_policy_again():
    built = build_services(Settings(_env_file=None), router_override=SameScenarioRouter())
    built.insurance.processor.composer = FallbackComposer()

    async def run():
        first = await built.messages.process("screenshot", "Хочу продлить мой полис")
        assert first.trace.expected_slot == "policy_number"
        second = await built.messages.process("screenshot", SCREENSHOT_PHONE)
        assert second.trace.expected_slot == "iin"
        assert second.trace.actions == ["find_client"]

    asyncio.run(run())


def routed(sid="SC27", *, status=None, field=None, slots=None, language="ru", confidence=0.95):
    return RouterDecision(
        language=language,
        response_language=language,
        scenarios=[dict(scenario_id=sid, confidence=confidence, reason="Synthetic regression")],
        slots=slots or {},
        identifier_answer=IdentifierAnswer(status=status, field=field) if status else None,
    )


class ScriptedRouter:
    def __init__(self, decisions):
        self.decisions = deque(decisions)

    async def route(self, text, state):
        return self.decisions.popleft()


def build(*decisions, demo=False):
    built = build_services(
        Settings(_env_file=None, demo_test_phone="87075551234" if demo else None),
        router_override=ScriptedRouter(decisions),
    )
    built.insurance.processor.composer = FallbackComposer()
    return built


def private(built, session):
    return built.dialogs.get_conversation(session).scenario_contexts["insurance_manager"].state


def test_full_screenshot_flow_terminates_before_unsupported_plate_and_retains_context():
    from app.conversation.service import SessionClosedError

    built = build(
        routed(),
        routed("SYS_UNCLEAR", confidence=0.2),
        routed(status="unavailable", field="policy_number"),
        routed("SYS_UNCLEAR", confidence=0.2),
    )

    async def run():
        replies = []
        for text in [
            "Хочу продлить мой полис",
            SCREENSHOT_PHONE,
            "У меня его нет, можно его проверить по номеру телефона?",
            "000000000000",
        ]:
            replies.append(await built.messages.process("screenshot-full", text))
        assert [r.trace.expected_slot for r in replies] == ["policy_number", "iin", "iin", None]
        last = replies[-1]
        assert last.conversation_status == "handoff"
        assert last.trace.manager_summary["reason"] == "lookup_exhausted"
        assert last.trace.manager_summary["business_problem"] == "renewal"
        assert last.trace.manager_summary["collected_fields"] == ["iin", "phone"]
        assert last.trace.manager_summary["unavailable_fields"] == ["policy_number"]
        assert last.trace.manager_summary["failed_lookup_fields"] == ["phone", "iin"]
        assert last.trace.manager_summary["next_required_action"] == "operator_review"
        assert last.trace.repair_attempts == 0
        assert last.state.unclear_count == last.state.consecutive_low_confidence == 0
        saved = private(built, "screenshot-full").model_dump()
        for late in ["У меня нет его под рукой.", "945ABC02"]:
            with pytest.raises(SessionClosedError):
                await built.messages.process("screenshot-full", late)
        assert private(built, "screenshot-full").model_dump() == saved
        assert saved["active_scenario"] == "SC27"
        assert saved["identification"]["provided_values"]["phone"] == [
            normalize_phone(SCREENSHOT_PHONE)
        ]
        assert saved["manager_summary"]["reason"] == "lookup_exhausted"
        assert any(t["role"] == "user" for t in saved["history"])
        public = json.dumps(last.model_dump(), ensure_ascii=False)
        assert all(
            value not in public for value in ["7770001234", "000000000000", "failed_attempts"]
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "language,unavailable",
    [
        ("ru", "У меня его нет"),
        ("ru", "Не помню номер"),
        ("ru", "Нет под рукой"),
        ("kk", "Менде ол жоқ"),
        ("kk", "Нөмірін білмеймін"),
    ],
)
def test_unavailability_resets_counters_and_survives_five_turns_then_voluntary_recovery(
    language,
    unavailable,
):
    built = build(
        routed("SC04", language=language),
        routed("SYS_UNCLEAR", language=language, confidence=0.1),
        *[routed("SYS_OUT_OF_SCOPE", language=language) for _ in range(5)],
        routed("SC04", language=language),
        demo=True,
    )

    async def run():
        await built.messages.process("recover", "Добавить водителя")
        result = await built.messages.process("recover", unavailable)
        assert result.trace.expected_slot == "phone"
        for _ in range(5):
            result = await built.messages.process("recover", "Вы виртуальный помощник?")
            assert result.trace.expected_slot == "phone"
            assert "policy_number" in private(built, "recover").identification.unavailable_fields
        result = await built.messages.process("recover", "Нашёл номер полиса: SQ-OGPO-990001")
        assert "policy_number" not in private(built, "recover").identification.unavailable_fields
        assert result.trace.expected_slot == "new_driver_iin"
        assert private(built, "recover").slots["policy_number"] == "SQ-OGPO-990001"
        assert result.trace.repair_attempts == result.state.unclear_count == 0

    asyncio.run(run())


@pytest.mark.parametrize("phone", ["87770001234", "+77770001234", "77770001234"])
def test_alternative_phone_normalizes_without_repeating_failed_value_then_correction(phone):
    built = build(*[routed("SC25") for _ in range(8)], demo=True)

    async def run():
        result = await built.messages.process("correct", phone)
        assert result.trace.expected_slot == "iin"
        for _ in range(5):
            result = await built.messages.process("correct", phone)
            assert "find_client" not in result.trace.actions
            assert result.trace.expected_slot == "iin"
        result = await built.messages.process("correct", "Исправляю телефон: 87075551234")
        assert result.trace.completed_scenario == "SC25"
        memory = private(built, "correct").identification
        assert memory.successful_field == "phone"
        assert len(memory.failed_attempts) == 1
        assert len(memory.provided_values["phone"]) == 2

    asyncio.run(run())


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_multiple_policies_and_unavailable_number_end_with_owned_safe_handoff(language):
    built = build(
        routed("SC25", slots={"phone": "+77010000001"}, language=language),
        routed("SC25", status="unavailable", field="policy_number", language=language),
    )

    async def run():
        first = await built.messages.process("multiple", "Проверьте полис")
        assert first.trace.expected_slot == "policy_number"
        last = await built.messages.process("multiple", "Номер недоступен")
        assert last.conversation_status == "handoff"
        assert last.trace.actions == []  # same automatic record lookup is never retried
        assert last.trace.manager_summary["known_client"]
        assert "SQ-" not in last.response_text
        assert last.trace.expected_slot is None
        assert ("демонстрации" if language == "ru" else "демонстрацияда") in last.response_text

    asyncio.run(run())


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_unavailable_claim_number_then_phone_resolves_single_owned_claim(language):
    built = build(
        routed("SC17", language=language),
        routed("SC17", status="unavailable", field="claim_number", language=language),
        routed("SC17", language=language),
        demo=True,
    )

    async def run():
        await built.messages.process("claim", "Проверить статус заявления")
        result = await built.messages.process("claim", "Номер заявления недоступен")
        assert result.trace.expected_slot == "phone"
        result = await built.messages.process("claim", "87075551234")
        assert result.trace.completed_scenario == "SC17"
        assert result.trace.actions == ["find_client", "get_claim"]
        assert result.conversation_status == "active"

    asyncio.run(run())


@pytest.mark.parametrize("sid", ["SC25", "SC27", "SC17", "SC19", "SC30"])
def test_all_unavailable_is_bounded_and_plate_never_authorizes_disclosure(sid):
    built = build()
    state = DialogState(
        session_id="bounded",
        active_scenario=sid,
        conversation=ConversationState(expected_slot="phone", expected_answer_type="slot"),
    )
    state.identification.unavailable_fields = ["phone", "iin", "policy_number", "claim_number"]
    state.slots["vehicle_plate"] = "945ABC02"
    from app.packs.insurance_manager.scenarios.decision_policy import PolicyResult

    result = built.insurance.processor.replies.generate_result(
        state,
        PolicyResult(
            outcome="continue", scenario_ids=[sid], consecutive_low_confidence=0, reason="Test"
        ),
    )
    assert result.handoff and result.identification.exhausted
    assert result.expected_slot is None
    assert result.actions == []
    assert result.manager_summary.reason == "lookup_exhausted"
    assert "945ABC02" not in result.model_dump_json()


def test_composer_rejects_backtracking_to_policy_instead_of_authorized_iin():
    with pytest.raises(ValueError, match="unexpected_collection_target"):
        validate_composition(
            ComposedReply(
                conversation_act="ask_slot", acknowledgement="", question="Номер полиса?"
            ),
            {
                "allowed_action": "ask_slot",
                "next_slot": "iin",
                "conversation": {"last_question": "Телефон?"},
            },
        )


def test_suspended_scenario_keeps_failed_lookup_on_return_and_handoff():
    built = build(
        routed("SC27"),
        routed("SC27"),
        routed("SC33", slots={"city": "Almaty"}),
        routed("SC27", status="unavailable", field="iin"),
    )

    async def run():
        await built.messages.process("resume", "Продлить полис")
        await built.messages.process("resume", "87770001234")
        await built.messages.process("resume", "Где офис в Алматы?")
        saved = private(built, "resume")
        assert saved.active_scenario == "SC27"
        assert saved.identification.failed_fields == ["phone"]
        result = await built.messages.process("resume", "ИИН не знаю")
        assert result.conversation_status == "handoff"
        assert "find_client" not in result.trace.actions
        assert result.trace.manager_summary["scenario"] == "SC27"
        assert result.trace.manager_summary["business_problem"] == "renewal"

    asyncio.run(run())


def test_private_lookup_values_never_enter_provider_memory_public_state_or_analytics():
    from app.packs.insurance_manager.agent.prompts import build_router_input

    built = build(routed(), routed(), routed(status="unavailable", field="iin"))

    async def run():
        await built.messages.process("privacy", "Продлить полис")
        await built.messages.process("privacy", "87770001234")
        result = await built.messages.process("privacy", "ИИН недоступен")
        saved = private(built, "privacy")
        payload = build_router_input(
            "Продолжим", saved.to_dialog(built.dialogs.get_conversation("privacy").global_context)
        )
        assert "provided_values" not in payload and "failed_attempts" not in payload
        assert "7770001234" not in payload
        assert "7770001234" not in result.model_dump_json()
        # Persistence uses the unchanged safe EventStore contract, never pack snapshots.
        import sqlite3

        with sqlite3.connect(os.environ["EVENT_DB_PATH"]) as connection:
            serialized = repr(connection.execute("SELECT * FROM events").fetchall())
        assert all(
            word not in serialized
            for word in (
                "7770001234",
                "provided_values",
                "failed_attempts",
                "ИИН недоступен",
            )
        )

    asyncio.run(run())


def test_free_composer_pronoun_cannot_reopen_the_previous_identifier_question():
    class MisleadingComposer:
        async def compose(self, payload):
            return ComposedReply(
                conversation_act="ask_slot",
                acknowledgement="Назовите старый документ.",
                question="Можете снова продиктовать тот номер?",
                expected_answer_type="slot",
            )

    built = build(routed(), routed())
    built.insurance.processor.composer = MisleadingComposer()

    async def run():
        await built.messages.process("wording", "Продление")
        result = await built.messages.process("wording", "87770001234")
        assert result.trace.expected_slot == "iin"
        assert "ИИН" in result.response_text
        assert "тот номер" not in result.response_text
        assert "старый документ" not in result.response_text

    asyncio.run(run())
