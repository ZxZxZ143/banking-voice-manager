"""Offline scripted-router regressions; these do not measure live model accuracy."""

from collections import deque

import pytest
from fastapi.testclient import TestClient

from app.agent.schemas import RouterDecision, ScenarioScore, ScenarioSelection
from app.core.config import Settings
from app.data.loaders import load_starter_kit
from app.dialog.models import DialogState
from app.main import create_app


def settings(**overrides) -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "openai_api_key": None,
            "openai_router_model": None,
            "enable_dev_stand": False,
            "router_accept_threshold": 0.75,
            "router_low_threshold": 0.45,
            "router_handoff_after": 2,
            "router_max_unclear_turns": 3,
            **overrides,
        }
    )


def decision(
    *scenario_ids: str,
    slots: dict | None = None,
    confidence: float = 0.95,
    continuation: bool = False,
    alternatives: list[ScenarioScore] | None = None,
    clarification_question: str | None = None,
) -> RouterDecision:
    return RouterDecision(
        language="ru",
        response_language="ru",
        scenarios=[
            ScenarioSelection(
                scenario_id=scenario_id,
                confidence=confidence,
                reason="Scripted output for an offline v2 API regression",
            )
            for scenario_id in scenario_ids
        ],
        slots=slots or {},
        is_continuation=continuation,
        alternatives=alternatives or [],
        clarification_question=clarification_question,
    )


class ScriptedRouter:
    def __init__(self, *outputs: RouterDecision) -> None:
        self.outputs = deque(outputs)
        self.previous_states: list[DialogState] = []

    async def route(self, text: str, state: DialogState) -> RouterDecision:
        self.previous_states.append(state.model_copy(deep=True))
        return self.outputs.popleft().model_copy(deep=True)


@pytest.fixture(scope="module")
def kit():
    return load_starter_kit(settings().starter_kit_path)


def send(client, session_id: str, text: str) -> dict:
    response = client.post("/api/message", json={"session_id": session_id, "text": text})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == session_id
    assert body["conversation_status"] == body["state"]["conversation_status"]
    assert body["conversation_status"] == body["trace"]["conversation_status"]
    assert body["state"]["turn_number"] == body["trace"]["turn_number"]
    return body


def assert_trace(body: dict, *, completed: str | None, actions: list[str], sources: list[str]):
    trace = body["trace"]
    assert trace["completed_scenario"] == completed
    assert trace["actions"] == actions
    assert trace["source_keys"] == sources
    assert trace["policy_outcome"] in {"accept", "continue"}
    for component in ("router", "policy", "response", "total"):
        assert trace["latency_ms"][component] >= 0
        assert trace["latency_ms"][component] <= trace["latency_ms"]["total"]
    assert trace["latency_ms"]["stt"] is None
    assert trace["latency_ms"]["tts_first_audio"] is None


