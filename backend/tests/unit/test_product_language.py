"""Application language policy against deliberately wrong model labels, all campaigns."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.core.services import build_services
from app.packs.contracts import GlobalConversationContext
from app.packs.product_promoter.catalog import load_catalog
from app.packs.product_promoter.models import ProductDecision
from app.packs.product_promoter.pack import ProductPromoterPack
from app.risk.models import RiskSignal, SecurityDecision

CASES = json.loads(
    (Path(__file__).resolve().parents[3] / "data/product_promoter/language_regressions.json")
    .resolve()
    .read_text(encoding="utf-8")
)


def opened(campaign, language="ru"):
    agent = AsyncMock()
    pack = ProductPromoterPack(
        load_catalog(Settings(_env_file=None).product_catalog_path), agent, campaign=campaign
    )
    global_context = GlobalConversationContext(session_id="language-fixture", language=language)
    turn = asyncio.run(pack.open_turn(global_context, pack.new_context()))
    return pack, agent, global_context, turn.context


@pytest.mark.parametrize("campaign", ["deposit", "card", "loan"])
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_evidence_and_continuity_override_wrong_model(campaign, case):
    pack, agent, global_context, context = opened(campaign, case["prior"])
    agent.decide.return_value = ProductDecision(
        intent=f"{campaign}_interest", language=case["model"], response_language=case["model"]
    )
    turn = asyncio.run(pack.handle_turn(case["text"], global_context, context))
    assert turn.context.response_language == case["expected"]
    assert turn.routing.response_language == case["expected"]
    assert turn.public_state.response_language == case["expected"]
    assert turn.response_text == pack._question(turn.context.last_question, case["expected"])


@pytest.mark.parametrize(
    "campaign,question", [("deposit", "liquidity"), ("card", "card_priority"), ("loan", "amount")]
)
@pytest.mark.parametrize(
    "text,language",
    [
        ("ответь на русском", "ru"),
        ("ответьте на русском", "ru"),
        ("говорите по-русски", "ru"),
        ("можно на русском?", "ru"),
        ("давайте на русском", "ru"),
        ("қазақша жауап беріңіз", "kk"),
        ("қазақша сөйлейік", "kk"),
    ],
)
def test_explicit_request_preserves_pending_sales_step(campaign, question, text, language):
    pack, agent, global_context, context = opened(campaign, "kk" if language == "ru" else "ru")
    context.last_question = question
    context.sales_phase = "needs"
    context.preferences.amount = 100000
    context.customer_turns = 2
    before = context.model_dump()
    turn = asyncio.run(pack.handle_turn(text, global_context, context))
    assert turn.context.preferred_response_language == language
    assert turn.response_text == pack._question(question, language)
    assert turn.routing.kind == "language_control"
    agent.decide.assert_not_called()
    for key in before.keys() - {
        "response_language",
        "preferred_response_language",
        "last_assistant_text",
        "last_question_text",
    }:
        assert turn.context.model_dump()[key] == before[key], key


@pytest.mark.parametrize("campaign", ["deposit", "card", "loan"])
def test_preference_persists_and_can_be_changed(campaign):
    pack, agent, global_context, context = opened(campaign)
    for requested, request, next_text in [
        ("kk", "қазақша жауап беріңіз", "меня интересуют условия"),
        ("ru", "ответьте на русском", "Маған шарттар туралы айтып беріңіз"),
    ]:
        turn = asyncio.run(pack.handle_turn(request, global_context, context))
        agent.decide.return_value = ProductDecision(
            intent="conditions_question",
            language="ru" if requested == "kk" else "kk",
            response_language="ru" if requested == "kk" else "kk",
        )
        turn = asyncio.run(pack.handle_turn(next_text, global_context, turn.context))
        assert turn.context.preferred_response_language == requested
        assert turn.routing.response_language == requested
        assert turn.public_state.response_language == requested
        context = turn.context


@pytest.mark.parametrize("mode", ["product_promoter", "card_promoter", "loan_promoter"])
@pytest.mark.parametrize("preferred", ["ru", "kk"])
def test_core_preference_survives_risk_detour_and_business_resumes(mode, preferred):
    built = build_services(Settings(_env_file=None))
    other = "kk" if preferred == "ru" else "ru"
    built.messages.risk.agent = AsyncMock()
    built.messages.risk.agent.analyze.return_value = SecurityDecision(
        intent="concern",
        language=other,
        response_language=other,
        risk_relevant=True,
        level="high",
        signals=[RiskSignal.OTP_REQUESTED],
        recommended_action="security_review",
    )
    pack = built.registry.get(mode)
    pack.agent = AsyncMock()
    pack.agent.decide.return_value = ProductDecision(
        intent="conditions_question",
        language=other,
        response_language=other,
    )

    async def flow():
        await built.messages.process("preference", "", mode, start_scenario=True)
        control = await built.messages.process(
            "preference", "ответь на русском" if preferred == "ru" else "қазақша жауап беріңіз"
        )
        assert control.routing.kind == "language_control"
        before = built.dialogs.get_conversation("preference").scenario_contexts[mode].state
        reply = await built.messages.process("preference", "Звонящий просит код из SMS")
        assert reply.routing.response_language == preferred
        assert reply.state.preferred_response_language == preferred
        assert reply.response_text.startswith(
            built.risk.policy.text("do_not_share_secrets", preferred)
        )
        after = built.dialogs.get_conversation("preference").scenario_contexts[mode].state
        assert after == before
        next_reply = await built.messages.process("preference", "Расскажите об условиях")
        assert next_reply.state.response_language == preferred
        assert next_reply.state.preferred_response_language == preferred
        assert next_reply.scenario_pack_id == mode

    asyncio.run(flow())


@pytest.mark.parametrize(
    "text",
    [
        "Не отвечайте на русском",
        "Он сказал: ответь на русском",
        "Депозит на русском сайте",
    ],
)
def test_language_control_does_not_swallow_business_or_quoted_text(text):
    from app.conversation.language import language_request

    assert language_request(text) == (None, text)


def test_language_control_with_business_clause_still_processes_business():
    pack, agent, global_context, context = opened("deposit", "kk")
    agent.decide.return_value = ProductDecision(
        intent="conditions_question",
        language="kk",
        response_language="kk",
    )
    turn = asyncio.run(
        pack.handle_turn("Ответьте на русском. Какие условия?", global_context, context)
    )
    assert agent.decide.call_args.args[0] == "Какие условия?"
    assert turn.context.preferred_response_language == "ru"
    assert turn.context.customer_turns == 1
    assert turn.routing.response_language == "ru"
