"""Offline API contract checks; scripted outputs do not measure LLM routing accuracy."""

import asyncio
from collections import deque

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.errors import RouterOutputError, RouterProviderError
from app.agent.schemas import RouterDecision, ScenarioScore, ScenarioSelection
from app.core.config import Settings
from app.dialog.models import DialogState
from app.main import create_app


def settings() -> Settings:
    return Settings(_env_file=None, openai_api_key=None, openai_router_model=None)


def decision(
    *scenario_ids: str,
    language: str = "ru",
    confidence: float = 0.95,
    slots: dict | None = None,
    continuation: bool = False,
    alternatives: list[ScenarioScore] | None = None,
) -> RouterDecision:
    return RouterDecision(
        language=language,
        scenarios=[
            ScenarioSelection(
                scenario_id=scenario_id,
                confidence=confidence,
                reason="Scripted output for an offline API contract check",
            )
            for scenario_id in scenario_ids
        ],
        alternatives=alternatives or [],
        slots=slots or {},
        is_continuation=continuation,
    )


class ScriptedRouter:
    """Replay test outputs in call order, without inspecting text or expected labels."""

    def __init__(self, *outputs: RouterDecision | Exception) -> None:
        self.outputs = deque(outputs)
        self.calls: list[tuple[str, DialogState]] = []

    async def route(self, text: str, state: DialogState) -> RouterDecision:
        self.calls.append((text, state.model_copy(deep=True)))
        output = self.outputs.popleft()
        if isinstance(output, Exception):
            # Failed provider code must not mutate a previously committed session.
            state.slots["phone"] = "+77019999999"
            state.active_scenario = "SC37"
            raise output from RuntimeError("private provider diagnostic")
        return output.model_copy(deep=True)


@pytest.mark.parametrize(
    ("text", "language", "scenario_id"),
    [
        ("  Хочу узнать стоимость страховки на машину.  ", "ru", "SC01"),
        ("Полисімнің мерзімін ұзартқым келеді.", "kk", "SC27"),
        ("Маған подскажите адрес вашего офиса.", "mixed", "SC33"),
    ],
)
def test_message_single_intent_contract_and_trace(text, language, scenario_id):
    router = ScriptedRouter(decision(scenario_id, language=language))
    with TestClient(create_app(settings(), router_override=router)) as client:
        response = client.post("/api/message", json={"session_id": "abc123", "text": text})
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "session_id",
            "response_text",
            "routing",
            "state",
            "trace",
            "conversation_status",
        }
        assert body["session_id"] == "abc123"
        assert body["response_text"].strip()
        assert body["routing"]["language"] == language
        assert body["routing"]["scenarios"][0]["scenario_id"] == scenario_id
        assert body["state"]["language"] == language
        assert body["state"]["active_scenario"] == scenario_id
        assert body["state"]["turn_number"] == 1
        assert body["conversation_status"] in {"active", "awaiting_user"}
        assert body["state"]["conversation_status"] == body["conversation_status"]
        assert body["state"]["history"] == [
            {"role": "user", "text": text.strip()},
            {"role": "assistant", "text": body["response_text"]},
        ]
        trace = body["trace"]
        assert trace["transcript"] == text.strip()
        assert trace["turn"] == 1
        assert trace["session_id"] == "abc123"
        assert trace["language"] == language
        assert trace["actions"] == []
        assert trace["active_scenario"] == scenario_id
        assert trace["conversation_status"] == body["conversation_status"]
        for component in ("router", "policy", "response", "total"):
            assert trace["latency_ms"][component] >= 0
        assert trace["latency_ms"]["stt"] is None
        assert trace["latency_ms"]["tts_first_audio"] is None
        assert len(client.app.state.services.traces.get("abc123")) == 1
        assert len(router.calls) == 1
        assert router.calls[0][0] == text.strip()


