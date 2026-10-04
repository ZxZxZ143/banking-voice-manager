import asyncio
import json

import pytest
from test_structured_precision import build, submit

from app.speech.structured.correction import apply_correction, parse_confirmation


@pytest.mark.parametrize("text", ["Нет. Вместо A B.", "вместо семёрки восемь", "замените C D"])
def test_spoken_replacement_does_not_require_asr_punctuation(text):
    kind = "phone" if "сем" in text else "vehicle_plate"
    value = "+77015232862" if kind == "phone" else "945ABC02"
    edit = parse_confirmation(text, kind).correction
    # Repeated sevens must still fail closed, even with syntactically clear edit.
    assert apply_correction(value, kind, edit) == (
        None if kind == "phone" else "945BBC02" if "A" in text else "945ABD02"
    )


@pytest.mark.parametrize(
    "kind,value,text,expected",
    [
        ("vehicle_plate", "945ABC02", "Нет, вместо C — D", "945ABD02"),
        ("vehicle_plate", "945ABC02", "Не B, а D", "945ADC02"),
        ("vehicle_plate", "943ABC02", "Там не три, а семь", "947ABC02"),
        ("phone", "+77775232862", "Последняя цифра три", "+77775232863"),
        ("vehicle_plate", "945ABD02", "Вторая буква C", "945ACD02"),
        ("vehicle_plate", "945ABC02", "Первая буква не A, а B", "945BBC02"),
        ("vehicle_plate", "945ABC01", "Регион не ноль один, а ноль два", "945ABC02"),
        ("phone", "+77775232862", "Всё правильно, только последняя цифра семь", "+77775232867"),
        ("vehicle_plate", "945ADC02", "Правильно всё кроме второй буквы — B", "945ABC02"),
        ("vehicle_plate", "945ADC02", "Нет, вы сказали C, там B", "945ADB02"),
        ("policy_number", "SQ-OGPO-123456", "Нет, пятая цифра не пять, а девять", "SQ-OGPO-123496"),
        ("vehicle_plate", "945ABC02", "Жоқ, C орнына D", "945ABD02"),
        ("vehicle_plate", "945ABC02", "Бірінші әріп A емес B", "945BBC02"),
        ("phone", "+77775232862", "Соңғы цифр үш", "+77775232863"),
        ("vehicle_plate", "945ABC01", "Өңір нөл бір емес нөл екі", "945ABC02"),
        ("vehicle_plate", "945ADC02", "Бәрі дұрыс, тек екінші әріп B", "945ABC02"),
        ("vehicle_plate", "945ABC02", "Нет, екінші әріп D", "945ADC02"),
        ("vehicle_plate", "945ABC02", "Нет, номер 945ABD02", "945ABD02"),
        ("vehicle_plate", "945ABC02", "Нет, вместо А — Б", "945BBC02"),
    ],
)
def test_minimal_edit_is_private_and_requires_final_confirmation(kind, value, text, expected):
    parsed = parse_confirmation(text, kind)
    assert parsed.kind == "correction"
    assert apply_correction(value, kind, parsed.correction) == expected
    assert value not in repr(parsed) and expected not in repr(parsed)
    services, router = build(kind, "kk" if "Жоқ" in text or "Соңғы" in text else "ru")

    async def run():
        await submit(services, value, value)
        result = await services.messages.process("precision", text, channel="voice")
        private = services.dialogs.get("precision")
        assert private.conversation.structured_capture.candidate == expected
        assert private.conversation.structured_capture.phase == "confirmation"
        assert private.slots == {} and private.client_lookup_attempts == []
        assert router.calls == [] and not result.trace.actions
        assert not result.trace.recognition.accepted
        assert expected not in result.model_dump_json()
        assert (
            "Нөмірді" in result.response_text
            if private.response_language == "kk"
            else "Проверьте номер" in result.response_text
        )
        confirmed = await services.messages.process("precision", "да", channel="voice")
        assert confirmed.trace.recognition.verification_method == "customer_confirmation"
        assert services.dialogs.get("precision").identification.provided_values[kind] == [expected]
        assert expected not in json.dumps(router.calls)

    asyncio.run(run())


@pytest.mark.parametrize(
    "old,new", [("A", "B"), ("B", "D"), ("C", "S"), ("M", "N"), ("P", "B"), ("E", "A")]
)
def test_explicit_letter_confusions(old, new):
    edit = parse_confirmation(f"Вместо {old} — {new}", "vehicle_plate").correction
    assert apply_correction(f"123{old}ZX02", "vehicle_plate", edit) == f"123{new}ZX02"


def test_ambiguous_edit_preserves_candidate_and_allows_only_one_clarification():
    services, _ = build("phone")

    async def run():
        await submit(services, "+77775232862", "+77775232862")
        reply = await services.messages.process(
            "precision", "Вместо семёрки — восемь", channel="voice"
        )
        assert "позицию" in reply.response_text
        pending = services.dialogs.get("precision").conversation.structured_capture
        assert pending.candidate == "+77775232862" and pending.phase == "confirmation"
        reply = await services.messages.process(
            "precision", "Вместо семёрки — восемь", channel="voice"
        )
        assert reply.conversation_status == "handoff" and not reply.trace.actions

    asyncio.run(run())


def test_clarification_resolves_position_without_resetting_or_admitting():
    services, _ = build("phone")

    async def run():
        await submit(services, "+77775232862", "+77775232862")
        await services.messages.process("precision", "Вместо семёрки — восемь", channel="voice")
        await services.messages.process("precision", "Вторая цифра", channel="voice")
        state = services.dialogs.get("precision")
        assert state.conversation.structured_capture.candidate == "+78775232862"
        assert state.slots == {} and state.client_lookup_attempts == []

    asyncio.run(run())


def test_correction_cycles_are_bounded():
    services, _ = build("vehicle_plate")

    async def run():
        await submit(services, "945ABC02", "945ABC02")
        for letter in ["D", "E"]:
            reply = await services.messages.process(
                "precision", f"Вторая буква {letter}", channel="voice"
            )
            assert reply.conversation_status == "awaiting_user"
        reply = await services.messages.process("precision", "Вторая буква F", channel="voice")
        assert reply.conversation_status == "handoff" and not reply.trace.actions
        assert services.dialogs.get("precision").slots == {}

    asyncio.run(run())


def test_browser_correction_exhaustion_offers_working_manual_input_without_voice_loop():
    services, _ = build("vehicle_plate")

    async def run():
        await submit(services, "945ABC02", "945ABC02")
        for letter in ["D", "E", "F"]:
            reply = await services.messages.process(
                "precision", f"Вторая буква {letter}", channel="voice", manual_input_available=True
            )
        assert reply.conversation_status == "awaiting_user"
        assert reply.trace.recognition.outcome == "manual_fallback"
        assert "клавиатуры" in reply.response_text
        assert services.dialogs.get("precision").slots == {}
        reply = await services.messages.process("precision", "945AFC02", channel="text")
        assert reply.trace.recognition.verification_method == "manual_entry"
        assert services.dialogs.get("precision").identification.provided_values[
            "vehicle_plate"
        ] == ["945AFC02"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    ["Не знаю", "Да, но номер неверный", "Поменяйте полис", "A B D", "Первая буква B и вторая C"],
)
def test_unclear_reply_never_confirms_or_invents_edit(text):
    parsed = parse_confirmation(text, "vehicle_plate")
    assert parsed.kind != "confirm"
    if parsed.correction:
        assert apply_correction("945ABC02", "vehicle_plate", parsed.correction) is None