def test_office_completion_allows_new_business_until_explicit_goodbye(kit):
    office = next(item for item in kit.knowledge.offices if item["city"] == "Astana")
    router = ScriptedRouter(
        decision("SC33", slots={"city": "Astana"}),
        decision("SC27"),
        decision("SYS_GOODBYE"),
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        first = send(client, "office-then-renewal", "Где ваш офис в Астане?")
        assert "Мәңгілік Ел, 55" in first["response_text"]
        assert "понедельник–пятница 09:00–18:00, суббота 10:00–15:00" in first["response_text"]
        assert office["address"] not in first["response_text"]
        assert first["state"]["active_scenario"] is None
        assert first["conversation_status"] == "active"
        assert_trace(
            first,
            completed="SC33",
            actions=["get_offices"],
            sources=["knowledge_base.offices"],
        )

        second = send(client, "office-then-renewal", "Ещё хочу продлить полис.")
        assert second["state"]["active_scenario"] == "SC27"
        assert second["conversation_status"] == "awaiting_user"
        assert second["state"]["turn_number"] == 2
        assert second["state"]["scenario_stack"] == []
        assert router.previous_states[1].active_scenario is None
        assert router.previous_states[1].history[-1].text == first["response_text"]

        goodbye = send(client, "office-then-renewal", "До свидания.")
        assert goodbye["conversation_status"] == "ended"
        blocked = client.post(
            "/api/message", json={"session_id": "office-then-renewal", "text": "Ещё вопрос."}
        )
        assert blocked.status_code == 409
        assert len(router.previous_states) == 3


def test_side_office_answer_restores_active_renewal_and_removes_pending_duplicate():
    router = ScriptedRouter(
        decision("SC27", "SC04"),
        decision("SC33", "SC27", slots={"city": "Astana"}),
        decision("SC27", continuation=True),
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        send(client, "side-question", "Продлить полис и добавить водителя.")
        side = send(client, "side-question", "Сначала адрес офиса, затем продолжим продление.")
        assert side["state"]["active_scenario"] == "SC27"
        assert side["state"]["scenario_stack"] == []
        assert side["state"]["pending_scenarios"] == ["SC04"]
        assert side["conversation_status"] == "awaiting_user"
        assert side["trace"]["completed_scenario"] == "SC33"
        assert side["trace"]["active_scenario"] == "SC27"
        assert side["trace"]["pending_scenarios"] == ["SC04"]
        resumed = send(client, "side-question", "Да, вернёмся к продлению.")
        assert resumed["trace"]["policy_outcome"] == "continue"
        assert resumed["state"]["pending_scenarios"] == ["SC04"]
        assert router.previous_states[2].active_scenario == "SC27"


def test_completed_side_question_resumes_most_recent_stack_item_before_pending():
    router = ScriptedRouter(
        decision("SC27", "SC04"),
        decision("SC01"),
        decision("SC33", slots={"city": "Astana"}),
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        send(client, "nested-questions", "Продлить полис и добавить водителя.")
        switched = send(client, "nested-questions", "Сначала хочу узнать цену нового полиса.")
        assert switched["state"]["scenario_stack"] == ["SC27"]
        result = send(client, "nested-questions", "А где офис в Астане?")
        assert result["state"]["active_scenario"] == "SC01"
        assert result["state"]["scenario_stack"] == ["SC27"]
        assert result["state"]["pending_scenarios"] == ["SC04"]
        assert result["conversation_status"] == "awaiting_user"
        assert result["trace"]["completed_scenario"] == "SC33"


def test_completed_first_intent_activates_next_pending_intent():
    router = ScriptedRouter(decision("SC33", "SC27", slots={"city": "Astana"}))
    with TestClient(create_app(settings(), router_override=router)) as client:
        body = send(client, "office-and-renewal", "Адрес офиса в Астане, потом продлить полис.")
        assert body["trace"]["completed_scenario"] == "SC33"
        assert body["state"]["active_scenario"] == "SC27"
        assert body["state"]["pending_scenarios"] == []
        assert body["state"]["scenario_stack"] == []
        assert body["conversation_status"] == "awaiting_user"


def test_new_co_request_precedes_return_to_interrupted_work():
    router = ScriptedRouter(decision("SC27"), decision("SC33", "SC31", slots={"city": "Astana"}))
    with TestClient(create_app(settings(), router_override=router)) as client:
        send(client, "new-co-request", "Продлить полис.")
        body = send(client, "new-co-request", "Адрес офиса и способы оплаты, потом продление.")
        assert body["trace"]["completed_scenario"] == "SC33"
        assert body["state"]["active_scenario"] == "SC31"
        assert body["state"]["scenario_stack"] == ["SC27"]
        assert body["state"]["pending_scenarios"] == []


def test_policy_answer_requires_identifier_then_uses_owned_fixture_and_keeps_session_open(kit):
    policy = kit.mock_backend.policies[0]
    owner = next(item for item in kit.mock_backend.clients if item.client_id == policy.client_id)
    router = ScriptedRouter(
        decision("SC25", slots={"policy_number": policy.policy_number}),
        decision("SC25", slots={"phone": owner.phone}, continuation=True),
        decision("SC01"),
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        first = send(client, "owned-policy", "Действует ли мой полис?")
        assert first["state"]["active_scenario"] == "SC25"
        assert first["trace"]["actions"] == []
        assert first["trace"]["source_keys"] == []
        assert first["trace"]["completed_scenario"] is None

        body = send(client, "owned-policy", owner.phone)
        assert policy.policy_number in body["response_text"]
        assert policy.start_date.isoformat() in body["response_text"]
        assert policy.end_date.isoformat() in body["response_text"]
        assert kit.scenarios.meta.as_of_date.isoformat() in body["response_text"]
        assert owner.iin not in body["response_text"]
        assert owner.address not in body["response_text"]
        assert body["state"]["active_scenario"] is None
        assert body["conversation_status"] == "active"
        assert_trace(
            body,
            completed="SC25",
            actions=["find_client", "get_policy"],
            sources=["mock_backend.clients", f"mock_backend.policies.{policy.policy_number}"],
        )
        next_question = send(client, "owned-policy", "Теперь рассчитать новый полис.")
        assert next_question["state"]["turn_number"] == 3
        assert next_question["state"]["active_scenario"] == "SC01"
        assert next_question["conversation_status"] == "awaiting_user"


def test_policy_number_from_another_client_matches_absent_record_failure(kit):
    policy = kit.mock_backend.policies[0]
    other = next(item for item in kit.mock_backend.clients if item.client_id != policy.client_id)
    absent = "SQ-OGPO-999999"
    assert all(item.policy_number != absent for item in kit.mock_backend.policies)
    router = ScriptedRouter(
        decision("SC25", slots={"phone": other.phone, "policy_number": policy.policy_number}),
        decision("SC25", slots={"phone": other.phone, "policy_number": absent}),
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        mismatch = send(client, "not-owner", "Проверить полис по моему телефону.")
        missing = send(client, "absent-policy", "Проверить полис по моему телефону.")
        assert mismatch["response_text"] == missing["response_text"]
        for body in (mismatch, missing):
            assert policy.policy_number not in body["response_text"]
            assert policy.start_date.isoformat() not in body["response_text"]
            assert policy.end_date.isoformat() not in body["response_text"]
            assert body["state"]["active_scenario"] == "SC25"
            assert body["conversation_status"] == "awaiting_user"
            assert_trace(body, completed=None, actions=["find_client", "get_policy"], sources=[])


def test_owned_claim_status_is_grounded_and_completes_only_the_scenario(kit):
    claim = kit.mock_backend.claims[0]
    owner = next(item for item in kit.mock_backend.clients if item.client_id == claim.client_id)
    router = ScriptedRouter(
        decision("SC17", slots={"phone": owner.phone, "claim_number": claim.claim_number})
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        body = send(client, "claim-status", "Как продвигается рассмотрение заявления?")
        assert claim.claim_number in body["response_text"]
        assert "выплачено" in body["response_text"]
        assert "Выплата выполнена 2026-05-29" in body["response_text"]
        assert claim.next_step not in body["response_text"]
        assert body["state"]["active_scenario"] is None
        assert body["conversation_status"] == "active"
        assert_trace(
            body,
            completed="SC17",
            actions=["find_client", "get_claim"],
            sources=["mock_backend.clients", f"mock_backend.claims.{claim.claim_number}"],
        )


@pytest.mark.parametrize(("scenario_id", "topic"), [("SC31", "payments"), ("SC34", "app_help")])
def test_public_knowledge_answers_are_grounded_and_do_not_end_session(kit, scenario_id, topic):
    router = ScriptedRouter(decision(scenario_id))
    with TestClient(create_app(settings(), router_override=router)) as client:
        body = send(client, f"knowledge-{scenario_id}", "Подскажите информацию, пожалуйста.")
        if topic == "payments":
            for method in (
                "банковской картой",
                "по ссылке из СМС",
                "банковским переводом",
                "терминал",
            ):
                assert method in body["response_text"]
        else:
            assert "Войдите по номеру телефона и одноразовому СМС-коду" in body["response_text"]
        assert body["state"]["active_scenario"] is None
        assert body["conversation_status"] == "active"
        assert_trace(
            body,
            completed=scenario_id,
            actions=["kb_lookup"],
            sources=[f"knowledge_base.{topic}"],
        )


def test_clarification_preserves_context_rejects_uncertain_slots_then_accepts_correction():
    question = "Вы хотите узнать статус заявления или оспорить решение?"
    router = ScriptedRouter(
        decision("SC27", slots={"phone": "+77010000001"}),
        decision(
            "SC17",
            confidence=0.6,
            slots={"phone": "+77010000002"},
            alternatives=[
                ScenarioScore(scenario_id="SC19", confidence=0.7),
                ScenarioScore(scenario_id="SC18", confidence=0.4),
                ScenarioScore(scenario_id="SYS_UNCLEAR", confidence=0.8),
                ScenarioScore(scenario_id="SC17", confidence=0.55),
            ],
            clarification_question=question,
        ),
        decision("SC19"),
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        send(client, "correction", "Хочу продлить полис.")
        unclear = send(client, "correction", "Ещё вопрос по решению.")
        assert unclear["response_text"] == question
        assert unclear["state"]["clarification_options"] == ["SC19", "SC17"]
        assert unclear["state"]["active_scenario"] == "SC27"
        assert unclear["state"]["slots"] == {"phone": "+77010000001"}
        assert unclear["state"]["unclear_count"] == 1
        assert unclear["trace"]["clarification"] is True
        assert unclear["trace"]["policy_outcome"] == "clarify"
        assert unclear["trace"]["actions"] == []
        assert unclear["trace"]["source_keys"] == []
        assert unclear["trace"]["completed_scenario"] is None

        corrected = send(client, "correction", "Я хочу оспорить решение, а не узнать статус.")
        assert router.previous_states[2].clarification_options == ["SC19", "SC17"]
        assert corrected["state"]["active_scenario"] == "SC19"
        assert corrected["state"]["scenario_stack"] == ["SC27"]
        assert corrected["state"]["clarification_options"] == []
        assert corrected["state"]["unclear_count"] == 0
        assert corrected["state"]["slots"] == {"phone": "+77010000001"}
        assert corrected["conversation_status"] == "awaiting_user"
        assert corrected["trace"]["policy_outcome"] == "accept"


def test_configured_policy_threshold_changes_acceptance_without_changing_router_output():
    router = ScriptedRouter(decision("SC27", confidence=0.8))
    with TestClient(
        create_app(settings(router_accept_threshold=0.9), router_override=router)
    ) as client:
        body = send(client, "custom-policy", "Хочу продлить полис.")
        assert body["trace"]["policy_outcome"] == "clarify"
        assert body["state"]["active_scenario"] is None
        assert body["state"]["clarification_options"] == ["SC27"]
        assert body["conversation_status"] == "awaiting_user"


def test_corrected_phone_replaces_conflicting_old_iin(kit):
    owner, other = kit.mock_backend.clients[:2]
    policy = next(p for p in kit.mock_backend.policies if p.client_id == owner.client_id)
    router = ScriptedRouter(
        decision(
            "SC25",
            slots={"phone": owner.phone, "iin": other.iin, "policy_number": policy.policy_number},
        ),
        decision("SC25", slots={"phone": owner.phone}, continuation=True),
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        first = send(client, "correct-identity", "Проверьте полис по этим данным.")
        assert first["trace"]["completed_scenario"] is None
        corrected = send(client, "correct-identity", owner.phone)
        assert "iin" not in corrected["state"]["slots"]
        assert policy.policy_number in corrected["response_text"]
        assert corrected["trace"]["completed_scenario"] == "SC25"


def test_changed_identity_does_not_inherit_previous_owned_record(kit):
    owner, other = kit.mock_backend.clients[:2]
    first_policy = next(p for p in kit.mock_backend.policies if p.client_id == owner.client_id)
    next_policy = next(p for p in kit.mock_backend.policies if p.client_id == other.client_id)
    router = ScriptedRouter(
        decision("SC25", slots={"phone": owner.phone, "policy_number": first_policy.policy_number}),
        decision("SC25", slots={"phone": other.phone}),
    )
    with TestClient(create_app(settings(), router_override=router)) as client:
        send(client, "changed-identity", "Проверьте мой полис.")
        changed = send(client, "changed-identity", "Теперь проверить по другому телефону.")
        assert "policy_number" not in changed["state"]["slots"]
        assert first_policy.policy_number not in changed["response_text"]
        assert next_policy.policy_number in changed["response_text"]
        assert changed["trace"]["completed_scenario"] == "SC25"