@pytest.mark.parametrize(
    ("selected", "active", "pending"),
    [
        (["SC27", "SC04"], "SC27", ["SC04"]),
        (["SC27", "SC11"], "SC11", ["SC27"]),
    ],
)
def test_message_multi_intent_orders_urgent_first_otherwise_spoken_order(selected, active, pending):
    router = ScriptedRouter(decision(*selected, language="mixed"))
    with TestClient(create_app(settings(), router_override=router)) as client:
        response = client.post(
            "/api/message",
            json={
                "session_id": "two-requests",
                "text": "Полисті продлить, ещё есть второй вопрос.",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert {item["scenario_id"] for item in body["routing"]["scenarios"]} == set(selected)
        assert body["state"]["active_scenario"] == active
        assert body["state"]["pending_scenarios"] == pending
        assert body["trace"]["pending_scenarios"] == pending
        assert len(router.calls) == 1


def test_message_continuation_preserves_pending_slots_and_history():
    router = ScriptedRouter(
        decision("SC27", "SC04", slots={"phone": "+77010000000"}),
        decision("SC27", slots={"policy_number": "SQ-OGPO-123456"}, continuation=True),
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        first = client.post(
            "/api/message", json={"session_id": "abc123", "text": "Продлить и добавить водителя."}
        )
        assert first.status_code == 200
        second = client.post(
            "/api/message", json={"session_id": "abc123", "text": "SQ-OGPO-123456"}
        )
        assert second.status_code == 200
        state = second.json()["state"]
        assert state["turn_number"] == 2
        assert state["active_scenario"] == "SC27"
        assert state["pending_scenarios"] == ["SC04"]
        assert state["scenario_stack"] == []
        assert state["slots"] == {"phone": "+77010000000", "policy_number": "SQ-OGPO-123456"}
        assert len(state["history"]) == 4
        assert state["history"][:2] == first.json()["state"]["history"]
        previous = router.calls[1][1]
        assert previous.active_scenario == "SC27"
        assert previous.pending_scenarios == ["SC04"]
        assert previous.slots["phone"] == "+77010000000"
        assert any(turn.text == first.json()["response_text"] for turn in previous.history)
        assert [trace.turn for trace in client.app.state.services.traces.get("abc123")] == [1, 2]


def test_message_topic_switch_and_return_keep_stack_without_active_duplicates():
    router = ScriptedRouter(decision("SC27"), decision("SC33"), decision("SC27"))
    with TestClient(create_app(settings(), router_override=router)) as client:
        responses = [
            client.post("/api/message", json={"session_id": "topics", "text": text})
            for text in ("Продлить страховку.", "Сначала адрес офиса.", "Вернёмся к продлению.")
        ]
        assert all(response.status_code == 200 for response in responses)
        assert responses[1].json()["state"]["scenario_stack"] == ["SC27"]
        final = responses[2].json()["state"]
        assert final["active_scenario"] == "SC27"
        assert final["scenario_stack"] == ["SC33"]
        assert final["turn_number"] == 3


def test_message_sessions_do_not_share_context_slots_or_traces():
    router = ScriptedRouter(
        decision("SC27", slots={"phone": "+77010000000"}), decision("SC33", language="kk")
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        first = client.post("/api/message", json={"session_id": "first", "text": "Продлить полис."})
        second = client.post("/api/message", json={"session_id": "second", "text": "Кеңсе қайда?"})
        assert first.status_code == second.status_code == 200
        state = second.json()["state"]
        assert state["session_id"] == "second"
        assert state["slots"] == {}
        assert state["turn_number"] == 1
        assert state["scenario_stack"] == []
        assert router.calls[1][1].active_scenario is None
        assert router.calls[1][1].slots == {}
        assert len(client.app.state.services.traces.get("first")) == 1
        assert len(client.app.state.services.traces.get("second")) == 1


def test_message_ambiguity_preserves_active_context_and_does_not_accept_uncertain_slots():
    router = ScriptedRouter(
        decision("SC27", slots={"phone": "+77010000000"}),
        decision(
            "SC17",
            confidence=0.6,
            slots={"phone": "+77019999999"},
            alternatives=[ScenarioScore(scenario_id="SC19", confidence=0.55)],
        ),
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        first = client.post(
            "/api/message", json={"session_id": "unsure", "text": "Продлить полис."}
        )
        response = client.post(
            "/api/message", json={"session_id": "unsure", "text": "Что теперь с этим решением?"}
        )
        assert first.status_code == response.status_code == 200
        body = response.json()
        assert body["conversation_status"] == "awaiting_user"
        assert body["state"]["active_scenario"] == "SC27"
        assert body["state"]["slots"] == {"phone": "+77010000000"}
        assert body["state"]["unclear_count"] == 1
        assert body["trace"]["clarification"]
        assert body["routing"]["alternatives"][0]["scenario_id"] == "SC19"


@pytest.mark.parametrize(
    ("scenario_id", "confidence", "count"), [("SYS_UNCLEAR", 0.9, 3), ("SC01", 0.2, 2)]
)
def test_message_repeated_uncertainty_ends_in_handoff(scenario_id, confidence, count):
    router = ScriptedRouter(*(decision(scenario_id, confidence=confidence) for _ in range(count)))
    with TestClient(create_app(settings(), router_override=router)) as client:
        responses = [
            client.post("/api/message", json={"session_id": "unclear", "text": "Не понимаю."})
            for _ in range(count)
        ]
        assert all(response.status_code == 200 for response in responses)
        assert all(
            response.json()["conversation_status"] == "awaiting_user" for response in responses[:-1]
        )
        final = responses[-1].json()
        assert final["conversation_status"] == "handoff"
        assert final["state"]["conversation_status"] == "handoff"
        assert final["trace"]["handoff"] is True


@pytest.mark.parametrize(("scenario_id", "status"), [("SC37", "handoff"), ("SYS_GOODBYE", "ended")])
def test_message_terminal_session_rejects_more_turns_without_routing(scenario_id, status):
    router = ScriptedRouter(decision(scenario_id))
    with TestClient(create_app(settings(), router_override=router)) as client:
        first = client.post("/api/message", json={"session_id": "done", "text": "Закончим."})
        assert first.status_code == 200
        assert first.json()["conversation_status"] == status
        again = client.post("/api/message", json={"session_id": "done", "text": "Ещё вопрос."})
        assert again.status_code == 409
        assert len(router.calls) == 1
        assert client.app.state.services.dialogs.get("done").turn_number == 1
        assert len(client.app.state.services.traces.get("done")) == 1


def test_message_out_of_scope_keeps_active_session_for_next_turn():
    router = ScriptedRouter(
        decision("SC27"), decision("SYS_OUT_OF_SCOPE"), decision("SC27", continuation=True)
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        first = client.post("/api/message", json={"session_id": "scope", "text": "Продлить полис."})
        outside = client.post(
            "/api/message", json={"session_id": "scope", "text": "Оформите кредит."}
        )
        assert first.status_code == outside.status_code == 200
        assert outside.json()["conversation_status"] == "awaiting_user"
        assert outside.json()["state"]["active_scenario"] == "SC27"
        resume = client.post(
            "/api/message", json={"session_id": "scope", "text": "Тогда продление."}
        )
        assert resume.status_code == 200
        assert resume.json()["state"]["active_scenario"] == "SC27"
        assert resume.json()["state"]["turn_number"] == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "", "text": "Вопрос"},
        {"session_id": "   ", "text": "Вопрос"},
        {"session_id": "x" * 129, "text": "Вопрос"},
        {"session_id": "valid", "text": "  "},
        {"session_id": "valid", "text": "x" * 10001},
        {"text": "Вопрос"},
        {"session_id": "valid"},
    ],
)
def test_message_invalid_input_never_routes(payload):
    router = ScriptedRouter()
    with TestClient(create_app(settings(), router_override=router)) as client:
        response = client.post("/api/message", json=payload)
        assert response.status_code == 422
        assert router.calls == []
        assert client.app.state.services.dialogs.get("valid") is None


def test_message_missing_credentials_returns_unavailable_without_state_or_trace():
    with TestClient(create_app(settings())) as client:
        response = client.post(
            "/api/message", json={"session_id": "unconfigured", "text": "Здравствуйте"}
        )
        assert response.status_code == 503
        assert response.json()["error"]["message"]
        assert client.app.state.services.dialogs.get("unconfigured") is None
        assert client.app.state.services.traces.get("unconfigured") == []


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (RouterProviderError(), 502),
        (RouterProviderError(timeout=True), 504),
        (RouterOutputError(), 502),
    ],
)
def test_message_failed_router_does_not_commit_mutations_or_expose_provider_errors(error, status):
    router = ScriptedRouter(
        decision("SC27", slots={"phone": "+77010000000"}),
        error,
        decision("SC27", continuation=True),
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        first = client.post(
            "/api/message", json={"session_id": "recover", "text": "Продлить полис."}
        )
        assert first.status_code == 200
        before = client.app.state.services.dialogs.get("recover").model_dump()
        response = client.post(
            "/api/message", json={"session_id": "recover", "text": "Следующий ход."}
        )
        assert response.status_code == status
        assert "private" not in response.text
        assert client.app.state.services.dialogs.get("recover").model_dump() == before
        assert len(client.app.state.services.traces.get("recover")) == 1
        retry = client.post(
            "/api/message", json={"session_id": "recover", "text": "Повторим запрос."}
        )
        assert retry.status_code == 200
        assert retry.json()["state"]["turn_number"] == 2
        assert retry.json()["state"]["slots"] == {"phone": "+77010000000"}
        assert len(client.app.state.services.traces.get("recover")) == 2


def test_message_concurrent_same_session_turns_are_serialized():
    class SlowRouter(ScriptedRouter):
        def __init__(self):
            super().__init__(decision("SC27"), decision("SC27", continuation=True))
            self.in_flight = 0
            self.max_in_flight = 0

        async def route(self, text, state):
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            await asyncio.sleep(0.01)
            try:
                return await super().route(text, state)
            finally:
                self.in_flight -= 1

    async def run():
        router = SlowRouter()
        app = create_app(settings(), router_override=router)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                responses = await asyncio.gather(
                    *(
                        client.post("/api/message", json={"session_id": "parallel", "text": text})
                        for text in ("Продление", "Номер полиса")
                    )
                )
                assert all(response.status_code == 200 for response in responses)
                assert sorted(
                    response.json()["state"]["turn_number"] for response in responses
                ) == [1, 2]
                assert router.max_in_flight == 1
                assert router.calls[1][1].active_scenario == "SC27"
                assert any(turn.role == "assistant" for turn in router.calls[1][1].history)
                assert app.state.services.dialogs.get("parallel").turn_number == 2
                assert len(app.state.services.traces.get("parallel")) == 2

    asyncio.run(run())


def test_message_different_sessions_can_route_concurrently():
    class RendezvousRouter:
        def __init__(self):
            self.session_ids = set()
            self.both_entered = asyncio.Event()

        async def route(self, text, state):
            self.session_ids.add(state.session_id)
            if len(self.session_ids) == 2:
                self.both_entered.set()
            await asyncio.wait_for(self.both_entered.wait(), timeout=2)
            return decision("SC33")

    async def run():
        router = RendezvousRouter()
        app = create_app(settings(), router_override=router)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                responses = await asyncio.gather(
                    *(
                        client.post(
                            "/api/message", json={"session_id": session_id, "text": "Адрес"}
                        )
                        for session_id in ("parallel-a", "parallel-b")
                    )
                )
                assert all(response.status_code == 200 for response in responses)
                assert all(response.json()["state"]["turn_number"] == 1 for response in responses)
                assert router.session_ids == {"parallel-a", "parallel-b"}

    asyncio.run(run())
