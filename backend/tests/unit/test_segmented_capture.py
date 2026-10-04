"""Synthetic regression for private segment drafts, never early business admission."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from test_structured_precision import PARTS, SEGMENTS, VALUES, build

from app.speech.structured.capture import StructuredCapture, capture_question
from app.speech.structured.context import context_for_capture
from app.speech.structured.normalization import normalize_spoken
from app.speech.structured.policy import RecognitionHypothesis, StructuredRecognitionPolicy
from app.speech.structured.recognition import resolve_recognition
from app.speech.stt.adaptive_endpoint import AdaptiveEndpoint


async def spoken(services, text, second=None, *, browser=False, unavailable=False):
    context, turn, slot = services.messages.transcription_snapshot("precision")
    provider = AsyncMock() if second is not None or unavailable else None
    if provider:
        provider.transcribe.return_value = second
        if unavailable:
            provider.transcribe.side_effect = TimeoutError()
    result = await resolve_recognition(text, b"xx", context, provider)
    receipt = services.messages.record_recognition("precision", turn, slot, text, result)
    return await services.messages.process(
        "precision",
        text,
        channel="voice",
        recognition_id=receipt,
        manual_input_available=browser,
    )


def test_screenshot_missing_second_recognizer_confirms_first_segment_instead_of_handoff():
    services, router = build("phone")

    async def run():
        await spoken(services, "неразборчиво", "неразборчиво")
        router.calls.clear()
        response = await spoken(services, "Восемь семь семь семь", unavailable=True)
        assert response.conversation_status == "awaiting_user"
        assert "восемь, семь, семь, семь" in response.response_text
        assert services.dialogs.get("precision").slots == {}
        assert not router.calls
        await services.messages.process("precision", "да", channel="voice")
        context, _, _ = services.messages.transcription_snapshot("precision")
        assert context.capture_part == "middle"
        await spoken(services, "523", "523")
        response = await spoken(services, "2862", "2862")
        assert "Проверьте номер: восемь, семь, семь, семь" in response.response_text
        assert not response.trace.recognition.accepted
        assert not services.dialogs.get("precision").client_lookup_attempts
        response = await services.messages.process("precision", "да", channel="voice")
        assert response.trace.recognition.accepted
        assert services.dialogs.get("precision").identification.provided_values["phone"] == [
            "+77775232862"
        ]

    asyncio.run(run())


@pytest.mark.parametrize("kind", VALUES)
@pytest.mark.parametrize("mode", ["agreement", "single", "retry"])
@pytest.mark.parametrize("language,yes", [("ru", "да"), ("kk", "иә")])
def test_every_segment_has_independent_draft_budget_and_final_confirmation(
    kind, mode, language, yes
):
    services, router = build(kind, language)

    async def run():
        await spoken(services, "неразборчиво", "неразборчиво")
        router.calls.clear()
        for index, segment in enumerate(SEGMENTS[kind]):
            if mode == "retry":
                response = await spoken(services, "неразборчиво", "неразборчиво")
                assert response.conversation_status == "awaiting_user"
                assert (
                    services.messages.transcription_snapshot("precision")[0].capture_part
                    == PARTS[kind][index]
                )
            response = await spoken(services, segment, segment if mode != "single" else None)
            if mode == "single":
                state = services.dialogs.get("precision")
                assert state.conversation.structured_capture.phase == "segment_confirmation"
                assert len(state.conversation.structured_capture.parts) == index
                context = services.messages.transcription_snapshot("precision")[0]
                assert context.expected_kind == "none" and context.confirmation_kind == kind
                response = await services.messages.process("precision", yes, channel="voice")
            state = services.dialogs.get("precision")
            assert response.conversation_status == "awaiting_user" and not response.trace.actions
            assert state.slots == {} and not state.client_lookup_attempts
            assert (
                not state.identification.failed_attempts
                and not state.identification.provided_values
            )
            assert not router.calls
            assert state.conversation.structured_capture.segment_attempts[PARTS[kind][index]] == (
                1 if mode == "agreement" else 2
            )
            assert response.state.conversation.structured_capture is None
            assert all(segment not in turn.text for turn in state.history)
            assert response.trace.transcript == "[произнесённый номер скрыт]"
            assert "segment_candidate" not in response.trace.model_dump_json()
            assert "canonical_candidate" not in response.trace.model_dump_json()
        state = services.dialogs.get("precision")
        assert state.conversation.structured_capture.phase == "confirmation"
        response = await services.messages.process("precision", yes, channel="voice")
        assert response.trace.recognition.verification_method == "customer_confirmation"
        assert services.dialogs.get("precision").identification.provided_values[kind] == [
            VALUES[kind]
        ]

    asyncio.run(run())


def test_conflicting_first_segment_repeats_only_that_segment_once():
    services, _ = build("phone")

    async def run():
        await spoken(services, "неразборчиво", "неразборчиво")
        response = await spoken(services, "8777", "8771")
        pending = services.dialogs.get("precision").conversation.structured_capture
        assert pending.parts == [] and pending.segment_candidate is None
        assert "Повторите" in response.response_text and "первые 4" in response.response_text
        response = await spoken(services, "8777", "8777")
        pending = services.dialogs.get("precision").conversation.structured_capture
        assert response.conversation_status == "awaiting_user" and pending.parts == ["8777"]
        assert pending.segment_attempts == {"first": 2}
        assert "следующие 3" in response.response_text

    asyncio.run(run())


@pytest.mark.parametrize("browser", [False, True])
@pytest.mark.parametrize(
    "failure", ["conflict", "unusable", "rejected", "unclear", "single_after_retry"]
)
def test_segment_exhaustion_is_bounded_and_preserves_problem(browser, failure):
    services, _ = build("phone")

    async def run():
        await spoken(services, "неразборчиво", "неразборчиво", browser=browser)
        state = services.dialogs.get("precision")
        state.slots["contact_field"] = "email"
        services.dialogs.save(state)
        if failure in {"rejected", "unclear"}:
            await spoken(services, "8777", browser=browser)
            response = await services.messages.process(
                "precision",
                "нет" if failure == "rejected" else "возможно",
                channel="voice",
                manual_input_available=browser,
            )
        else:
            for attempt in range(2):
                response = await spoken(
                    services,
                    "8777"
                    if failure == "conflict" or failure == "single_after_retry" and attempt
                    else "неразборчиво",
                    "8771" if failure == "conflict" else None,
                    browser=browser,
                )
        state = services.dialogs.get("precision")
        assert state.active_scenario == "SC25" and state.slots == {"contact_field": "email"}
        assert not state.client_lookup_attempts and not state.identification.failed_attempts
        assert not state.identification.unavailable_fields
        if browser:
            assert response.conversation_status == "awaiting_user"
            assert response.trace.recognition.outcome == "manual_fallback"
            assert "клавиатуры" in response.response_text
            response = await services.messages.process("precision", "87775232862", channel="text")
            assert response.trace.recognition.verification_method == "manual_entry"
            assert services.dialogs.get("precision").identification.provided_values["phone"] == [
                "+77775232862"
            ]
        else:
            assert response.conversation_status == "handoff"
            assert response.state.manager_summary.scenario == "SC25"
            assert response.state.manager_summary.collected_fields == ["contact_field"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "source,style,first",
    [
        ("87775232862", "domestic_8", "8777"),
        ("77775232862", "international_7", "7777"),
        ("7775232862", "national_10", "777"),
    ],
)
def test_whole_and_segment_phone_preserve_spoken_style_and_final_correction(source, style, first):
    services, _ = build("phone")

    async def run():
        await spoken(services, source, source)
        pending = services.dialogs.get("precision").conversation.structured_capture
        assert pending.candidate == source and pending.phone_input_style == style
        response = await services.messages.process("precision", "нет", channel="voice")
        assert f"первые {len(first)}" in response.response_text
        context = services.messages.transcription_snapshot("precision")[0]
        assert str(len(first)) in context.prompt
        for segment in [first, "523", "2862"]:
            await spoken(services, segment, segment)
        state = services.dialogs.get("precision")
        assert state.conversation.structured_capture.candidate == source
        response = await services.messages.process(
            "precision", "Нет, последняя цифра три", channel="voice"
        )
        assert (
            services.dialogs.get("precision").conversation.structured_capture.candidate
            == source[:-1] + "3"
        )
        assert not response.trace.recognition.accepted and not response.trace.actions
        await services.messages.process("precision", "да", channel="voice")
        assert services.dialogs.get("precision").identification.provided_values["phone"] == [
            "+77775232863"
        ]

    asyncio.run(run())


@pytest.mark.parametrize(
    "kind,part",
    [
        ("phone", "first"),
        ("phone", "middle"),
        ("iin", "first"),
        ("vehicle_plate", "letters"),
        ("vehicle_plate", "region"),
    ],
)
def test_segments_use_fast_local_endpoint_and_no_private_value_in_context(kind, part):
    capture = StructuredCapture(kind, kind, "SC25", "segments")
    capture.parts = ["private"] * PARTS[kind].index(part)
    context = context_for_capture(kind, "ru", capture)
    assert "private" not in context.model_dump_json()
    assert 500 <= AdaptiveEndpoint(context).base_ms <= 900
    assert capture_question(capture, "ru")


def test_truncated_domestic_phone_is_not_reinterpreted_as_national():
    assert not normalize_spoken("8777000123", "phone").accepted
    assert normalize_spoken("7775232862", "phone").value == "+77775232862"


@pytest.mark.parametrize("evidence", ["invalid", "ambiguous", "unavailable"])
def test_single_segment_with_unusable_other_hypothesis_never_admits(evidence):
    first = RecognitionHypothesis("realtime", "phone", "8777", True, "unique_schema")
    second = RecognitionHypothesis("bounded", "phone", None, False, evidence)
    policy = StructuredRecognitionPolicy()
    for left, right in [(first, second), (second, first)]:
        result = policy.decide_segment("phone", left, right)
        assert result.segment_evidence == "single" and result.candidate == first
        assert result.accepted_value is None and not result.consensus


def test_bounded_only_segment_can_be_confirmed_without_partial_data_in_sqlite_or_logs(caplog):
    services, router = build("phone")

    async def run():
        await spoken(services, "неразборчиво", "неразборчиво")
        router.calls.clear()
        response = await spoken(services, "неразборчиво", "8777")
        assert response.conversation_status == "awaiting_user"
        await services.messages.process("precision", "да", channel="voice")
        pending = services.dialogs.get("precision").conversation.structured_capture
        assert pending.parts == ["8777"] and not router.calls
        assert "8777" not in repr(pending) and "8777" not in caplog.text
        events = services.events.store.get_session_events("precision")
        payloads = [event.payload.model_dump_json() for event in events.events]
        assert payloads and all(
            "8777" not in item and "segment_candidate" not in item for item in payloads
        )

    asyncio.run(run())


def test_disagreeing_national_phones_keep_three_digit_first_segment_layout():
    services, _ = build("phone")

    async def run():
        response = await spoken(services, "7775232862", "7775232863")
        assert "первые 3" in response.response_text
        await spoken(services, "777", "777")
        assert services.dialogs.get("precision").conversation.structured_capture.parts == ["777"]

    asyncio.run(run())


def test_eight_and_seven_are_distinct_draft_segments():
    services, _ = build("phone")

    async def run():
        await spoken(services, "неразборчиво", "неразборчиво")
        response = await spoken(services, "8777", "7777")
        assert response.trace.recognition.segment_evidence == "conflict"
        assert services.dialogs.get("precision").conversation.structured_capture.parts == []
        assert "Повторите" in response.response_text

    asyncio.run(run())
