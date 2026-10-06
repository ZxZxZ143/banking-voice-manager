"""Synthetic RU/KK confirmation evidence; real parser and application admission."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_structured_precision import VALUES, build, submit

from app.packs.insurance_manager.data.demo_profile import with_demo_profile
from app.packs.insurance_manager.data.repositories import MockBackendRepository
from app.packs.insurance_manager.speech_capture import advance_capture
from app.speech.structured.capture import StructuredCapture
from app.speech.structured.context import CONFIRMATION_KEYWORDS, context_for_capture
from app.speech.structured.correction import parse_confirmation
from app.speech.structured.recognition import CONFIRMATION_AUDIO_LIMIT, resolve_recognition
from app.speech.stt.streaming import StreamInput, relay_stream


def confirmation_context(kind="phone", language="ru", phase="confirmation"):
    capture = StructuredCapture(kind, kind, "SC25", phase, candidate=VALUES[kind])
    return context_for_capture(kind, language, capture)


@pytest.mark.parametrize("language", ["ru", "kk"])
@pytest.mark.parametrize("kind", VALUES)
@pytest.mark.parametrize("phase", ["confirmation", "segment_confirmation"])
def test_confirmation_hints_are_public_bounded_and_preserve_both_languages(language, kind, phase):
    context = confirmation_context(kind, language, phase)
    assert len(context.prompt) <= 500
    assert context.expected_kind == "none" and context.confirmation_kind == kind
    assert context.keywords == CONFIRMATION_KEYWORDS
    assert "do not translate into English" in context.prompt
    assert all(value not in context.model_dump_json() for value in VALUES.values())
    assert "Russian" in context.prompt and "Kazakh" in context.prompt
    assert ("Prefer Russian" if language == "ru" else "Prefer Kazakh") in context.prompt


@pytest.mark.parametrize(
    "text,answer",
    [
        ("Да.", "confirm"),
        ("Нет.", "reject"),
        ("Иә.", "confirm"),
        ("Жоқ.", "reject"),
        ("Верно.", "confirm"),
        ("Неверно.", "reject"),
        ("Дұрыс.", "confirm"),
        ("Дұрыс емес.", "reject"),
        ("Нет, вместо C — D.", "correction"),
        ("Последняя цифра три.", "correction"),
    ],
)
def test_clear_ru_kk_replies_and_corrections_remain_single_pass(text, answer):
    async def run():
        provider = AsyncMock()
        result = await resolve_recognition(text, b"xx", confirmation_context(), provider)
        assert result.confirmation.kind == answer
        assert not result.metadata.second_pass_used
        provider.transcribe.assert_not_awaited()
        assert not result.metadata.accepted  # Only advance_capture can admit the private draft.

    asyncio.run(run())


@pytest.mark.parametrize("first", ["Yes", "No.", "Yep!", "Nope", "неразборчиво", "э"])
@pytest.mark.parametrize(
    "second,answer",
    [("Да.", "confirm"), ("Нет.", "reject"), ("Иә.", "confirm"), ("Жоқ.", "reject")],
)
def test_conditional_recovery_uses_one_attempt_and_only_local_parser_evidence(
    first, second, answer
):
    async def run():
        provider = AsyncMock()
        provider.transcribe.return_value = second
        result = await resolve_recognition(first, b"xx", confirmation_context(), provider)
        assert result.confirmation.kind == answer
        assert result.recovered_text == second
        assert result.metadata.second_pass_used and not result.metadata.first_pass_valid
        provider.transcribe.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("first,second", [("Да.", "Нет."), ("Иә.", "Жоқ."), ("Нет.", "Да.")])
def test_already_available_disagreeing_recognizers_never_choose(first, second):
    async def run():
        task = asyncio.create_task(asyncio.sleep(0, result=second))
        result = await resolve_recognition(first, b"xx", confirmation_context(), second_task=task)
        assert result.confirmation.kind == "conflict" and result.recovered_text is None
        services, _ = build("phone")
        await submit(services, VALUES["phone"], VALUES["phone"])
        state = services.dialogs.get("precision")
        step = advance_capture(state, first, result, "voice")
        assert "Уточните" in step.question
        assert step.state.conversation.structured_capture.candidate == VALUES["phone"]
        assert step.state.conversation.structured_capture.phase == "confirmation"
        assert not step.speech.metadata.accepted

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["english", "unknown", "timeout", "oversized"])
def test_unresolved_recovery_is_not_confirmation_or_rejection_and_never_retries(failure):
    async def run():
        provider = AsyncMock()
        provider.transcribe.return_value = {
            "english": "No.",
            "unknown": "хм",
            "oversized": "а" * 501,
        }.get(failure)
        if failure == "timeout":
            provider.transcribe.side_effect = TimeoutError("sensitive provider detail")
        result = await resolve_recognition("No.", b"xx", confirmation_context(), provider)
        assert result.confirmation.kind == "out_of_language_confirmation"
        provider.transcribe.assert_awaited_once()
        assert "sensitive" not in repr(result) + result.metadata.model_dump_json()

    asyncio.run(run())


@pytest.mark.parametrize("second,language", [("Да.", "ru"), ("Иә.", "kk")])
def test_screenshot_phone_no_then_yes_admits_full_phone_without_fallback(second, language):
    async def run():
        services, _ = build("phone", language)
        phone = "+77775232862"  # Exact synthetic screenshot read-back.
        services.insurance.processor.replies.backend = MockBackendRepository(
            with_demo_profile(services.kit.mock_backend, phone)
        )
        first, _ = await submit(services, phone, phone)
        assert ("«да» или «нет»" if language == "ru" else "Иә немесе жоқ") in first.response_text
        pending = services.dialogs.get("precision").conversation.structured_capture
        assert pending.candidate == phone
        final, _ = await submit(services, "No.", second)
        state = services.dialogs.get("precision")
        assert final.trace.recognition.accepted
        assert state.identification.provided_values["phone"] == [phone]
        assert "iin" not in state.identification.provided_values
        assert state.conversation.structured_capture is None
        assert state.conversation.expected_slot != "iin"
        assert state.identification.successful_field == "phone"
        assert final.conversation_status != "handoff"

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["confirmation", "segment_confirmation"])
@pytest.mark.parametrize("text", ["No.", "Yes", "Yep", "Nope", "хм", "не знаю", "Вы бот?"])
def test_unexpected_short_answer_is_owned_and_retains_same_draft_without_router(phase, text):
    async def run():
        services, router = build("phone")
        await submit(services, VALUES["phone"], VALUES["phone"])
        state = services.dialogs.get("precision")
        capture = state.conversation.structured_capture
        capture.phase = phase
        if phase == "segment_confirmation":
            capture.segment_candidate = "8777"
            capture.segment_attempts = {"first": 1}
        services.dialogs.save(state)
        result, _ = await submit(services, text, "No.")
        pending = services.dialogs.get("precision").conversation.structured_capture
        assert pending.candidate == VALUES["phone"] and pending.phase == phase
        assert pending.parts == []
        assert router.calls == [] and result.trace.actions == []
        assert result.conversation_status == "awaiting_user"
        assert "Не расслышал" in result.response_text
        assert not services.dialogs.get("precision").client_lookup_attempts
        assert not result.trace.recognition.accepted

    asyncio.run(run())


def test_confirmation_audio_is_bounded_and_cancellation_releases_recovery():
    async def run():
        provider = AsyncMock()
        await resolve_recognition(
            "No.", bytes(CONFIRMATION_AUDIO_LIMIT + 2), confirmation_context(), provider
        )
        provider.transcribe.assert_not_awaited()
        provider.transcribe.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await resolve_recognition("No.", b"xx", confirmation_context(), provider)

    asyncio.run(run())


@pytest.mark.parametrize(
    "first,second,calls,final",
    [("Да.", "No.", 0, "Да."), ("No.", "Да.", 1, "Да."), ("No.", "No.", 1, "No.")],
)
def test_stream_recovery_publishes_once_and_receipt_matches_visible_text(
    first, second, calls, final
):
    async def run():
        audio, wire = asyncio.Queue(), asyncio.Queue()
        audio.put_nowait(StreamInput("audio", bytes(4800)))
        audio.put_nowait(StreamInput("finish"))
        events, receipts = [], []
        provider = AsyncMock()
        provider.transcribe.return_value = second

        class Upstream:
            async def send(self, raw):
                if json.loads(raw)["type"].endswith("commit"):
                    wire.put_nowait(
                        json.dumps(
                            {"type": "input_audio_transcription.completed", "transcript": first}
                        )
                    )

            def __aiter__(self):
                return self

            async def __anext__(self):
                return await wire.get()

        class Detector:
            tracker = SimpleNamespace(has_speech=True, silence_ms=650)

            def feed(self, pcm):
                return False, 0.9

        async def emit(event):
            events.append(event)

        def record(text, result):
            receipts.append((text, result))
            return "receipt"

        await asyncio.wait_for(
            relay_stream(
                audio.get,
                emit,
                Upstream(),
                Detector(),
                context=confirmation_context(),
                second_pass=provider,
                record_recognition=record,
            ),
            1,
        )
        finals = [e for e in events if e["type"] == "utterance.final"]
        assert len(finals) == 1 and finals[0]["text"] == final
        assert receipts[0][0] == final and len(receipts) == 1
        assert provider.transcribe.await_count == calls
        if calls:
            assert provider.transcribe.call_args.args[0] == bytes(4800)
        assert finals[0]["recognition"]["second_pass_used"] == bool(calls)
        assert all(value not in json.dumps(finals) for value in VALUES.values())

    asyncio.run(run())


@pytest.mark.parametrize("word", ["Yes", "No", "Yep", "Nope"])
def test_english_words_are_never_added_to_ru_kk_parser(word):
    assert parse_confirmation(word, "phone").kind == "out_of_language_confirmation"
