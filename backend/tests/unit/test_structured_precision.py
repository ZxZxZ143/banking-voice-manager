"""Precision gate regressions. All identifiers/audio and semantic routers are synthetic."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.core.services import build_services
from app.packs.insurance_manager.agent.schemas import RouterDecision
from app.packs.insurance_manager.state import ConversationState, DialogState
from app.speech.structured.capture import PARTS
from app.speech.structured.context import context_for_slot
from app.speech.structured.policy import RISKS, RecognitionOutcome
from app.speech.structured.recognition import resolve_recognition
from app.speech.stt.streaming import StreamInput, relay_stream

VALUES = {
    "phone": "+77770001234",
    "iin": "000101300000",
    "policy_number": "SQ-OGPO-000123",
    "claim_number": "CL-000123",
    "vehicle_plate": "123ABC02",
}
SEGMENTS = {
    "phone": ["8777", "000", "1234"],
    "iin": ["000101", "300000"],
    "policy_number": ["SQ OGPO", "000123"],
    "claim_number": ["CL", "000123"],
    "vehicle_plate": ["123", "ABC", "02"],
}


class SameScenario:
    def __init__(self):
        self.calls = []

    async def route(self, text, state):
        self.calls.append((text, state.model_dump_json()))
        return RouterDecision(
            language=state.response_language,
            scenarios=[dict(scenario_id=state.active_scenario, confidence=0.99, reason="Fixture")],
            is_continuation=True,
            slots={"iin": "999999999999", "vehicle_plate": "999ZZZ02"},
        )


def build(kind, language="ru"):
    router = SameScenario()
    services = build_services(Settings(_env_file=None), router_override=router)
    services.dialogs.save(
        DialogState(
            session_id="precision",
            active_scenario="SC25",
            response_language=language,
            conversation=ConversationState(expected_slot=kind, policy_relationship="existing"),
        )
    )
    return services, router


async def submit(services, first, second):
    context, turn, slot = services.messages.transcription_snapshot("precision")
    provider = AsyncMock()
    provider.transcribe.return_value = second
    result = await resolve_recognition(first, bytes(4800), context, provider)
    receipt = services.messages.record_recognition("precision", turn, slot, first, result)
    response = await services.messages.process(
        "precision", first, channel="voice", recognition_id=receipt
    )
    return response, provider


@pytest.mark.parametrize("kind", VALUES)
@pytest.mark.parametrize("evidence", ["single", "consensus", "conflict", "outage"])
def test_valid_looking_hypotheses_never_authorize_sensitive_slots(kind, evidence):
    async def run():
        value = VALUES[kind]
        provider = None if evidence == "single" else AsyncMock()
        if provider:
            provider.transcribe.return_value = value if evidence != "conflict" else value[:-1] + "1"
            if evidence == "outage":
                provider.transcribe.side_effect = TimeoutError("private provider payload")
        result = await resolve_recognition(value, b"xx", context_for_slot(kind), provider)
        assert result.value is None and result.accepted_value is None
        assert not result.metadata.accepted and result.metadata.risk == RISKS[kind]
        assert result.metadata.outcome == (
            "repair_required" if evidence == "conflict" else "confirmation_required"
        )
        assert result.metadata.consensus == (evidence == "consensus")
        if provider:
            provider.transcribe.assert_awaited_once()
        assert value not in repr(result) and value not in result.metadata.model_dump_json()

    asyncio.run(run())


@pytest.mark.parametrize("kind", VALUES)
@pytest.mark.parametrize("language,yes", [("ru", "да"), ("kk", "иә")])
def test_confirmation_is_the_only_admission_and_preserves_relationship(kind, language, yes):
    services, router = build(kind, language)

    async def run():
        response, provider = await submit(services, VALUES[kind], VALUES[kind])
        private = services.dialogs.get("precision")
        assert private.slots == {} and private.client_lookup_attempts == []
        assert (
            private.identification.failed_attempts == []
            and private.identification.provided_values == {}
        )
        assert router.calls == [] and response.trace.actions == []
        assert response.state.conversation.policy_relationship == "existing"
        assert response.state.conversation.structured_capture is None
        assert response.trace.recognition.consensus
        context, _, slot = services.messages.transcription_snapshot("precision")
        assert context.expected_kind == "none" and slot == kind
        before = provider.transcribe.await_count
        response = await services.messages.process("precision", yes, channel="voice")
        assert response.trace.recognition.accepted
        assert response.trace.recognition.verification_method == "customer_confirmation"
        assert services.dialogs.get("precision").identification.provided_values[kind] == [
            VALUES[kind]
        ]
        assert provider.transcribe.await_count == before
        assert "999999999999" not in json.dumps(services.dialogs.get("precision").slots)
        assert VALUES[kind] not in response.model_dump_json()
        assert all(VALUES[kind] not in text + state for text, state in router.calls)

    asyncio.run(run())


@pytest.mark.parametrize("kind", VALUES)
def test_rejection_captures_segments_then_confirms_full_value(kind):
    services, _ = build(kind)

    async def run():
        await submit(services, VALUES[kind], VALUES[kind])
        response = await services.messages.process("precision", "нет", channel="voice")
        assert response.conversation_status == "awaiting_user"
        for index, part in enumerate(SEGMENTS[kind]):
            context, _, _ = services.messages.transcription_snapshot("precision")
            assert context.capture_part == PARTS[kind][index]
            assert VALUES[kind] not in context.model_dump_json()
            response, _ = await submit(services, part, part)
            assert not response.trace.recognition.accepted and response.trace.actions == []
            assert services.dialogs.get("precision").slots == {}
            assert services.dialogs.get("precision").client_lookup_attempts == []
        pending = services.dialogs.get("precision").conversation.structured_capture
        assert pending.phase == "confirmation"
        assert pending.candidate == ("87770001234" if kind == "phone" else VALUES[kind])
        response = await services.messages.process("precision", "да", channel="voice")
        assert response.trace.recognition.accepted
        assert services.dialogs.get("precision").identification.provided_values[kind] == [
            VALUES[kind]
        ]

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure", ["unclear_confirmation", "segment_conflict", "second_rejection", "expired"]
)
def test_verification_has_a_finite_path_to_handoff_without_lookup(failure):
    services, _ = build("vehicle_plate")

    async def run():
        await submit(services, "123AB02", "123AB02")
        if failure == "expired":
            state = services.dialogs.get("precision")
            state.conversation.structured_capture.expires_at = 0
            services.dialogs.save(state)
            response = await services.messages.process("precision", "да", channel="voice")
        elif failure == "unclear_confirmation":
            await services.messages.process("precision", "возможно", channel="voice")
            response = await services.messages.process("precision", "возможно", channel="voice")
        else:
            await services.messages.process("precision", "нет", channel="voice")
            if failure == "segment_conflict":
                response, _ = await submit(services, "123", "124")
                assert response.conversation_status == "awaiting_user"
                response, _ = await submit(services, "123", "124")
            else:
                for part in SEGMENTS["vehicle_plate"]:
                    await submit(services, part, part)
                response = await services.messages.process("precision", "нет", channel="voice")
        assert response.conversation_status == "handoff"
        assert response.trace.actions == [] and not response.trace.recognition.accepted
        private = services.dialogs.get("precision")
        assert private.slots == {} and private.client_lookup_attempts == []
        assert private.identification.failed_attempts == []
        assert private.conversation.structured_capture is None
        assert response.state.manager_summary.next_required_action == "verify_spoken_identifier"

    asyncio.run(run())


def test_typed_manual_correction_is_allowed_without_spoken_guess():
    services, _ = build("iin")

    async def run():
        await submit(services, "000101300001", "000101300001")
        response = await services.messages.process("precision", "000101300000", channel="text")
        assert response.trace.recognition.verification_method == "manual_entry"
        assert services.dialogs.get("precision").identification.provided_values["iin"] == [
            "000101300000"
        ]

    asyncio.run(run())


@pytest.mark.parametrize("language", ["ru", "kk"])
@pytest.mark.parametrize("source", ["SC31", "SC33", "security"])
def test_voice_wrap_up_ack_more_end_and_relationship_remain_intact(language, source):
    from test_insurance_completion import assert_metrics, build, decision

    choices = (
        []
        if source == "security"
        else [
            decision(
                source,
                lang=language,
                slots={"city": "Almaty"} if source == "SC33" else {},
            )
        ]
    )
    services, _ = build(
        *choices,
        decision(lang=language, signal="acknowledgement"),
        decision(lang=language, signal="more_questions"),
        decision(lang=language, signal="no_more_questions"),
        lang=language,
    )

    async def run():
        turn = await services.messages.process(
            "completed",
            "Оператор банка просит код из SMS" if source == "security" else "Условия оплаты",
            channel="voice",
        )
        assert_metrics(turn, wrap_up=True, relationship="not_applicable")
        for words, spec in [
            (("Хорошо", "Жақсы"), {"resolved_acknowledgement": True}),
            (("Ещё вопрос", "Тағы сұрағым бар"), {"open_followup": True}),
            (("Нет, спасибо", "Жоқ, рақмет"), {"no_more_questions": True}),
        ]:
            turn = await services.messages.process(
                "completed", words[language == "kk"], channel="voice"
            )
            assert_metrics(turn, **spec)
            assert turn.trace.recognition is None

    asyncio.run(run())


def test_risk_detour_retains_private_verification_and_relationship_without_confirming_it():
    from test_insurance_completion import build, decision

    services, router = build(decision(signal="acknowledgement"), decision("SC25"))
    services.dialogs.save(
        DialogState(
            session_id="precision",
            active_scenario="SC25",
            conversation=ConversationState(expected_slot="iin", policy_relationship="existing"),
        )
    )

    async def run():
        first, _ = await submit(services, VALUES["iin"], VALUES["iin"])
        risk = await services.messages.process(
            "precision", "Звонящий просит код из SMS", channel="voice"
        )
        assert risk.state.conversation.resume_after_risk
        assert risk.state.conversation.structured_capture is None
        assert VALUES["iin"] not in risk.model_dump_json()
        resumed = await services.messages.process("precision", "Хорошо", channel="voice")
        private = services.dialogs.get("precision")
        assert private.slots == {} and private.conversation.structured_capture is not None
        assert private.conversation.last_question == first.response_text
        assert private.conversation.policy_relationship == "existing"
        assert resumed.trace.actions == [] and not resumed.routing.scenarios
        final = await services.messages.process("precision", "да", channel="voice")
        assert final.trace.recognition.accepted
        assert first.response_text not in router.contexts[-1].model_dump_json()
        assert VALUES["iin"] not in final.model_dump_json()

    asyncio.run(run())


def test_direct_request_can_leave_pending_verification_without_committing_it():
    from test_insurance_completion import assert_metrics, build, decision

    services, _ = build(decision("SC06", relationship="new"))
    services.dialogs.save(
        DialogState(
            session_id="precision",
            active_scenario="SC25",
            conversation=ConversationState(expected_slot="iin", policy_relationship="existing"),
        )
    )

    async def run():
        await submit(services, VALUES["iin"], VALUES["iin"])
        turn = await services.messages.process(
            "precision", "Хочу страховку для поездки", channel="voice"
        )
        assert_metrics(turn, relationship="new", scenario="SC06", wrap_up=False)
        assert services.dialogs.get("precision").conversation.structured_capture is None
        assert "iin" not in services.dialogs.get("precision").slots

    asyncio.run(run())


def test_provisional_tts_preference_is_still_cedar():
    assert Settings(_env_file=None).backend_tts_voice == "cedar"


@pytest.mark.parametrize("contact_field,kind", [("phone", "phone"), ("email", "none")])
def test_contact_change_context_only_treats_phone_as_identifier(contact_field, kind):
    services, _ = build("new_value")
    state = services.dialogs.get("precision")
    state.slots["contact_field"] = contact_field
    services.dialogs.save(state)
    context, _, slot = services.messages.transcription_snapshot("precision")
    assert context.expected_kind == kind and slot == "new_value"


def test_new_contact_phone_requires_confirmation_without_replacing_identity_phone():
    services, _ = build("new_value")
    state = services.dialogs.get("precision")
    state.active_scenario = "SC29"
    state.slots = {"contact_field": "phone", "phone": "+77011110001"}
    services.dialogs.save(state)

    async def run():
        first, _ = await submit(services, VALUES["phone"], VALUES["phone"])
        assert first.trace.recognition.risk == "high" and not first.trace.recognition.accepted
        assert "new_value" not in services.dialogs.get("precision").slots
        result = await services.messages.process("precision", "да", channel="voice")
        assert result.trace.recognition.accepted
        private = services.dialogs.get("precision")
        assert private.slots["new_value"] == VALUES["phone"]
        assert private.slots["phone"] == "+77011110001"

    asyncio.run(run())


def test_data_provided_directly_after_risk_enters_verification_without_lost_attempt():
    services, router = build("iin")
    state = services.dialogs.get("precision")
    state.conversation.resume_after_risk = True
    services.dialogs.save(state)

    async def run():
        turn, _ = await submit(services, VALUES["iin"], VALUES["iin"])
        assert turn.trace.recognition.outcome == "confirmation_required"
        assert turn.trace.actions == [] and router.calls == []
        assert not services.dialogs.get("precision").conversation.resume_after_risk
        assert services.dialogs.get("precision").slots == {}

    asyncio.run(run())


def test_unrelated_question_cannot_leave_old_confirmation_authority_active():
    from test_insurance_completion import build, decision

    services, _ = build(decision("SYS_OUT_OF_SCOPE", scope_kind="identity"))
    services.dialogs.save(
        DialogState(
            session_id="precision",
            active_scenario="SC25",
            conversation=ConversationState(expected_slot="iin", policy_relationship="existing"),
        )
    )

    async def run():
        await submit(services, VALUES["iin"], VALUES["iin"])
        await services.messages.process(
            "precision", "Расскажите, как работает страховка?", channel="voice"
        )
        assert services.dialogs.get("precision").conversation.structured_capture is None
        assert services.dialogs.get("precision").slots == {}

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_bounded_starts_at_commit_before_realtime_final_and_cancellation_releases_it(cancel):
    # Segmented repair still requires both recognizers. Whole identifiers have a
    # separately tested race to read-back, without any acceptance authority.
    async def run():
        queue, upstream_events = asyncio.Queue(), asyncio.Queue()
        queue.put_nowait(StreamInput("audio", bytes(4800)))
        queue.put_nowait(StreamInput("finish"))
        entered, released = asyncio.Event(), asyncio.Event()
        events, receipts = [], []

        class Provider:
            calls = 0

            async def transcribe(self, pcm, context):
                self.calls += 1
                entered.set()
                try:
                    if cancel:
                        await asyncio.Future()
                    return "ABC"
                finally:
                    released.set()

        class Upstream:
            async def send(self, raw):
                if json.loads(raw)["type"].endswith("commit"):
                    await entered.wait()
                    if cancel:
                        queue.put_nowait(StreamInput("cancel"))
                    else:
                        upstream_events.put_nowait(
                            json.dumps(
                                {
                                    "type": "input_audio_transcription.completed",
                                    "transcript": "ABC",
                                }
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

        async def emit(event):
            events.append(event)

        def record(text, result):
            receipts.append(result)
            return "synthetic-receipt"

        provider = Provider()
        await asyncio.wait_for(
            relay_stream(
                queue.get,
                emit,
                Upstream(),
                Detector(),
                context=context_for_slot("vehicle_plate").model_copy(
                    update={"capture_part": "letters"}
                ),
                second_pass=provider,
                record_recognition=record,
            ),
            2,
        )
        assert provider.calls == 1 and released.is_set()
        finals = [e for e in events if e["type"] == "utterance.final"]
        assert len(finals) == (0 if cancel else 1)
        if not cancel:
            assert receipts[0].metadata.consensus
            assert receipts[0].metadata.outcome == RecognitionOutcome.confirmation_required

    asyncio.run(run())
