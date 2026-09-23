"""Scripted language regressions, not live model accuracy measurements."""

import json
from collections import deque

import pytest
from fastapi.testclient import TestClient

from app.agent.prompts import build_router_input
from app.agent.schemas import RouterDecision, ScenarioSelection
from app.core.config import Settings
from app.dialog.message import reply_language_for_turn
from app.dialog.models import DialogState, DialogTurn
from app.main import create_app


class WrongReplyLanguageRouter:
    def __init__(self):
        self.languages = deque(["ru", "kk", "ru"])

    async def route(self, text, state):
        language = self.languages.popleft()
        return RouterDecision(
            language=language,
            response_language="ru" if language == "kk" else "kk",
            clarification_question="Wrong-language question must never be displayed?",
            scenarios=[
                ScenarioSelection(scenario_id="SYS_UNCLEAR", confidence=0.9, reason="Offline test")
            ],
        )


def test_current_language_overrides_stale_reply_language_in_one_session():
    settings = Settings(
        _env_file=None,
        openai_api_key=None,
        openai_router_model=None,
        router_max_unclear_turns=10,
    )
    with TestClient(create_app(settings, router_override=WrongReplyLanguageRouter())) as client:
        for turn, language in enumerate(("ru", "kk", "ru"), 1):
            result = client.post(
                "/api/message", json={"session_id": "reply-language", "text": "test"}
            )
            assert result.status_code == 200
            body = result.json()
            assert body["state"]["response_language"] == language
            assert body["routing"]["response_language"] == language
            assert body["routing"]["clarification_question"] is None
            assert "Wrong-language" not in body["response_text"]
            assert body["state"]["turn_number"] == turn
            assert body["conversation_status"] == "awaiting_user"
            if language == "kk":
                assert "қ" in body["response_text"].lower()
            else:
                assert "уточ" in body["response_text"].lower()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Кеңсенің жұмыс уақытын түсіндіріңізші", "kk"),
        ("Қайда?", "kk"),
        ("Где офис на Мәңгілік Ел?", "ru"),
        ("Сәлем, хочу узнать о страховке машины", "ru"),
        ("Номер полиса SQ-OGPO-123456", "ru"),
    ],
)
def test_kazakh_script_guard_does_not_treat_borrowed_names_as_language_switch(text, expected):
    decision = RouterDecision(
        language="ru",
        response_language="ru",
        scenarios=[ScenarioSelection(scenario_id="SC33", confidence=0.95, reason="Fixture")],
    )
    assert reply_language_for_turn(text, decision) == expected


def test_current_utterance_is_last_after_historical_context():
    state = DialogState(
        session_id="order",
        history=[DialogTurn(role="assistant", text="Previous answer")],
        turn_number=1,
    )
    payload = json.loads(build_router_input("Current question", state))
    assert list(payload) == ["dialog_state", "utterance"]
    assert payload["utterance"] == "Current question"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Как получить копию моего полиса?", "ru"),
        ("Хочу узнать, где ваш офис", "ru"),
        ("Мен полис туралы сұраймын", "kk"),
        ("SQ-OGPO-123456", "kk"),
    ],
)
def test_russian_function_words_override_stale_kazakh_reply_context(text, expected):
    decision = RouterDecision(
        language="kk",
        response_language="kk",
        scenarios=[ScenarioSelection(scenario_id="SC33", confidence=0.9, reason="Fixture")],
    )
    assert reply_language_for_turn(text, decision) == expected
