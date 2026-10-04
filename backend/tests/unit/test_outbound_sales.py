"""Campaign authority, grounded offers and bounded refusal behavior."""

import asyncio

import pytest

from app.core.config import Settings
from app.packs.contracts import GlobalConversationContext
from app.packs.product_promoter.agent import ProductAgent
from app.packs.product_promoter.catalog import load_catalog, matching_products
from app.packs.product_promoter.models import Preferences, ProductDecision
from app.packs.product_promoter.pack import ProductPromoterPack


class SalesFixture:
    def __init__(self, *decisions):
        self.decisions = list(decisions)

    async def decide(self, text, context):
        return self.decisions.pop(0).model_copy(deep=True)


def decision(intent, **values):
    return ProductDecision(intent=intent, language="ru", response_language="ru", **values)


def pack(campaign="deposit", *decisions):
    return ProductPromoterPack(
        load_catalog(Settings(_env_file=None).product_catalog_path),
        SalesFixture(*decisions),
        campaign=campaign,
    )


def opened(sales):
    return asyncio.run(
        sales.open_turn(GlobalConversationContext(session_id="sales"), sales.new_context())
    )


def turn(sales, context):
    return asyncio.run(
        sales.handle_turn(
            "fictional customer reply", GlobalConversationContext(session_id="sales"), context
        )
    )


@pytest.mark.parametrize(
    "campaign,mode,prefix",
    [
        ("deposit", "product_promoter", "DEP-"),
        ("card", "card_promoter", "CARD-"),
        ("loan", "loan_promoter", "LOAN-"),
    ],
)
def test_bot_starts_assigned_offer_before_any_customer_reply(campaign, mode, prefix):
    sales = pack(campaign)
    first = opened(sales)
    assert first.public_state.scenario_mode == mode
    assert first.context.campaign == first.context.product_category == campaign
    assert first.context.last_question == "offer_details"
    assert first.context.recommended_product_id.startswith(prefix)
    assert first.response_text.count("?") == 3
    assert "Звоню" in first.response_text and "Merei Demo Bank" in first.response_text
    assert "консультант" not in first.response_text and "или карту" not in first.response_text
    assert first.trace.source_keys and first.trace.transcript == ""
    assert not sales.agent.decisions


def test_opening_question_explains_steps_of_the_previously_offered_product():
    sales = pack("deposit", decision("opening_question"))
    first = opened(sales)
    following = turn(sales, first.context)
    assert following.context.recommended_product_id == "DEP-FLEX"
    assert following.context.sales_phase == "opening"
    assert following.result.outcome == "consulting" and not following.result.completed
    product = following.public_state.products[0]
    assert product.id == "DEP-FLEX"
    assert all(step in following.response_text for step in product.opening_steps_ru)
    assert "14,93" not in following.response_text


def test_rate_question_is_focused_and_keeps_offered_product_without_new_consent():
    sales = pack("deposit", decision("conditions_question", question_topic="rate"))
    following = turn(sales, opened(sales).context)
    assert "10,47" in following.response_text and "10 процентов" in following.response_text
    assert following.response_text.startswith("Ставка —")
    assert (
        "Проверьте" not in following.response_text
        and "Расскажу об этом варианте" not in following.response_text
    )
    assert "досрочном" not in following.response_text and "минимум" not in following.response_text
    assert following.context.last_question == "opening_offer"
    assert not following.result.completed


def test_model_interest_without_preferences_follows_the_previous_offer_step():
    sales = pack(
        "deposit",
        decision("deposit_interest", accepts_explanation=True),
        decision("deposit_interest", accepts_explanation=True),
    )
    explanation = turn(sales, opened(sales).context)
    assert explanation.routing.intent == "conditions_question"
    assert explanation.context.last_question == "opening_offer"
    instructions = turn(sales, explanation.context)
    assert instructions.routing.intent == "opening_question"
    assert instructions.context.sales_phase == "opening" and not instructions.result.completed
    assert "model=deposit_interest" in instructions.trace.reason


