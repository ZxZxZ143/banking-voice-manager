"""Stage 3.2 behavior boundaries; every identifier here is a synthetic fixture."""

import asyncio
import json
from collections import deque

import pytest

from app.core.config import Settings
from app.core.services import build_services
from app.packs.insurance_manager.agent.prompts import build_router_input
from app.packs.insurance_manager.agent.schemas import RouterDecision
from app.packs.insurance_manager.composer import (
    ComposedReply,
    fallback_composition,
    optional_acknowledgement,
    validate_composition,
)
from app.packs.insurance_manager.data.demo_profile import normalize_phone, with_demo_profile
from app.packs.insurance_manager.state import DialogState, DialogTurn


class RouterFixture:
    def __init__(self, *items):
        self.items = deque(items)

    async def route(self, text, state):
        return self.items.popleft()


class FallbackComposer:
    async def compose(self, payload):
        from app.packs.insurance_manager.response.routing import RoutingReplyResult

        return fallback_composition(payload, RoutingReplyResult(text="Назовите нужные данные."))


def decision(sid, slots=None, scope="none"):
    return RouterDecision(
        language="ru",
        response_language="ru",
        scope_kind=scope,
        scenarios=[dict(scenario_id=sid, confidence=0.95, reason="Fixture")],
        slots=slots or {},
    )


def build(*items, demo=False):
    config = Settings(_env_file=None, demo_test_phone="87075551234" if demo else None)
    built = build_services(config, router_override=RouterFixture(*items))
    built.insurance.processor.composer = FallbackComposer()
    return built


@pytest.mark.parametrize(
    "phone",
    [
        "+77075551234",
        "77075551234",
        "87075551234",
        "8 707 555 12 34",
        "+7 707 555 12 34",
        "7075551234",
        "707 555 12 34",
    ],
)
def test_phone_normalization_and_overlay_lookup_no_format_loop(phone):
    built = build(decision("SC25"), decision("SYS_UNCLEAR"), demo=True)

    async def flow():
        first = await built.messages.process("phone", "Проверьте мой полис")
        assert first.state.conversation.expected_slot == "phone"
        second = await built.messages.process("phone", phone)
        private = (
            built.dialogs.get_conversation("phone").scenario_contexts["insurance_manager"].state
        )
        assert private.slots["phone"] == "+77075551234"
        assert second.trace.completed_scenario == "SC25"
        assert second.conversation_status == "active"
        assert second.state.conversation.expected_slot is None
        assert "формат" not in second.response_text
        assert "77075551234" not in json.dumps(second.trace.model_dump())

    asyncio.run(flow())


def test_unknown_identifiers_one_alternative_then_useful_context_and_handoff():
    built = build(
        decision("SC25", {"phone": "+77075551234"}),
        decision("SC25", {"iin": "000101300000"}),
        decision("SC25", {"policy_number": "SQ-OGPO-990001"}),
    )

    async def flow():
        first = await built.messages.process("unknown", "Проверка")
        assert first.state.conversation.expected_slot == "iin"
        second = await built.messages.process("unknown", "ИИН")
        assert second.state.conversation.expected_slot == "policy_number"
        third = await built.messages.process("unknown", "Номер полиса")
        assert third.conversation_status == "handoff"
        assert third.trace.manager_summary["reason"] == "client_not_found"
        assert third.trace.manager_summary["completed_read_only_checks"] == []
        assert third.trace.manager_summary["known_client"] is False
        assert third.state.client_lookup_attempts == ["phone", "iin"]

    asyncio.run(flow())


def test_unknown_alternative_does_not_erase_payment_context_or_repeat_phone():
    built = build(
        decision("SC30", {"phone": "+77075551234", "payment_date": "2026-10-01"}),
        decision("SC30", {"iin": "000101300000"}),
    )

    async def flow():
        first = await built.messages.process("pay", "Оплата")
        assert first.state.conversation.expected_slot == "iin"
        second = await built.messages.process("pay", "ИИН")
        assert second.conversation_status == "handoff"
        assert second.state.slots["payment_date"] == "2026-10-01"

    asyncio.run(flow())


@pytest.mark.parametrize("kind", ["small_talk", "identity", "banking", "unrelated"])
def test_scope_turn_preserves_expected_field_and_never_calls_selector(kind):
    built = build(
        decision("SC30", {"payment_date": "2026-10-01"}), decision("SYS_OUT_OF_SCOPE", scope=kind)
    )

    class ForbiddenSelector:
        async def select(self, *args):
            pytest.fail("Automatic switching is disabled")

    built.messages.selector = ForbiddenSelector()

    async def flow():
        await built.messages.process("scope", "Оплата")
        turn = await built.messages.process("scope", "Отступление")
        assert turn.scenario_pack_id == "insurance_manager"
        assert turn.state.active_scenario == "SC30"
        assert turn.state.conversation.expected_slot == "phone"
        assert turn.state.slots["payment_date"] == "2026-10-01"
        assert turn.trace.pack_switch is None
        assert "Product Promoter" not in turn.response_text
        if kind == "identity":
            assert "виртуальный" in turn.response_text

    asyncio.run(flow())


