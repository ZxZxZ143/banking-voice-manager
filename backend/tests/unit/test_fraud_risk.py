"""Security boundary and continuation checks; fixtures are never production fallbacks."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agents import AgentOutputSchema
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.errors import RouterOutputError, RouterProviderError
from app.agent.schemas import RouterDecision
from app.core.config import Settings
from app.core.services import build_services
from app.main import create_app
from app.packs.fraud_security.models import FraudCaseResult
from app.packs.product_promoter.models import Preferences, ProductDecision
from app.risk.agent import RiskAgent
from app.risk.models import RiskContext, RiskInput, RiskSignal, SecurityDecision
from app.risk.policy import load_policy
from app.risk.precheck import precheck
from app.risk.privacy import redact_authentication, redact_risk_input
from app.risk.service import RiskIntelligence


def security(signals=(), *, language="ru", **kwargs):
    return SecurityDecision(
        intent="concern" if signals else "general_info",
        language=language,
        response_language=language,
        risk_relevant=bool(signals),
        level="high" if signals else "none",
        signals=list(signals),
        recommended_action="security_review" if signals else "none",
        **kwargs,
    )


class RiskFixture:
    def __init__(self, *outputs):
        self.outputs, self.inputs = list(outputs), []

    async def analyze(self, payload):
        self.inputs.append(payload.model_dump(mode="json"))
        result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result.model_copy(deep=True)


class InsuranceFixture:
    def __init__(self):
        self.inputs = []

    async def route(self, text, state):
        self.inputs.append((text, state.model_copy(deep=True)))
        return RouterDecision(
            language="ru",
            slots={"trip_country": "Турция"},
            scenarios=[dict(scenario_id="SC06", confidence=0.99, reason="fixture")],
        )


class ProductFixture:
    def __init__(self):
        self.inputs = []

    async def decide(self, text, context):
        self.inputs.append(text)
        return ProductDecision(
            intent="card_interest",
            language="ru",
            response_language="ru",
            preferences=Preferences(cashback=True),
        )


def configure(built, fixture):
    intelligence = built.registry.get("fraud_security").intelligence
    intelligence.agent = fixture
    built.messages.risk = intelligence
    return built


def services(fixture):
    return configure(
        build_services(Settings(_env_file=None), router_override=InsuranceFixture()), fixture
    )


@pytest.mark.parametrize(
    "text",
    [
        "Хочу депозит на год",
        "Сейчас полис действует?",
        "Карта с кешбэком",
        "Депозитті бір жылға ашқым келеді",
        "Турция на 7 дней",
    ],
)
def test_harmless_gate_makes_no_model_call(text):
    fixture = RiskFixture()
    intelligence = RiskIntelligence(
        fixture, load_policy(Settings(_env_file=None).security_policy_path)
    )
    run = asyncio.run(intelligence.analyze(text, active_assistant="card_promoter"))
    assert run.assessment is None and run.agent_ms is None and not fixture.inputs


@pytest.mark.parametrize(
    "text",
    [
        "У меня просят код из SMS",
        "Банк қызметкері SMS кодты сұрап жатыр",
        "Подозрительная ссылка",
        "Установите AnyDesk, сказал звонящий",
        "Переведите на безопасный счёт",
        "Неизвестный перевод, я его не делал",
        "У меня украли карту",
        "Мой профиль взломали",
        "CVV спрашивает оператор",
        "Телефон в аккаунте сменили без меня",
    ],
)
def test_candidates_not_classified_by_regex(text):
    assert precheck(text).analyze
    assert not hasattr(precheck(text), "level") and not hasattr(precheck(text), "signals")


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("Код из SMS: 654321", "654321"),
        ("Я сообщил PIN 7248", "7248"),
        ("CVV=741", "741"),
        ("мой пароль Spring_Secret_42", "Spring_Secret_42"),
        ("сообщил пароль SpringSecret42", "SpringSecret42"),
        ("Карта 4111 2222 3333 4444", "4111 2222 3333 4444"),
        ("SMS код 6 5 4 3 2 1", "6 5 4 3 2 1"),
        ("растау коды: 654321", "654321"),
    ],
)
def test_authentication_is_masked_idempotently(text, secret):
    safe = redact_authentication(text)
    assert secret not in safe and "скрыт" in safe
    assert redact_authentication(safe) == safe


def test_normal_identification_is_not_destroyed_but_risk_gets_no_identifiers():
    text = "Телефон +77010000001, ИИН 000101300000, почта demo@example.invalid. Ссылка https://demo.invalid"
    assert redact_authentication(text) == text
    safe = redact_risk_input(text)
    assert all(s not in safe for s in ("77010000001", "000101300000", "demo@example", "https://"))
    with pytest.raises(ValidationError):
        RiskInput(
            current_text="text",
            active_assistant="insurance_manager",
            context={"client_id": "private"},
        )
    with pytest.raises(ValidationError):
        RiskInput(current_text="text", active_assistant="card_promoter", sales_lead={})


def test_unlabelled_exposure_answer_and_spoken_code_are_masked():
    assert "654321" not in redact_authentication("Да, 654321", "exposure")
    assert redact_authentication("77010000001", "exposure") == "77010000001"
    assert "один два три" not in redact_authentication("SMS код один два три четыре пять шесть")
    assert "бір екі үш" not in redact_authentication("растау коды бір екі үш төрт бес алты")


def test_routine_confirmation_is_candidate_but_not_a_high_risk_incident():
    fixture = RiskFixture(security())
    built = services(fixture)
    run = asyncio.run(
        built.messages.risk.analyze(
            "Нужно ли подтверждение по SMS?", active_assistant="card_promoter"
        )
    )
    assert run.assessment.risk_relevant is False
    assert run.assessment.level == "none" and not run.assessment.guidance_shown


@pytest.mark.parametrize("mode", ["card_promoter", "insurance_manager"])
@pytest.mark.parametrize("confidence", [0.4, 0.95])
def test_security_detour_keeps_private_state_result_and_no_hidden_switch_then_continues(
    mode, confidence
):
    fixture = RiskFixture(
        security([RiskSignal.OTP_REQUESTED, RiskSignal.BANK_IMPERSONATION], confidence=confidence)
    )
    built = services(fixture)
    product = ProductFixture()
    built.registry.get("card_promoter").agent = product

    async def flow():
        await built.messages.process("detour", "", mode, start_scenario=True)
        await built.messages.process(
            "detour", "Мне нужен кешбэк" if mode == "card_promoter" else "Поездка в Турцию"
        )
        before = (
            built.dialogs.get_conversation("detour").scenario_contexts[mode].model_copy(deep=True)
        )
        reply = await built.messages.process("detour", "Звонящий из банка просит код из SMS 654321")
        after = built.dialogs.get_conversation("detour")
        assert (
            after.active_scenario_pack == mode and "fraud_security" not in after.scenario_contexts
        )
        assert after.scenario_contexts[mode].state == before.state
        assert after.scenario_contexts[mode].result == before.result
        assert after.scenario_contexts[mode].lifecycle == before.lifecycle
        assert reply.risk.level == "high" and "Не сообщайте" in reply.response_text
        assert reply.trace.pack_switch is None and reply.trace.actions == []
        assert "654321" not in json.dumps(reply.model_dump(mode="json"))
        assert "654321" not in json.dumps(fixture.inputs)
        assert set(fixture.inputs[0]) == {
            "current_text",
            "language",
            "channel",
            "active_assistant",
            "context",
        }
        assert set(fixture.inputs[0]["context"]) == {
            "previous_signals",
            "pending_question",
            "response_language",
        }
        final = await built.messages.process("detour", "Да, продолжим")
        assert final.scenario_pack_id == mode and final.risk is None
        assert final.trace.turn == 4

    asyncio.run(flow())
    if mode == "card_promoter":
        assert len(product.inputs) == 2
    else:
        assert len(built.router.inputs) == 2


@pytest.mark.parametrize(
    "error", [RouterProviderError(timeout=True), RouterProviderError(), RouterOutputError()]
)
def test_risk_failure_keeps_safety_warning_and_business_state_without_fake_assessment(error):
    built = services(RiskFixture(error))
    asyncio.run(built.messages.process("failed", "", "card_promoter", start_scenario=True))
    before = built.dialogs.get_conversation("failed").scenario_contexts["card_promoter"].state
    reply = asyncio.run(built.messages.process("failed", "Мне звонят и просят код из SMS"))
    assert reply.risk.analysis_status != "analyzed" and reply.risk.risk_relevant is None
    assert reply.risk.level == "none" and reply.risk.signals == []
    assert "недоступна" in reply.response_text and "Не сообщайте" in reply.response_text
    assert (
        built.dialogs.get_conversation("failed").scenario_contexts["card_promoter"].state == before
    )


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_specialist_collects_safe_yes_no_then_exposure_handoff(language):
    first = security([RiskSignal.OTP_REQUESTED], language=language, case_type="social_engineering")
    second = security(
        [RiskSignal.OTP_DISCLOSED], language=language, case_type="credential_exposure", answer=True
    )
    second.level, second.recommended_action = "critical", "urgent_security_review"
    fixture, built = RiskFixture(first, second), None
    built = services(fixture)

    async def flow():
        one = await built.messages.process(
            "fraud",
            "SMS код сұрады" if language == "kk" else "Мне просили SMS код",
            "fraud_security",
        )
        assert one.state.pending_question == "exposure" and one.response_text.count("?") == 1
        assert one.trace.pack_switch is None and type(one.scenario_result) is FraudCaseResult
        two = await built.messages.process("fraud", "Иә" if language == "kk" else "Да")
        assert (
            two.conversation_status == "handoff"
            and two.state.fraud_case.case_status == "needs_review"
        )
        assert two.state.fraud_case.risk.level == "critical"
        assert two.response_text.startswith(built.risk.policy.text("exposure_review", language))
        assert "оператор" in two.response_text and two.state.pending_question is None
        assert fixture.inputs[1]["context"]["pending_question"] == "exposure"
        assert set(fixture.inputs[1]["context"]["previous_signals"]) == {
            "otp_requested_by_third_party"
        }

    asyncio.run(flow())


def test_negative_exposure_answer_has_no_repeat_and_explicit_operator_keeps_exact_phrase():
    first = security([RiskSignal.OTP_REQUESTED], case_type="social_engineering")
    negative = security([RiskSignal.OTP_REQUESTED], case_type="social_engineering", answer=False)
    operator = security().model_copy(update={"intent": "operator_request"})
    built = services(RiskFixture(first, negative, operator))
    asyncio.run(built.messages.process("no", "Просят SMS код", "fraud_security"))
    two = asyncio.run(built.messages.process("no", "Нет, ничего не сообщил"))
    assert two.state.pending_question is None and "?" not in two.response_text
    assert RiskSignal.OTP_DISCLOSED not in two.state.fraud_case.facts
    end = asyncio.run(built.messages.process("no", "Дайте оператора"))
    assert end.response_text == "Конечно, передаю диалог оператору."


def test_live_wire_projections_and_manual_selection_keep_risk_additive():
    app = create_app(Settings(_env_file=None), router_override=InsuranceFixture())
    with TestClient(app) as client:
        configure(app.state.services, RiskFixture(security([RiskSignal.OTP_REQUESTED]), security()))
        opened = client.post(
            "/api/conversation/start", json={"session_id": "api", "scenario_mode": "card_promoter"}
        ).json()
        assert "risk" not in opened
        response = client.post(
            "/api/message", json={"session_id": "api", "text": "Просят SMS код", "channel": "voice"}
        )
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "session_id",
            "response_text",
            "routing",
            "state",
            "trace",
            "conversation_status",
            "risk",
        }
        assert body["state"]["sales_lead"]["product_category"] == "card"
        assert body["trace"]["scenario_pack_id"] == "card_promoter"
        selected = client.post(
            "/api/message",
            json={
                "session_id": "api",
                "text": "Как защититься?",
                "scenario_mode": "fraud_security",
            },
        ).json()
        assert selected["trace"]["pack_switch"]["source"] == "explicit"
        assert selected["state"]["fraud_case"]["case_status"] == "informed"


def test_risk_transport_is_one_bounded_tool_free_private_call(monkeypatch):
    from app.packs import structured_agent

    built = build_services(
        Settings(_env_file=None, openai_api_key="test-only", openai_router_model="fixture-model")
    )
    agent = built.messages.risk.agent
    assert isinstance(agent, RiskAgent) and agent.transport.settings.router_timeout_seconds == 8
    AgentOutputSchema(SecurityDecision)
    captured = {}

    async def run(agent, **kwargs):
        captured.update(kwargs)
        assert not agent.tools and not agent.handoffs and agent.model_settings.store is False
        assert agent.model_settings.retry.max_retries == 0
        return SimpleNamespace(final_output=security())

    monkeypatch.setattr(structured_agent.Runner, "run", run)
    monkeypatch.setattr(structured_agent.AsyncOpenAI, "close", AsyncMock())
    asyncio.run(agent.analyze(RiskInput(current_text="SMS", active_assistant="fraud_security")))
    assert captured["max_turns"] == 1 and captured["run_config"].tracing_disabled
    assert captured["run_config"].trace_include_sensitive_data is False


def test_unsafe_extra_signal_actions_or_secret_fields_rejected():
    for update in (
        {"recommended_action": "freeze_account"},
        {"signals": ["fraud_confirmed"]},
        {"otp": "654321"},
    ):
        with pytest.raises(ValidationError):
            SecurityDecision.model_validate(security().model_dump() | update)


@pytest.mark.parametrize(
    ("question", "signals", "answer", "expected", "level"),
    [
        ("exposure", [RiskSignal.OTP_REQUESTED], True, RiskSignal.OTP_DISCLOSED, "critical"),
        (
            "remote_installed",
            [RiskSignal.REMOTE_ACCESS_REQUESTED],
            True,
            RiskSignal.REMOTE_ACCESS_INSTALLED,
            "critical",
        ),
        ("link_exposure", [RiskSignal.SUSPICIOUS_LINK], True, RiskSignal.SUSPICIOUS_LINK, "high"),
        (
            "link_exposure",
            [RiskSignal.SUSPICIOUS_LINK],
            False,
            RiskSignal.SUSPICIOUS_LINK,
            "medium",
        ),
    ],
)
def test_safe_model_answer_follows_pending_question_contract(
    question, signals, answer, expected, level
):
    fixture = RiskFixture(security().model_copy(update={"answer": answer}))
    built = services(fixture)
    run = asyncio.run(
        built.messages.risk.analyze(
            "Короткий ответ",
            active_assistant="fraud_security",
            context=RiskContext(previous_signals=signals, pending_question=question),
        )
    )
    assert expected in run.assessment.signals and run.assessment.level == level
    assert run.decision.intent == "concern"
    if question == "link_exposure":
        assert RiskSignal.CREDENTIAL_DISCLOSED not in run.assessment.signals


def test_early_precaution_has_no_model_session_or_risk_verdict():
    app = create_app(Settings(_env_file=None), router_override=InsuranceFixture())
    with TestClient(app) as client:
        fixture = RiskFixture()
        configure(app.state.services, fixture)
        response = client.post(
            "/api/security/precaution",
            json={"text": "Позвонили и просят SMS код", "response_language": "ru"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "response_text": app.state.services.risk.policy.text("do_not_share_secrets", "ru"),
            "response_language": "ru",
        }
        assert not fixture.inputs
        assert app.state.services.dialogs.get_conversation("anything") is None
        harmless = client.post(
            "/api/security/precaution", json={"text": "Хочу депозит на год"}
        ).json()
        assert harmless["response_text"] == ""


def test_warning_preserves_completed_lead_lifecycle():
    built = services(RiskFixture(security([RiskSignal.OTP_REQUESTED])))
    asyncio.run(built.messages.process("complete", "", "card_promoter", start_scenario=True))
    conversation = built.dialogs.get_conversation("complete")
    entry = conversation.scenario_contexts["card_promoter"]
    entry.lifecycle, entry.state.completed, entry.result.completed = "completed", True, True
    entry.public_state.completed = True
    entry.public_state.sales_lead.completed = True
    built.dialogs.save_conversation(conversation)
    before = entry.model_copy(deep=True)
    asyncio.run(built.messages.process("complete", "Звонящий просит SMS код"))
    after = built.dialogs.get_conversation("complete").scenario_contexts["card_promoter"]
    assert (
        after.lifecycle == "completed"
        and after.state == before.state
        and after.result == before.result
    )