@pytest.mark.parametrize("intent", ["conditions_question", "general_discovery"])
def test_accepting_opening_explanation_does_not_repeat_conditions_or_create_application(intent):
    sales = pack(
        "deposit",
        decision("conditions_question"),
        decision(intent, accepts_explanation=True),
    )
    explained = turn(sales, opened(sales).context)
    following = turn(sales, explained.context)
    assert following.routing.intent == "opening_question"
    assert following.context.sales_phase == "opening"
    assert not following.result.completed and following.result.outcome == "consulting"
    assert "«Депозиты»" in following.response_text


def test_generic_product_interest_is_still_preference_discovery_not_implicit_acceptance():
    sales = pack("deposit", decision("deposit_interest"))
    following = turn(sales, opened(sales).context)
    assert following.routing.intent == "deposit_interest"
    assert following.context.last_question == "liquidity"


def test_model_information_focus_takes_priority_over_another_needs_survey():
    sales = pack("deposit", decision("deposit_interest", question_topic="rate"))
    following = turn(sales, opened(sales).context)
    assert following.routing.intent == "conditions_question"
    assert "10,47" in following.response_text and following.context.last_question == "opening_offer"


def test_first_refusal_can_be_reconsidered_but_later_refusal_is_final():
    sales = pack(
        "deposit", decision("decline"), decision("conditions_question"), decision("decline")
    )
    first = turn(sales, opened(sales).context)
    assert first.context.refusal_count == 1 and first.context.sales_phase == "refusal_check"
    assert first.response_text.count("?") == 1 and not first.result.completed
    interested = turn(sales, first.context)
    assert interested.context.refusal_count == 1 and interested.context.sales_phase == "conditions"
    final = turn(sales, interested.context)
    assert final.result.outcome == "declined" and final.result.status == "ended"
    assert final.result.completed and "?" not in final.response_text


def test_explicit_do_not_call_request_stops_immediately_without_an_extra_pitch():
    sales = pack("deposit", decision("decline", stop_sales=True))
    final = turn(sales, opened(sales).context)
    assert final.result.status == "ended" and final.context.refusal_count == 1
    assert final.result.outcome == "declined" and "?" not in final.response_text


@pytest.mark.parametrize(
    "customer_decision",
    [
        decision("card_interest"),
        decision("card_interest", category="card", preferences=Preferences(cashback=True)),
        decision("conditions_question", product_ids=["CARD-REWARD"]),
        decision("loan_interest", category="loan"),
    ],
)
def test_customer_cannot_select_a_different_campaign_or_overwrite_preferences(customer_decision):
    sales = pack("deposit", customer_decision)
    first = opened(sales)
    following = turn(sales, first.context)
    assert following.context.product_category == following.context.campaign == "deposit"
    assert following.routing.intent == "out_of_scope"
    assert following.context.recommended_product_id == "DEP-FLEX"
    assert following.context.preferences.cashback is None and not following.public_state.products


def test_agent_receives_only_assigned_campaign_catalog_names():
    catalog = load_catalog(Settings(_env_file=None).product_catalog_path)
    agent = ProductAgent(Settings(_env_file=None), catalog)
    sales = pack("card")
    captured = []

    async def observe(payload):
        captured.append(payload)
        return decision("conditions_question")

    agent.transport.run = observe
    asyncio.run(agent.decide("Расскажите условия", sales.new_context()))
    assert captured[0]["scenario_context"]["campaign"] == "card"
    assert all(p["category"] == "card" for p in captured[0]["public_products"])
    assert "loan" not in {p["category"] for p in captured[0]["public_products"]}


def test_loan_matching_respects_amount_term_and_does_not_perform_approval():
    catalog = load_catalog(Settings(_env_file=None).product_catalog_path)
    assert (
        matching_products(catalog, "loan", Preferences(amount=400000, currency="KZT"))[0].id
        == "LOAN-DIGITAL"
    )
    assert matching_products(catalog, "loan", Preferences(amount=4000000, currency="KZT")) == []
    assert matching_products(catalog, "loan", Preferences(currency="USD")) == []
    sales = pack(
        "loan", decision("loan_interest", preferences=Preferences(amount=400000, currency="KZT"))
    )
    following = turn(sales, opened(sales).context)
    assert following.context.campaign == "loan"
    assert "Решение по заявке принимает банк" in following.response_text
    assert following.result.outcome == "consulting" and not following.result.completed
