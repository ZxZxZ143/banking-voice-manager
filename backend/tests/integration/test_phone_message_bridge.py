"""Phone reuses the real MessageService with a fixture Router; no network calls."""

import asyncio

from app.agent.schemas import RouterDecision, ScenarioSelection
from app.core.config import Settings
from app.core.services import build_services
from app.telephony.base import CallStarted
from app.telephony.bench import FakePhoneTTS, ScriptedPhoneSTT
from app.telephony.providers.mock import MockTelephonyProvider
from app.telephony.runtime import PhoneRuntime


def test_phone_bridge_reuses_message_service_and_conversation_history():
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
            Settings(_env_file=None, openai_api_key=None, openai_router_model=None),
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
        responses = runtime.event_store.list(event_type="agent.response")
        assert len(responses) == 2
        assert all(event.trace["session_id"] == session.session_id for event in responses)
        assert all(event.trace["scenarios"][0]["scenario_id"] == "SC33" for event in responses)
        assert len(runtime.provider.outgoing["synthetic-call"]) == 2
        await runtime.shutdown()

    asyncio.run(run())
