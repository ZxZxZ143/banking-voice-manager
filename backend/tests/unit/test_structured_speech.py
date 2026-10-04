"""Synthetic values only; acceptance, ambiguity and bounded repair contracts."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.core.services import build_services
from app.packs.insurance_manager.agent.schemas import RouterDecision
from app.packs.insurance_manager.state import ConversationState, DialogState
from app.speech.structured.context import context_for_slot
from app.speech.structured.normalization import normalize_spoken, pricing_region, recognize_expected
from app.speech.structured.recognition import RecognitionReceipts, resolve_recognition
from app.speech.stt.streaming_provider import configure_transcription


@pytest.mark.parametrize(
    "kind,text,value",
    [
        ("region_code", "регион ноль два", "02"),
        ("region_code", "это регион ноль два", "02"),
        ("region_code", "регион 02", "02"),
        ("region_code", "нөл бір", "01"),
        ("region_code", "екінші өңір", "02"),
        ("phone", "восемь семь семь семь ноль ноль ноль один два три четыре", "+77770001234"),
        ("phone", "плюс жеті семь жеті семь нөл ноль нөл бір екі три төрт", "+77770001234"),
        (
            "phone",
            "8 семьсот семьдесят семь ноль ноль ноль двенадцать тридцать четыре",
            "+77770001234",
        ),
        ("iin", "ноль ноль ноль один ноль один три ноль ноль ноль ноль ноль", "000101300000"),
        ("iin", "нөл нөл нөл бір нөл бір үш нөл нөл нөл нөл нөл", "000101300000"),
        ("iin", "нөл ноль нөл один нөл бір три нөл ноль нөл ноль нөл", "000101300000"),
        ("iin", "000 жүз жиырма үш 000 жүз жиырма үш", "000123000123"),
        ("policy_number", "эс кью о гэ пэ о ноль ноль ноль один два три", "SQ-OGPO-000123"),
        ("policy_number", "SQ КАСКО 000123", "SQ-CASCO-000123"),
        ("claim_number", "си эл нөл нөл нөл бір екі үш", "CL-000123"),
        ("vehicle_plate", "сто двадцать три эй би си регион ноль два", "123ABC02"),
        ("vehicle_plate", "бір екі үш а бэ сэ екінші өңір", "123ABC02"),
        ("vehicle_plate", "123 АВС 02", "123ABC02"),
    ],
)
def test_structured_values(kind, text, value):
    result = normalize_spoken(text, kind)
    assert result.accepted
    assert result.value == value


@pytest.mark.parametrize("code", range(1, 21))
def test_official_region_pricing(code):
    result = normalize_spoken(f"регион {code:02}", "region_code")
    assert result.value == f"{code:02}"
    assert pricing_region(result.value) == {1: "astana", 2: "almaty"}.get(code, "other")


@pytest.mark.parametrize(
    "kind,text",
    [
        ("none", "регион ноль два"),
        ("iin", "00010130000"),
        ("phone", "8777000123"),
        ("policy_number", "SQ-UNKNOWN-000123"),
        ("vehicle_plate", "123ABC99"),
        ("region_code", "регион 21"),
        ("region_code", "регион ноль два или ноль один"),
        ("iin", "000101300000 или 000101300001"),
    ],
)
def test_never_guess_invalid_or_conflicting_values(kind, text):
    assert not normalize_spoken(text, kind).accepted


def test_group_boundaries_can_remain_ambiguous():
    # 21 + 30 + 4 + 50 = 2130450; 20 + 1 + 34 + 50 = 2013450.
    result = normalize_spoken("двадцать один тридцать четыре пятьдесят", "iin", r"\d{7}")
    assert len(result.candidates) >= 2
    assert not result.accepted


def test_alternative_phone_is_never_relabelled_as_policy():
    result = recognize_expected(
        "восемь семь семь семь ноль ноль ноль один два три четыре", "policy_number"
    )
    assert result.kind == "phone" and result.value == "+77770001234"


def test_dynamic_provider_context_contains_only_field_hints():
    async def run():
        upstream = AsyncMock()
        upstream.recv.return_value = json.dumps({"type": "session.updated"})
        await configure_transcription(upstream, context_for_slot("iin", "kk"))
        config = json.loads(upstream.send.call_args.args[0])["session"]["audio"]["input"][
            "transcription"
        ]
        assert config["delay"] == "high"
        assert "twelve" in config["prompt"]
        assert config["keywords"] == []
        assert config["languages"] == ["kk", "ru"]
        await configure_transcription(upstream, context_for_slot(None))
        assert '"delay": "medium"' in upstream.send.call_args.args[0]

    asyncio.run(run())


@pytest.mark.parametrize("text,calls", [("регион ноль два", 0), ("регион неверно", 1)])
def test_second_pass_only_when_needed(text, calls):
    async def run():
        provider = AsyncMock()
        provider.transcribe.return_value = "регион ноль два"
        outcome = await resolve_recognition(text, bytes(4800), context_for_slot("region"), provider)
        assert provider.transcribe.await_count == calls
        assert outcome.value == "02"
        assert outcome.metadata.second_pass_used == bool(calls)
        assert "value" not in outcome.metadata.model_dump()
        assert "candidates" not in outcome.metadata.model_dump()

    asyncio.run(run())


def test_second_pass_failure_is_safe_and_never_retries():
    async def run():
        provider = AsyncMock()
        provider.transcribe.side_effect = TimeoutError("private payload")
        result = await resolve_recognition("ошибка", b"xx", context_for_slot("iin"), provider)
        assert not result.metadata.accepted and result.metadata.second_pass_failed
        provider.transcribe.assert_awaited_once()
        assert "private" not in repr(result)

    asyncio.run(run())


def test_receipt_is_bound_to_session_turn_slot_and_text_and_one_use():
    receipts = RecognitionReceipts()
    result = asyncio.run(resolve_recognition("регион 02", b"", context_for_slot("region")))
    token = receipts.put("s", 2, "region", "регион 02", result)
    for session, turn, slot, text in [
        ("other", 2, "region", "регион 02"),
        ("s", 3, "region", "регион 02"),
        ("s", 2, "iin", "регион 02"),
        ("s", 2, "region", "регион 01"),
    ]:
        assert receipts.take(token, session, turn, slot, text) is None
    assert receipts.take(token, "s", 2, "region", "регион 02") is result
    assert receipts.take(token, "s", 2, "region", "регион 02") is None


class SameScenarioRouter:
    async def route(self, text, state):
        return RouterDecision(
            language=state.response_language,
            scenarios=[
                dict(scenario_id=state.active_scenario, confidence=0.95, reason="Synthetic fixture")
            ],
            slots={"iin": "000101300000"},
        )


def test_recognition_failure_repairs_once_then_handoffs_without_lookup():
    built = build_services(Settings(_env_file=None), router_override=SameScenarioRouter())
    built.dialogs.save(
        DialogState(
            session_id="repair",
            active_scenario="SC27",
            conversation=ConversationState(expected_slot="region"),
        )
    )

    async def run():
        first = await built.messages.process("repair", "регион ошибка", channel="voice")
        assert "две цифры" in first.response_text
        assert first.state.conversation.recognition_attempts == {"region": 1}
        assert first.trace.actions == []
        second = await built.messages.process("repair", "регион ошибка", channel="voice")
        assert second.conversation_status == "handoff"
        assert second.trace.actions == []
        assert built.dialogs.get("repair").client_lookup_attempts == []
        assert built.dialogs.get("repair").identification.failed_attempts == []

    asyncio.run(run())


def test_region_answer_progresses_without_rewriting_transcript():
    built = build_services(Settings(_env_file=None), router_override=SameScenarioRouter())
    built.dialogs.save(
        DialogState(
            session_id="region",
            active_scenario="SC01",
            slots={"vehicle_type": "car"},
            conversation=ConversationState(expected_slot="region"),
        )
    )

    async def run():
        result = await built.messages.process("region", "регион ноль два", channel="voice")
        assert result.state.slots["region"] == "almaty"
        assert result.trace.transcript == "регион ноль два"
        assert result.trace.recognition.accepted
        assert result.trace.expected_slot != "region"

    asyncio.run(run())


def test_dataset_precision_and_coverage():
    from collections import Counter
    from pathlib import Path

    rows = json.loads(
        (Path(__file__).resolve().parents[3] / "data/speech/structured_utterances.json").read_text(
            encoding="utf-8"
        )
    )
    positives = [r for r in rows if r["expected"] is not None]
    assert Counter(r["kind"] for r in positives) == {
        "phone": 20,
        "iin": 20,
        "vehicle_plate": 20,
        "policy_number": 15,
        "claim_number": 10,
        "region_code": 15,
    }
    accepted = 0
    for row in rows:
        result = normalize_spoken(row["text"], row["kind"])
        if result.accepted:
            assert result.value == row["expected"], row["id"]
            accepted += 1
    assert accepted >= 95


@pytest.mark.parametrize(
    "text", ["Алматы регион 01", "Алматы регион 21", "Алматы неизвестно", "не Алматы"]
)
def test_region_conflicting_or_unknown_context_is_not_accepted(text):
    assert not normalize_spoken(text, "region_code").accepted


@pytest.mark.parametrize(
    "text,code", [("Алматы облысы", "05"), ("Алматы регион ноль два", "02"), ("Қызылорда", "11")]
)
def test_explicit_regions_and_consistent_codes(text, code):
    assert normalize_spoken(text, "region_code").value == code


def test_grouped_private_values_and_two_letter_plates_are_redacted():
    from app.packs.insurance_manager.privacy import redact_text

    for text in ("8 семьсот семьдесят семь ноль ноль ноль двенадцать тридцать четыре", "123AB02"):
        assert text not in redact_text(text)


@pytest.mark.parametrize(
    "raw",
    ["один два три эй би си ноль два", "123 A B C 02", "CL 123456"],
)
def test_private_identifiers_remain_redacted_without_current_slot_values(raw):
    from app.packs.insurance_manager.privacy import redact_text

    # Later public history is rebuilt from the private history, not the last
    # already-redacted API response; it must remain safe after a topic change.
    assert raw not in redact_text(raw, {"region": "almaty"})


def test_receipt_second_pass_requires_confirmation_and_is_private(tmp_path):
    built = build_services(
        Settings(_env_file=None, event_db_path=tmp_path / "events.db"),
        router_override=SameScenarioRouter(),
    )
    built.dialogs.save(
        DialogState(
            session_id="private",
            active_scenario="SC25",
            conversation=ConversationState(expected_slot="iin"),
        )
    )

    async def run():
        context, turn, slot = built.messages.transcription_snapshot("private")
        second = AsyncMock()
        second.transcribe.return_value = "000101300000"
        raw = "ноль ноль ноль один ошибка"
        outcome = await resolve_recognition(raw, bytes(4800), context, second)
        token = built.messages.record_recognition("private", turn, slot, raw, outcome)
        result = await built.messages.process("private", raw, channel="voice", recognition_id=token)
        assert "iin" not in built.dialogs.get("private").slots
        assert result.trace.actions == []
        assert result.trace.recognition.outcome == "confirmation_required"
        assert result.trace.recognition.second_pass_used
        assert raw not in result.model_dump_json()
        result = await built.messages.process("private", "да", channel="voice")
        private = built.dialogs.get("private")
        assert private.slots["iin"] == "000101300000"
        assert result.trace.recognition.verification_method == "customer_confirmation"
        public = result.model_dump_json()
        assert "000101300000" not in public and raw not in public
        assert private.conversation.recognition_attempts == {}
        assert built.messages.recognitions._items == {}

    asyncio.run(run())
    assert b"000101300000" not in (tmp_path / "events.db").read_bytes()


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_recognition_exhaustion_preserves_lookup_memory_and_prepares_summary(language):
    built = build_services(Settings(_env_file=None), router_override=SameScenarioRouter())
    built.dialogs.save(
        DialogState(
            session_id="repair-safe",
            response_language=language,
            active_scenario="SC01",
            conversation=ConversationState(expected_slot="region"),
        )
    )

    async def run():
        first = await built.messages.process("repair-safe", "ошибка", channel="voice")
        second = await built.messages.process("repair-safe", "ошибка", channel="voice")
        assert first.state.conversation.recognition_attempts["region"] == 1
        assert second.conversation_status == "handoff"
        assert second.state.manager_summary.next_required_action == "verify_spoken_identifier"
        assert second.state.client_lookup_attempts == []
        assert second.state.identification.failed_attempts == []

    asyncio.run(run())


@pytest.mark.parametrize("codec", ["twilio", "vonage"])
def test_phone_codec_to_shared_context_parser_and_progression(codec, caplog):
    import io
    import math
    import struct
    import wave

    from app.speech.tts.base import SpeechResult
    from app.telephony.base import CallStarted, ProviderAudio
    from app.telephony.bench import FakePhoneTTS
    from app.telephony.providers.mock import MockTelephonyProvider
    from app.telephony.providers.twilio_audio import MulawInput, speech_to_mulaw
    from app.telephony.providers.vonage_audio import L16Input, speech_to_l16
    from app.telephony.runtime import PhoneRuntime

    # Non-silent synthetic tone exercises actual codecs; STT is explicitly a fixture.
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(
            b"".join(struct.pack("<h", int(2000 * math.sin(i / 10))) for i in range(4800))
        )
    speech = SpeechResult(audio=buffer.getvalue(), content_type="audio/wav", language="ru")
    encoded = speech_to_mulaw(speech) if codec == "twilio" else speech_to_l16(speech)
    decoder = MulawInput() if codec == "twilio" else L16Input()
    size = 160 if codec == "twilio" else 640
    pcm_frames = [
        frame
        for i in range(0, len(encoded), size)
        for frame in decoder.decode(encoded[i : i + size])
    ]
    built = build_services(Settings(_env_file=None), router_override=SameScenarioRouter())

    class FixtureSTT:
        async def run_with_context(self, receive, emit, context, record):
            assert context.expected_kind == "region_code" and context.accuracy_mode == "high"
            pcm = bytearray()
            while True:
                event = await receive()
                if event.kind == "audio":
                    pcm.extend(event.audio)
                elif event.kind == "finish":
                    assert pcm and any(pcm)
                    raw = "регион ноль два"
                    result = await resolve_recognition(raw, bytes(pcm), context)
                    await emit(
                        dict(type="utterance.final", text=raw, recognition_id=record(raw, result))
                    )
                    pcm.clear()
                    return

    async def run():
        provider = MockTelephonyProvider()
        runtime = PhoneRuntime(built.messages, FixtureSTT(), FakePhoneTTS(), provider)
        session = runtime.start_call(CallStarted("fixture-codec"))
        built.dialogs.save(
            DialogState(
                session_id=session.session_id,
                active_scenario="SC01",
                slots={"vehicle_type": "car"},
                conversation=ConversationState(expected_slot="region"),
            )
        )
        for frame in pcm_frames:
            await runtime.feed_audio("fixture-codec", ProviderAudio(frame))
        await runtime.finish_utterance("fixture-codec")
        async with asyncio.timeout(2):
            while not provider.outgoing.get("fixture-codec"):
                await asyncio.sleep(0)
        state = built.dialogs.get(session.session_id)
        assert state.slots["region"] == "almaty" and state.conversation.expected_slot != "region"
        assert built.messages.recognitions._items == {}
        await runtime.shutdown()

    asyncio.run(run())
    assert "регион ноль два" not in caplog.text


@pytest.mark.parametrize("cancel", [False, True])
def test_second_pass_has_its_own_deadline_and_cancellation_stops_late_final(monkeypatch, cancel):
    from types import SimpleNamespace

    from app.speech.stt import streaming
    from app.speech.stt.streaming import StreamInput, relay_stream

    clock = [0.0]
    monkeypatch.setattr(streaming, "perf_counter", lambda: clock[0])

    async def run():
        queue = asyncio.Queue()
        upstream_events = asyncio.Queue()
        queue.put_nowait(StreamInput("audio", bytes(4800)))
        queue.put_nowait(StreamInput("finish"))
        entered = asyncio.Event()
        events, receipts = [], []

        class Upstream:
            async def send(self, raw):
                if json.loads(raw)["type"].endswith("commit"):
                    upstream_events.put_nowait(
                        json.dumps(
                            dict(type="input_audio_transcription.completed", transcript="ошибка")
                        )
                    )

            def __aiter__(self):
                return self

            async def __anext__(self):
                return await upstream_events.get()

        class Detector:
            tracker = SimpleNamespace(has_speech=True, silence_ms=0)

            def feed(self, pcm):
                return False, 0.9

        class SecondPass:
            async def transcribe(self, pcm, context):
                assert pcm == bytes(4800)
                entered.set()
                clock[0] = 31  # First transcript arrived; its deadline must stop.
                if cancel:
                    await asyncio.Future()
                await asyncio.sleep(0.25)
                return "регион ноль два"

        async def emit(event):
            events.append(event)

        def record(text, result):
            receipts.append(result)
            return "fixture-receipt"

        task = asyncio.create_task(
            relay_stream(
                queue.get,
                emit,
                Upstream(),
                Detector(),
                context=context_for_slot("region"),
                second_pass=SecondPass(),
                record_recognition=record,
            )
        )
        await entered.wait()
        if cancel:
            queue.put_nowait(StreamInput("cancel"))
        await asyncio.wait_for(task, 1)
        finals = [e for e in events if e["type"] == "utterance.final"]
        if cancel:
            assert finals == [] and receipts == []
        else:
            assert len(finals) == 1 and receipts[0].value == "02"
            assert finals[0]["text"] == "ошибка"
            assert "value" not in finals[0]["recognition"]

    asyncio.run(run())


def test_evaluation_never_counts_outage_as_zero_latency_or_negative_as_recovery():
    import runpy
    from pathlib import Path

    summary = runpy.run_path(
        str(Path(__file__).resolve().parents[3] / "scripts/evaluate_structured_speech.py")
    )["summary"]
    rows = [
        dict(
            kind="iin",
            language="ru",
            expected="synthetic",
            accepted=False,
            correct=False,
            latency_ms=100,
            second_pass_used=True,
        ),
        dict(
            kind="iin",
            language="ru",
            expected="synthetic",
            accepted=False,
            correct=False,
            latency_ms=0,
            provider_failed=True,
        ),
        dict(
            kind="iin",
            language="kk",
            expected=None,
            accepted=False,
            correct=True,
            latency_ms=200,
            second_pass_used=True,
        ),
    ]
    result = summary(rows)
    assert result["latency_p50_ms"] >= 100
    assert result["second_pass_recovery_rate"] == 0
    assert result["provider_failures"] == 1


@pytest.mark.parametrize(
    "slot,kind,text,value,scenario",
    [
        ("drivers_iin", "iin", "000101300000", ["000101300000"], "SC01"),
        ("new_driver_iin", "iin", "000101300000", "000101300000", "SC04"),
        ("culprit_vehicle_plate", "vehicle_plate", "123ABC02", "123ABC02", "SC14"),
    ],
)
def test_related_source_slots_use_same_parser_and_keep_their_business_field(
    slot, kind, text, value, scenario
):
    built = build_services(Settings(_env_file=None), router_override=SameScenarioRouter())
    built.dialogs.save(
        DialogState(
            session_id="alias",
            active_scenario=scenario,
            conversation=ConversationState(expected_slot=slot),
        )
    )
    context, _, _ = built.messages.transcription_snapshot("alias")
    assert context.expected_kind == kind

    async def run():
        await built.messages.process("alias", text, channel="voice")
        assert slot not in built.dialogs.get("alias").slots
        await built.messages.process("alias", "да", channel="voice")
        state = built.dialogs.get("alias")
        assert state.slots[slot] == value
        assert "iin" not in state.slots

    asyncio.run(run())
