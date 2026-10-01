"""Deterministic Stage 1 API checks; live routing is evaluated separately."""

from collections import deque

import pytest
from fastapi.testclient import TestClient

from app.agent.errors import RouterOutputError
from app.agent.schemas import RouterDecision
from app.core.config import Settings
from app.main import create_app


def route(sid, *, language="ru", slots=None, continuation=False, **extra):
    return RouterDecision(
        language=language,
        response_language="kk" if language == "kk" else "ru",
        scenarios=[dict(scenario_id=sid, confidence=0.98, reason="Offline regression fixture")],
        slots=slots or {},
        is_continuation=continuation,
        **extra,
    )


class ScriptedRouter:
    def __init__(self, *decisions):
        self.decisions = deque(decisions)
        self.states = []

    async def route(self, text, state):
        self.states.append(state)
        return self.decisions.popleft()


def client_for(router):
    return TestClient(create_app(Settings(_env_file=None), router_override=router))


def send(client, text, session="stage1"):
    response = client.post("/api/message", json=dict(session_id=session, text=text))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["response_text"].strip()
    assert not any(
        token in body["response_text"] for token in ("{", "}", "None", "null", "undefined")
    )
    assert body["conversation_status"] == body["trace"]["conversation_status"]
    return body


@pytest.mark.parametrize(
    ("sid", "language", "text", "status"),
    [
        ("SC37", "ru", "Соедините меня с оператором.", "handoff"),
        ("SC37", "kk", "Мені операторға қосыңызшы.", "handoff"),
        ("SYS_GOODBYE", "ru", "Спасибо, до свидания.", "ended"),
        ("SYS_GOODBYE", "kk", "Рақмет, сау болыңыз.", "ended"),
    ],
)
def test_terminal_turn_is_successful_visible_and_closed(sid, language, text, status):
    router = ScriptedRouter(route(sid, language=language))
    with client_for(router) as client:
        body = send(client, text)
        assert body["conversation_status"] == status
        assert body["trace"]["handoff"] == (status == "handoff")
        assert body["state"]["response_language"] == language
        assert body["state"]["history"][-1]["text"] == body["response_text"]
        assert len(router.states) == 1
        assert (
            client.post(
                "/api/message", json=dict(session_id="stage1", text="Ещё вопрос")
            ).status_code
            == 409
        )


@pytest.mark.parametrize("language", ["ru", "kk", "mixed"])
def test_duration_answer_continues_trip_in_one_session(language):
    router = ScriptedRouter(
        route("SC06", language=language), route("SC06", language=language, continuation=True)
    )
    with client_for(router) as client:
        first = send(
            client,
            "Маған саяхат сақтандыруы керек."
            if language == "kk"
            else "Мне нужна туристическая страховка.",
        )
        second = send(client, "Екі аптаға." if language == "kk" else "На две недели.")
        assert first["state"]["active_scenario"] == second["state"]["active_scenario"] == "SC06"
        assert second["trace"]["policy_outcome"] == "continue"
        assert second["state"]["turn_number"] == 2
        assert len(router.states[1].history) == 2


def test_bad_clarification_template_is_replaced_with_targeted_options():
    router = ScriptedRouter(
        route(
            "SYS_UNCLEAR",
            clarification_question="{option} null",
            alternatives=[
                dict(scenario_id="SC25", confidence=0.7),
                dict(scenario_id="SC30", confidence=0.6),
            ],
        )
    )
    with client_for(router) as client:
        body = send(client, "У меня проблема с полисом.")
        assert body["trace"]["clarification"]
        assert "срок полиса" in body["response_text"] and "оплатой" in body["response_text"]


def test_multi_request_retains_driver_request_and_its_slots():
    decision = route("SC27", slots={"new_driver_iin": "850314300121"})
    decision.scenarios.append(dict_to_selection("SC04"))
    with client_for(ScriptedRouter(decision)) as client:
        body = send(client, "Хочу продлить ОГПО и добавить туда сына.")
        assert body["state"]["active_scenario"] == "SC27"
        assert body["state"]["pending_scenarios"] == ["SC04"]
        assert body["state"]["scenario_slots"]["SC04"]["new_driver_iin"] == "850314300121"


def dict_to_selection(sid):
    from app.agent.schemas import ScenarioSelection

    return ScenarioSelection(scenario_id=sid, confidence=0.98, reason="Offline fixture")


def test_completed_quote_does_not_end_conversation_or_leak_into_next_quote():
    router = ScriptedRouter(
        route("SC03", slots={"car_value": 10000000, "car_year": 2024}), route("SC03")
    )
    with client_for(router) as client:
        first = send(client, "Рассчитайте КАСКО.")
        assert "400000" in first["response_text"]
        assert first["conversation_status"] == "active"
        assert first["trace"]["completed_scenario"] == "SC03"
        assert first["trace"]["source_keys"] == ["knowledge_base.products.casco"]
        second = send(client, "Теперь рассчитать для другой машины.")
        assert "car_value" not in second["state"]["slots"]
        assert "стоит" in second["response_text"]


def test_owned_payment_lookup_returns_fact_and_successful_handoff():
    router = ScriptedRouter(
        route("SC30", slots={"phone": "+77010000009", "payment_date": "2026-06-01"})
    )
    with client_for(router) as client:
        body = send(client, "Оплата была, полиса нет.")
        assert "22800" in body["response_text"]
        assert body["conversation_status"] == "handoff"
        assert body["trace"]["actions"] == ["find_client", "check_payment"]


def test_unknown_weather_does_not_create_insurance_work():
    with client_for(ScriptedRouter(route("SYS_OUT_OF_SCOPE"))) as client:
        body = send(client, "Какая завтра погода в Алматы?")
        assert body["state"]["active_scenario"] is None
        assert body["trace"]["actions"] == []


def test_rejected_model_output_clarifies_then_hands_off_without_business_actions():
    class InvalidRouter:
        async def route(self, text, state):
            raise RouterOutputError("segment_coverage")

    with client_for(InvalidRouter()) as client:
        first = send(client, "Мне нужна помощь по полису.")
        assert first["conversation_status"] == "awaiting_user"
        assert first["trace"]["routing_error"] == "segment_coverage"
        assert first["trace"]["clarification"]
        assert first["trace"]["actions"] == []
        assert first["state"]["slots"] == {}
        second = send(client, "Всё ещё не получается разобраться.")
        assert second["conversation_status"] == "handoff"
        assert second["trace"]["handoff"]
        assert second["state"]["turn_number"] == 2
        assert second["trace"]["actions"] == []


@pytest.mark.parametrize("language", ["ru", "kk"])
@pytest.mark.parametrize("index", range(1, 41))
def test_every_catalog_flow_has_a_safe_first_response(index, language):
    sid = f"SC{index:02d}"
    with client_for(ScriptedRouter(route(sid, language=language))) as client:
        body = send(client, "Страховой запрос" if language == "ru" else "Сақтандыру сұрағы")
        assert "Выполнение операций" not in body["response_text"]