def test_payment_and_policy_change_summary_contains_only_real_checks():
    built = build(
        decision("SC30", {"phone": "+77075551234", "payment_date": "2026-10-01"}), demo=True
    )
    result = asyncio.run(built.messages.process("payment", "Платёж"))
    assert result.conversation_status == "handoff"
    assert result.trace.manager_summary["known_client"]
    assert result.trace.manager_summary["completed_read_only_checks"] == [
        "find_client",
        "check_payment",
    ]
    built = build(
        decision(
            "SC04",
            {
                "phone": "+77075551234",
                "policy_number": "SQ-OGPO-990001",
                "new_driver_iin": "000101300000",
            },
        ),
        demo=True,
    )
    result = asyncio.run(built.messages.process("driver", "Добавить водителя"))
    assert result.conversation_status == "handoff"
    assert result.trace.manager_summary["next_required_action"] == "update_policy"
    assert result.trace.manager_summary["completed_read_only_checks"] == [
        "find_client",
        "get_policy",
        "get_bm_class",
    ]
    assert "update_policy" not in result.trace.actions


def test_overlay_optional_and_does_not_modify_canonical():
    kit = build().kit
    before = kit.mock_backend.model_dump()
    effective = with_demo_profile(kit.mock_backend, "87075551234")
    assert len(effective.clients) == len(kit.mock_backend.clients) + 1
    assert kit.mock_backend.model_dump() == before
    assert with_demo_profile(kit.mock_backend, None).model_dump() == before
    with pytest.raises(ValueError):
        normalize_phone("123")


@pytest.mark.parametrize(
    "reaction", ["Понял.", "Спасибо.", "Понял, спасибо.", "Спасибо, продолжим.", "Хорошо."]
)
def test_low_value_acknowledgements_are_optional(reaction):
    assert optional_acknowledgement(reaction, "") == ""
    assert optional_acknowledgement("Спасибо, записал уточнение.", "Спасибо за сведения.") == ""


def test_local_phone_never_enters_router_provider_payload():
    state = DialogState(
        session_id="private",
        slots={"phone": "+77075551234"},
        scenario_slots={"SC30": {"phone": "87075551234"}},
        history=[DialogTurn(role="user", text="Телефон 8 707 555 12 34")],
    )
    payload = build_router_input("Мой номер +7 707 555 12 34", state, local_phone="+77075551234")
    assert "77075551234" not in payload and "87075551234" not in payload
    assert "707 555" not in payload
    assert payload.count("[локальный телефон получен]") == 4
    assert state.slots["phone"] == "+77075551234"


@pytest.mark.parametrize("phone", ["7075551234", "707 555 12 34"])
def test_phone_without_country_code_is_hidden_from_provider(phone):
    payload = build_router_input(phone, DialogState(session_id="national"))
    assert "7075551234" not in payload and "707 555" not in payload
    assert "[локальный телефон получен]" in payload


@pytest.mark.parametrize("variant", ["default", "policy_end_date", "policy_period"])
def test_policy_answer_uses_only_offered_facts_without_extra_question(variant):
    built = build(decision("SC25", {"iin": "000101300000"}), demo=True)

    class PolicyComposer:
        async def compose(self, payload):
            result = ComposedReply(
                conversation_act="answer",
                acknowledgement="Понял.",
                question="Могу помочь ещё?",
                fact_variant=variant,
            )
            validate_composition(result, payload)
            return result

    built.insurance.processor.composer = PolicyComposer()
    turn = asyncio.run(built.messages.process("policy", "Проверка полиса"))
    assert turn.trace.completed_scenario == "SC25"
    assert turn.trace.expected_slot is None
    assert "?" not in turn.response_text and "[номер скрыт]" not in turn.response_text
    assert "2026-10-01" not in turn.response_text
    if variant == "default":
        assert turn.response_text == "Сейчас ваш полис действует."
    else:
        assert "31 декабря 2026 года" in turn.response_text
        assert "990001" not in turn.response_text


def test_composer_cannot_select_unavailable_policy_fact_variant():
    with pytest.raises(ValueError, match="unsupported_fact_variant"):
        validate_composition(
            ComposedReply(
                conversation_act="answer", acknowledgement="", fact_variant="policy_end_date"
            ),
            {"allowed_action": "answer", "grounded_variants": {}},
        )


@pytest.mark.parametrize(
    "sid,guidance", [("SC15", "сначала свяжитесь"), ("SC38", "Никому не сообщайте СМС-коды")]
)
def test_existing_urgent_guidance_is_spoken_before_collecting_missing_fields(sid, guidance):
    built = build(decision(sid))
    turn = asyncio.run(built.messages.process("urgent", "Нужна помощь"))
    assert guidance in turn.response_text
    assert turn.trace.expected_slot is not None
    assert turn.conversation_status not in {"handoff", "ended"}
