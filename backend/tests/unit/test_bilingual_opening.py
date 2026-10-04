"""Offline opening/continuity checks with structured model fixtures, not live quality scores."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.conversation.opening import BILINGUAL_OPENING
from app.core.config import Settings
from app.core.services import build_services
from app.packs.insurance_manager.agent.schemas import RouterDecision
from app.packs.product_promoter.models import ProductDecision
from app.risk.models import SecurityDecision

MODES = [
    "insurance_manager",
    "fraud_security",
    "product_promoter",
    "card_promoter",
    "loan_promoter",
]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("first_language", ["kk", "ru", "mixed"])
def test_proactive_bilingual_opening_then_dynamic_customer_language(mode, first_language):
    built = build_services(Settings(_env_file=None))
    pack = built.registry.get(mode)
    languages = [
        first_language,
        "ru" if first_language != "ru" else "kk",
        "kk" if first_language != "ru" else "ru",
    ]
    replies = ["kk" if lang == "mixed" else lang for lang in languages]
    if mode == "insurance_manager":
        pack.processor.router = AsyncMock()
        pack.processor.router.route.side_effect = [
            RouterDecision(
                language=lang,
                response_language=reply,
                scenarios=[dict(scenario_id="SC06", confidence=0.99, reason="Offline fixture")],
            )
            for lang, reply in zip(languages, replies, strict=True)
        ]
    elif mode == "fraud_security":
        pack.intelligence.agent = AsyncMock()
        pack.intelligence.agent.analyze.side_effect = [
            SecurityDecision(
                intent="general_info",
                language=lang,
                response_language=reply,
                risk_relevant=False,
                level="none",
                signals=[],
                recommended_action="none",
            )
            for lang, reply in zip(languages, replies, strict=True)
        ]
    else:
        pack.agent = AsyncMock()
        pack.agent.decide.side_effect = [
            ProductDecision(intent="conditions_question", language=lang, response_language=reply)
            for lang, reply in zip(languages, replies, strict=True)
        ]

    async def flow():
        opening = await built.messages.process("bilingual", "", mode, start_scenario=True)
        assert opening.response_text.startswith(BILINGUAL_OPENING)
        assert BILINGUAL_OPENING == (
            "Сәлеметсіз бе! Сізге қалай көмектесе аламын? Здравствуйте! Чем я могу вам помочь?"
        )
        assert opening.response_text.index("Сәлеметсіз") < opening.response_text.index(
            "Здравствуйте"
        )
        for forbidden in [
            "Which language",
            "На каком языке",
            "Қай тілде",
            "выберите язык",
            "тілді таңда",
        ]:
            assert forbidden.casefold() not in opening.response_text.casefold()
        assert getattr(opening.state, "preferred_response_language", None) is None
        texts = {
            "kk": "Маған шарттары туралы айтып беріңіз",
            "ru": "Я хочу узнать условия этого продукта",
            "mixed": "Маған условия туралы айтып беріңіз",
        }
        for lang, reply in zip(languages, replies, strict=True):
            turn = await built.messages.process("bilingual", texts[lang])
            assert turn.state.response_language == reply
            assert turn.routing.response_language == reply
            assert turn.routing.language == lang
            assert BILINGUAL_OPENING not in turn.response_text
            assert turn.conversation_status not in {"handoff", "ended"}
            assert getattr(turn.state, "preferred_response_language", None) is None

    asyncio.run(flow())


@pytest.mark.parametrize("recent", ["kk", "ru"])
def test_combined_opener_switching_and_terminal_continuity(recent):
    built = build_services(Settings(_env_file=None))
    agent = AsyncMock()
    built.registry.get("fraud_security").intelligence.agent = agent
    agent.analyze.side_effect = [
        SecurityDecision(
            intent="general_info",
            language="kk",
            response_language="kk",
            risk_relevant=False,
            level="none",
            recommended_action="none",
        ),
        SecurityDecision(
            intent="general_info",
            language=recent,
            response_language=recent,
            risk_relevant=False,
            level="none",
            recommended_action="none",
        ),
        SecurityDecision(
            intent="goodbye",
            language="ru" if recent == "kk" else "kk",
            response_language="ru" if recent == "kk" else "kk",
            risk_relevant=False,
            level="none",
            recommended_action="none",
        ),
    ]

    async def flow():
        opener = await built.messages.process("combined", "", "fraud_security", start_scenario=True)
        assert opener.response_text.startswith(BILINGUAL_OPENING)
        await built.messages.process("combined", "Маған қауіпсіздік туралы айтып беріңіз")
        switched = await built.messages.process(
            "combined",
            "Я хочу узнать как защитить мой аккаунт"
            if recent == "ru"
            else "Маған қауіпсіздік туралы тағы айтып беріңіз",
        )
        assert switched.state.response_language == recent
        closed = await built.messages.process("combined", "Рахмет" if recent == "kk" else "Спасибо")
        assert closed.conversation_status == "ended"
        assert closed.state.response_language == recent
        assert closed.response_text == ("Сау болыңыз!" if recent == "kk" else "До свидания!")
        assert BILINGUAL_OPENING not in closed.response_text

    asyncio.run(flow())


def test_combined_bilingual_opener_and_review_required_farewell():
    from app.risk.models import RiskSignal

    built = build_services(Settings(_env_file=None))
    agent = AsyncMock()
    built.registry.get("fraud_security").intelligence.agent = agent
    agent.analyze.return_value = SecurityDecision(
        intent="goodbye",
        language="kk",
        response_language="kk",
        risk_relevant=True,
        level="high",
        signals=[RiskSignal.ACCOUNT_TAKEOVER],
        recommended_action="security_review",
    )

    async def flow():
        opening = await built.messages.process(
            "combined-risk", "", "fraud_security", start_scenario=True
        )
        assert opening.response_text.startswith(BILINGUAL_OPENING)
        result = await built.messages.process(
            "combined-risk", "Менің аккаунтыма басқа адам кірді, сау болыңыз"
        )
        assert result.conversation_status == "handoff"
        assert result.state.response_language == "kk"
        assert result.response_text.endswith("Әрине, диалогты операторға тапсырамын.")
        assert BILINGUAL_OPENING not in result.response_text

    asyncio.run(flow())
