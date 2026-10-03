from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.packs.product_promoter.models import ProductDecision


@pytest.mark.parametrize("mode", ["product_promoter", "card_promoter", "loan_promoter"])
def test_language_control_serializes_through_real_http_schema_and_keeps_sales_state(mode):
    app = create_app(Settings(_env_file=None))
    with TestClient(app) as client:
        pack = app.state.services.registry.get(mode)
        pack.agent = AsyncMock()
        pack.agent.decide.return_value = ProductDecision(
            intent=f"{pack.campaign}_interest", language="kk", response_language="kk"
        )
        opened = client.post(
            "/api/conversation/start",
            json={
                "session_id": "language-http",
                "scenario_mode": mode,
            },
        )
        assert opened.status_code == 200
        first = client.post(
            "/api/message",
            json={
                "session_id": "language-http",
                "text": "меня интересует накопительный депозит",
            },
        )
        assert first.status_code == 200
        assert first.json()["state"]["response_language"] == "ru"
        before = first.json()["state"]
        for command, language in [
            ("ответь на русском", "ru"),
            ("қазақша жауап беріңіз", "kk"),
            ("говорите по-русски", "ru"),
        ]:
            response = client.post(
                "/api/message",
                json={
                    "session_id": "language-http",
                    "text": command,
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["routing"]["kind"] == "language_control"
            assert body["routing"]["response_language"] == language
            assert body["state"]["preferred_response_language"] == language
            assert body["response_text"] == pack._question(before["last_question"], language)
            for key in (
                "sales_lead",
                "preferences",
                "sales_phase",
                "customer_turns",
                "last_question",
            ):
                assert body["state"][key] == before[key]
        assert pack.agent.decide.await_count == 1
