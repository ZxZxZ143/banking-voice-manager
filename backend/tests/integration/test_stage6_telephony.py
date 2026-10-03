"""Current Stage5 core through teammate PhoneRuntime; every external model/audio is a fixture."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from scripts.smoke_stage6_integration import (
    FixtureRouter,
    FixtureSTT,
    audio_turn,
    concern,
    configure,
    routed,
    smoke,
)

from app.agent.errors import RouterProviderError
from app.core.config import Settings
from app.core.services import build_services
from app.main import create_app
from app.packs.contracts import ConversationContext, GlobalConversationContext
from app.telephony.base import CallStarted, ProviderAudio, ProviderError
from app.telephony.bench import FakePhoneTTS
from app.telephony.providers.mock import MockTelephonyProvider
from app.telephony.runtime import PhoneRuntime


def build(tmp_path, *decisions):
    return build_services(
        Settings(
            _env_file=None,
            event_db_path=tmp_path / "events.db",
            openai_api_key=None,
            openai_router_model=None,
            demo_test_phone=None,
        ),
        router_override=FixtureRouter(*decisions),
    )


def phone(services, texts):
    return PhoneRuntime(
        services.messages, FixtureSTT(texts), FakePhoneTTS(), MockTelephonyProvider()
    )


def events(services, session):
    return services.events.store.get_session_events(session.session_id).events


def test_complete_current_core_risk_sqlite_api_and_restart(tmp_path):
    report = smoke(tmp_path / "events.db")
    assert report["events"] == 7 and report["restart_history_identical"]


def test_phone_insurance_policy_unavailable_phone_iin_exhaustion_and_privacy(tmp_path):
    services = build(
        tmp_path,
        routed("SC27"),
        routed("SC27", unavailable="policy_number"),
        routed("SC27"),
        routed("SC27"),
    )
    configure(services)
    texts = {
        1: "Хочу продлить полис",
        2: "Номера полиса нет под рукой",
        3: "87770001234",
        4: "000000000000",
    }

    async def run():
        runtime = phone(services, texts)
        session = runtime.start_call(CallStarted("PRIVATE_PROVIDER_ID", {"phone": "87770001234"}))
        expected = []
        for marker in texts:
            await audio_turn(runtime, session.call_id, marker)
            expected.append(services.traces.get(session.session_id)[-1].expected_slot)
        assert expected == ["policy_number", "phone", "iin", None]
        state = services.dialogs.get_conversation(session.session_id)
        insurance = state.scenario_contexts["insurance_manager"].state
        assert state.global_context.turn_number == 4
        assert insurance.identification.unavailable_fields == ["policy_number"]
        assert insurance.identification.failed_fields == ["phone", "iin"]
        assert insurance.manager_summary.reason == "lookup_exhausted"
        assert session.status == session.conversation_status == "handoff"
        assert len(runtime.provider.outgoing[session.call_id]) == 4
        assert not await runtime.feed_audio(session.call_id, ProviderAudio(bytes(480)))
        assert not await runtime.handle_transcript(
            session.call_id, {"type": "utterance.final", "text": "late"}
        )
        await services.messages.end_session(session.session_id)
        stored = events(services, session)
        assert sum(e.event_type == "operator_handoff" for e in stored) == 1
        assert sum(e.event_type == "conversation_turn" for e in stored) == 4
        assert not any(e.event_type == "conversation_ended" for e in stored)
        safe = json.dumps([e.model_dump(mode="json") for e in stored], ensure_ascii=False)
        disk = services.events.store.path.read_bytes()
        for value in [
            *texts.values(),
            "PRIVATE_PROVIDER_ID",
            "response_text",
            "transcript",
            "audio",
            "provider_metadata",
        ]:
            assert value not in safe
            assert value.encode() not in disk
        assert services.events.health().status == "ok"
        await runtime.shutdown()

    asyncio.run(run())


def test_parallel_insurance_fraud_calls_keep_state_stt_playback_and_events_isolated(tmp_path):
    services = build(tmp_path, routed("SC04"))
    risk = configure(services, concern())

    async def run():
        runtime = phone(
            services, {1: "Добавить водителя", 2: "Мне звонят из банка и просят SMS-код."}
        )
        insurance = runtime.start_call(CallStarted("insurance-call"))
        fraud = runtime.start_call(CallStarted("fraud-call"))
        # Explicit trusted application selection, like scenario_mode in the web core.
        # Provider metadata/text cannot select or instantiate another routing service.
        context = ConversationContext(
            global_context=GlobalConversationContext(session_id=fraud.session_id)
        )
        services.messages.lifecycle.activate(context, "fraud_security")
        services.dialogs.save_conversation(context)
        await asyncio.gather(
            audio_turn(runtime, insurance.call_id, 1), audio_turn(runtime, fraud.call_id, 2)
        )
        assert insurance.session_id != fraud.session_id
        left = services.dialogs.get_conversation(insurance.session_id)
        right = services.dialogs.get_conversation(fraud.session_id)
        assert set(left.scenario_contexts) == {"insurance_manager"}
        assert set(right.scenario_contexts) == {"fraud_security"}
        assert (
            left.scenario_contexts["insurance_manager"].state.conversation.expected_slot
            == "policy_number"
        )
        assert right.risk_context.previous_signals == concern().signals
        assert risk.requests[0].active_assistant == "fraud_security"
        assert sorted(runtime.stt.captures) == [[1], [2]]
        assert len({id(capture) for capture in runtime.stt.captures}) == 2
        assert (
            len(runtime.provider.outgoing[insurance.call_id])
            == len(runtime.provider.outgoing[fraud.call_id])
            == 1
        )
        assert runtime.tts.requests[0].text != runtime.tts.requests[1].text
        assert {e.assistant_id for e in events(services, insurance)} == {"insurance_manager"}
        assert {e.assistant_id for e in events(services, fraud)} == {"fraud_security"}
        assert any(e.event_type == "fraud_case" for e in events(services, fraud))
        await runtime.end_call(insurance.call_id)
        assert runtime.registry.get(fraud.call_id) is fraud
        await runtime.shutdown()
        for session in (insurance, fraud):
            assert sum(e.event_type == "conversation_ended" for e in events(services, session)) == 1

    asyncio.run(run())


def test_phone_risk_failure_remains_advisory_and_persists_unavailable(tmp_path):
    services = build(tmp_path)
    configure(services, RouterProviderError(timeout=True))

    async def run():
        runtime = phone(services, {1: "Мне звонят из банка и просят SMS-код."})
        session = runtime.start_call(CallStarted("risk-failure"))
        await audio_turn(runtime, session.call_id, 1)
        risk = next(e for e in events(services, session) if e.event_type == "risk_signal")
        assert risk.payload.analysis_status == "unavailable"
        assert risk.risk_level == "none" and not risk.risk_signals
        assert risk.payload.guidance_shown
        assert session.status == "active" and session.error_code is None
        assert (
            services.dialogs.get_conversation(session.session_id).active_scenario_pack
            == "insurance_manager"
        )
        assert runtime.provider.outgoing[session.call_id]
        await runtime.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize(
    "scenario,status,event_type",
    [
        ("SYS_GOODBYE", "ended", "conversation_ended"),
        ("SC37", "handoff", "operator_handoff"),
    ],
)
def test_phone_terminal_reply_precedes_close_and_is_persisted_once(
    tmp_path, scenario, status, event_type
):
    services = build(tmp_path, routed(scenario))
    configure(services)

    async def run():
        runtime = phone(services, {1: "[OFFLINE] terminal fixture"})
        order = []
        original_send, original_close = runtime.provider.send_audio, runtime.provider.close

        async def send(call_id, speech):
            order.append("reply")
            await original_send(call_id, speech)

        async def close(call_id):
            order.append("close")
            await original_close(call_id)

        runtime.provider.send_audio, runtime.provider.close = send, close
        session = runtime.start_call(CallStarted("terminal"))
        await runtime.handle_transcript(
            session.call_id, {"type": "utterance.final", "text": "[OFFLINE] terminal fixture"}
        )
        assert session.status == status and order == ["reply", "close"]
        await runtime.end_call(session.call_id)
        await services.messages.end_session(session.session_id)
        assert sum(e.event_type == event_type for e in events(services, session)) == 1
        assert not runtime.registry.get(session.call_id)

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["agent", "stt", "tts", "send", "disconnect"])
def test_current_phone_failures_close_committed_conversation_safely(tmp_path, stage, caplog):
    services = build(tmp_path, routed(), RouterProviderError() if stage == "agent" else routed())
    configure(services)

    async def fail(*args):
        raise RuntimeError("PRIVATE_DEPENDENCY_ERROR")

    async def run():
        runtime = phone(services, {1: "[OFFLINE] first", 2: "[OFFLINE] second"})
        session = runtime.start_call(CallStarted("failed-call"))
        await audio_turn(runtime, session.call_id, 1)
        if stage == "stt":
            runtime.stt.run = fail
        elif stage == "tts":
            runtime.tts.synthesize = fail
        elif stage == "send":
            runtime.provider.send_audio = fail
        if stage == "disconnect":
            await runtime.handle_event(ProviderError(session.call_id))
        else:
            await audio_turn(runtime, session.call_id, 2)
        # Termination invalidates transport immediately, then records safe closure.
        async with asyncio.timeout(3):
            while not any(e.event_type == "conversation_ended" for e in events(services, session)):
                await asyncio.sleep(0.001)
        assert session.status == "error"
        assert session.call_id in runtime.provider.closed
        assert (
            services.dialogs.get_conversation(session.session_id).global_context.conversation_status
            == "ended"
        )
        assert sum(e.event_type == "conversation_ended" for e in events(services, session)) == 1
        assert "PRIVATE_DEPENDENCY_ERROR" not in caplog.text
        await runtime.shutdown()

    asyncio.run(run())


def test_storage_failure_does_not_fake_success_or_break_phone_reply(tmp_path, monkeypatch):
    services = build(tmp_path, routed())
    configure(services)

    def fail(events):
        raise OSError("PRIVATE_STORAGE_ERROR")

    monkeypatch.setattr(services.events.store, "append_many", fail)

    async def run():
        runtime = phone(services, {1: "[OFFLINE] question"})
        session = runtime.start_call(CallStarted("storage-failure"))
        await audio_turn(runtime, session.call_id, 1)
        assert runtime.provider.outgoing[session.call_id]
        assert services.events.health().status == "degraded"
        assert services.events.health().last_error == "storage_unavailable"
        assert events(services, session) == []
        await runtime.shutdown()

    asyncio.run(run())


def test_turn_limit_applies_even_without_provider_final_id(tmp_path):
    services = build(tmp_path)

    async def run():
        runtime = phone(services, {})
        session = runtime.start_call(CallStarted("bounded"))
        runtime._calls[session.call_id].turn_number = 1000
        assert not await runtime.handle_transcript(
            session.call_id, {"type": "utterance.final", "text": "extra"}
        )
        assert session.error_code == "turn_limit"
        assert not services.router.histories and not runtime.tts.requests

    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twilio", "vonage"])
def test_partial_provider_configuration_fails_closed_without_breaking_health(tmp_path, provider):
    settings = Settings(
        _env_file=None,
        event_db_path=tmp_path / "events.db",
        openai_api_key=None,
        twilio_auth_token=None,
        vonage_private_key_path=None,
        **{f"{provider}_enabled": True},
    )
    with TestClient(create_app(settings, router_override=FixtureRouter())) as client:
        health = client.get("/health").json()
        assert health["telephony"][provider] == "unavailable"
        assert health["analytics"]["status"] == "ok"
        assert client.get("/api/analytics/overview").status_code == 200
        path = "voice" if provider == "twilio" else "answer"
        assert client.post(f"/api/v1/telephony/{provider}/{path}", json={}).status_code == 503
