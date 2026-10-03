"""Phone reuses the real MessageService with a fixture Router; no network calls."""

import asyncio

from app.agent.schemas import RouterDecision, ScenarioSelection
from app.core.config import Settings
from app.core.services import build_services
from app.telephony.base import CallStarted
from app.telephony.bench import FakePhoneTTS, ScriptedPhoneSTT
from app.telephony.providers.mock import MockTelephonyProvider
from app.telephony.runtime import PhoneRuntime


def test_phone_bridge_reuses_message_service_and_conversation_history(tmp_path):
    class FixtureRouter:
        def __init__(self):
            self.histories = []

        async def route(self, text, state):
            self.histories.append(list(state.history))
            return RouterDecision(
                language="kk",
                response_language="kk",
                scenarios=[
                    ScenarioSelection(scenario_id="SC33", confidence=0.95, reason="Offline fixture")
                ],
            )

    async def run():
        router = FixtureRouter()
        services = build_services(
            Settings(
                _env_file=None,
                openai_api_key=None,
                openai_router_model=None,
                event_db_path=tmp_path / "events.db",
            ),
            router_override=router,
        )
        runtime = PhoneRuntime(
            services.messages, ScriptedPhoneSTT(), FakePhoneTTS(), MockTelephonyProvider()
        )
        session = runtime.start_call(CallStarted("synthetic-call"))
        for text in ("Кеңсе қайда?", "Жұмыс уақыты?"):
            assert await runtime.handle_transcript(
                "synthetic-call", {"type": "utterance.final", "text": text}
            )
        assert len(router.histories[0]) == 0
        assert len(router.histories[1]) == 2
        assert services.dialogs.get(session.session_id).turn_number == 2
        assert all(request.language == "kk" for request in runtime.tts.requests)
        events = services.events.store.get_session_events(session.session_id).events
        assert sum(e.event_type == "conversation_turn" for e in events) == 2
        assert all(e.channel == "voice" and e.source == "runtime" for e in events)
        assert {e.scenario_id for e in events if e.event_type == "insurance_result"} == {"SC33"}
        assert len(runtime.provider.outgoing["synthetic-call"]) == 2
        await runtime.shutdown()

    asyncio.run(run())
