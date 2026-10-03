"""OFFLINE ONLY: current core/Risk/SQLite/API with scripted model, STT and silent TTS.

No provider credentials, network calls, dial API or production database are used.
"""

import asyncio
import json
from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from app.core.config import Settings
from app.main import create_app
from app.packs.insurance_manager.agent.schemas import IdentifierAnswer, RouterDecision
from app.risk.models import RiskSignal, SecurityDecision
from app.telephony.base import CallStarted, ProviderAudio
from app.telephony.bench import FakePhoneTTS
from app.telephony.providers.mock import MockTelephonyProvider
from app.telephony.runtime import PhoneRuntime
from fastapi.testclient import TestClient


def routed(scenario="SC33", *, unavailable=None):
    return RouterDecision(
        language="ru",
        response_language="ru",
        scenarios=[
            {"scenario_id": scenario, "confidence": 0.99, "reason": "Offline fixture"}
        ],
        identifier_answer=(
            IdentifierAnswer(status="unavailable", field=unavailable)
            if unavailable
            else None
        ),
    )


class FixtureRouter:
    def __init__(self, *decisions):
        self.decisions = deque(decisions)
        self.histories = []

    async def route(self, text, state):
        self.histories.append(list(state.history))
        decision = self.decisions.popleft()
        if isinstance(decision, Exception):
            raise decision
        return decision


def concern():
    return SecurityDecision(
        intent="concern",
        language="ru",
        response_language="ru",
        risk_relevant=True,
        level="high",
        signals=[RiskSignal.BANK_IMPERSONATION, RiskSignal.OTP_REQUESTED],
        recommended_action="security_review",
        case_type="social_engineering",
    )


class FixtureRiskAgent:
    def __init__(self, *decisions):
        self.decisions = deque(decisions)
        self.requests = []

    async def analyze(self, payload):
        self.requests.append(payload)
        decision = self.decisions.popleft()
        if isinstance(decision, Exception):
            raise decision
        return decision


class FixtureSTT:
    """Per-run local capture state; byte markers select explicitly scripted finals."""

    def __init__(self, texts):
        self.texts = texts
        self.captures = []

    async def run(self, receive, emit):
        capture = []
        self.captures.append(capture)
        while True:
            packet = await receive()
            if packet.kind == "cancel":
                return
            if packet.kind == "audio":
                capture.append(packet.audio[0])
                await emit({"type": "transcript.partial", "delta": "[OFFLINE]"})
            elif packet.kind == "finish":
                assert capture and len(set(capture)) == 1
                marker = capture[0]
                await emit(
                    {
                        "type": "utterance.final",
                        "text": self.texts[marker],
                        "item_id": f"fixture-{marker}",
                        "language": "ru",
                    }
                )
                return


async def audio_turn(runtime, call_id, marker):
    session = runtime.registry.get(call_id)
    assert session is not None
    before = runtime._calls[call_id].turn_number
    assert await runtime.feed_audio(call_id, ProviderAudio(bytes([marker, 0]) * 240))
    await runtime.finish_utterance(call_id)
    async with asyncio.timeout(5):
        while runtime.registry.get(call_id) and (
            runtime._calls[call_id].turn_number == before or session.status != "active"
        ):
            await asyncio.sleep(0.001)
    # Final playback/terminal persistence can outlive registry invalidation briefly.
    await asyncio.sleep(0)


class FixtureComposer:
    async def compose(self, payload):
        # Exercise current deterministic composition fallback without any model call.
        raise ValueError("offline_composer")


def configure(services, *risk_decisions):
    risk_agent = FixtureRiskAgent(*risk_decisions)
    services.risk.agent = risk_agent
    services.messages.risk = services.risk
    services.insurance.processor.composer = FixtureComposer()
    return risk_agent


async def run_conversation(services):
    risk_agent = configure(services, concern())
    stt = FixtureSTT(
        {
            1: "[OFFLINE] Где находится офис?",
            2: "Мне звонят из банка и просят SMS-код.",
        }
    )
    provider, tts = MockTelephonyProvider(), FakePhoneTTS()
    runtime = PhoneRuntime(services.messages, stt, tts, provider)
    session = runtime.start_call(
        CallStarted("stage6-offline-call", {"provider": "mock"})
    )
    UUID(session.session_id)
    try:
        for marker in (1, 2):
            await audio_turn(runtime, session.call_id, marker)
        conversation = services.dialogs.get_conversation(session.session_id)
        assert conversation.global_context.turn_number == 2
        assert conversation.active_scenario_pack == "insurance_manager"
        assert risk_agent.requests[0].channel == "voice"
        assert risk_agent.requests[0].active_assistant == "insurance_manager"
        assert len(provider.outgoing[session.call_id]) == 2
        assert len(tts.requests) == 2 and stt.captures == [[1], [2]]
    finally:
        await runtime.shutdown()
    events = services.events.store.get_session_events(session.session_id).events
    assert sum(e.event_type == "conversation_started" for e in events) == 1
    assert sum(e.event_type == "conversation_turn" for e in events) == 2
    assert sum(e.event_type == "insurance_result" for e in events) >= 1
    assert sum(e.event_type == "risk_signal" for e in events) == 1
    assert sum(e.event_type == "conversation_ended" for e in events) == 1
    assert all(e.channel == "voice" and e.source == "runtime" for e in events)
    assert not runtime._calls and session.call_id in provider.closed
    return session.session_id, len(events)


def smoke(database: Path):
    settings = Settings(
        _env_file=None,
        event_db_path=database,
        openai_api_key=None,
        openai_router_model=None,
        demo_test_phone=None,
        twilio_enabled=False,
        vonage_enabled=False,
    )
    with TestClient(
        create_app(settings, router_override=FixtureRouter(routed()))
    ) as client:
        sid, count = client.portal.call(run_conversation, client.app.state.services)
        detail = client.get(f"/api/analytics/sessions/{sid}/detail")
        assert detail.status_code == 200
        for endpoint in ("overview", "sessions", "risk", "scenarios", "anomalies"):
            response = client.get(
                f"/api/analytics/{endpoint}", params={"channel": "voice"}
            )
            assert response.status_code == 200, endpoint
        response = client.get(f"/api/analytics/sessions/{sid}/journey")
        assert response.status_code == 200
        history = client.get(f"/api/analytics/sessions/{sid}").json()
        assert history["total"] == count
        assert client.get("/health").json()["telephony"] == {
            "twilio": "disabled",
            "vonage": "disabled",
        }
    # A fresh application/EventRecorder/SQLiteEventStore must see identical history.
    with TestClient(create_app(settings, router_override=FixtureRouter())) as restarted:
        assert restarted.get(f"/api/analytics/sessions/{sid}").json() == history
        assert (
            restarted.get(f"/api/analytics/sessions/{sid}/detail").json()
            == detail.json()
        )
    return {
        "mode": "OFFLINE MOCK — current core/Risk/SQLite/API, fixture models/STT/silent TTS",
        "channel": "voice",
        "source": "runtime (isolated temporary database only)",
        "turns": 2,
        "events": count,
        "same_session": True,
        "risk_persisted": True,
        "terminal_persisted": True,
        "restart_history_identical": True,
        "live_pstn": "NOT RUN — pending_credentials",
    }


if __name__ == "__main__":
    with TemporaryDirectory(prefix="stage6-offline-") as temporary:
        print(
            json.dumps(
                smoke(Path(temporary) / "events.db"), ensure_ascii=False, indent=2
            )
        )
