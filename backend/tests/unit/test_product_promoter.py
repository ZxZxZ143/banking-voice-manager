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
from app.packs.contracts import GlobalConversationContext
from app.packs.product_promoter.agent import ProductAgent
from app.packs.product_promoter.catalog import conditions, load_catalog, matching_products
from app.packs.product_promoter.models import (
    Preferences,
    ProductCatalog,
    ProductDecision,
    ProductScenarioContext,
    SalesLeadResult,
)
from app.packs.product_promoter.pack import ProductPromoterPack
from app.packs.product_promoter.presentation import money, spoken_currency, spoken_summary
from app.packs.selector import PackSelection, ScenarioSelector
from app.packs.structured_agent import StructuredAgent


def catalog():
    return load_catalog(Settings(_env_file=None).product_catalog_path)


def decision(intent, **kwargs):
    return ProductDecision(intent=intent, language="ru", response_language="ru", **kwargs)


class ProductFixture:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.inputs = []

    async def decide(self, text, context):
        self.inputs.append((text, context.model_copy(deep=True)))
        result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result.model_copy(deep=True)


class InsuranceFixture:
    def __init__(self, *ids):
        self.ids = list(ids or ["SC06"])
        self.inputs = []

    async def route(self, text, state):
        self.inputs.append((text, state.model_copy(deep=True)))
        return RouterDecision(
            language="ru",
            slots={"trip_country": "Турция"},
            scenarios=[dict(scenario_id=self.ids.pop(0), confidence=0.99, reason="fixture")],
        )


class SelectorFixture:
    def __init__(self, target):
        self.target = target
        self.inputs = []

    async def select(self, *args):
        self.inputs.append(args)
        if isinstance(self.target, Exception):
            raise self.target
        return PackSelection(target_pack_id=self.target, confidence=0.99, response_language="ru")


def handle(agent, context=None):
    return asyncio.run(
        ProductPromoterPack(catalog(), agent).handle_turn(
            "synthetic test text",
            GlobalConversationContext(session_id="unit"),
            context or ProductScenarioContext(),
        )
    )


@pytest.mark.parametrize("language", ["ru", "kk"])
@pytest.mark.parametrize("index", range(6))
def test_all_condition_values_are_rendered_from_source(index, language):
    product = catalog().products[index]
    reply = conditions(product, language)
    assert product.id in reply and product.reference_date in reply
    assert (product.restrictions_ru if language == "ru" else product.restrictions_kk) in reply
    if product.category == "deposit":
        for value in (
            product.nominal_rate_percent,
            product.effective_rate_percent,
            product.minimum_amount,
        ):
            assert f"{value:g}" in reply
        assert (
            product.early_termination_ru if language == "ru" else product.early_termination_kk
        ) in reply
    else:
        for value in (
            product.monthly_fee_kzt,
            product.cashback_percent,
            product.cashback_limit_kzt,
            product.atm_free_limit_kzt,
            product.atm_above_limit_percent,
        ):
            assert f"{value:g}" in reply


def test_catalog_is_synthetic_complete_and_unique():
    source = catalog().model_dump()
    assert source["synthetic"] is True and source["brand"] == "Merei Demo Bank"
    source["products"][1]["id"] = source["products"][0]["id"]
    with pytest.raises(ValidationError):
        ProductCatalog.model_validate(source)
    source = catalog().model_dump()
    source["products"][0]["effective_rate_percent"] = None
    with pytest.raises(ValidationError):
        ProductCatalog.model_validate(source)


@pytest.mark.parametrize("extra", ["income", "iin", "health", "religion", "insurance_slots"])
def test_preferences_forbid_sensitive_or_other_pack_fields(extra):
    with pytest.raises(ValidationError):
        Preferences.model_validate({extra: "not stored"})


@pytest.mark.parametrize(
    "prefs,expected",
    [
        ({"liquidity": True}, "DEP-FLEX"),
        ({"liquidity": False, "amount": 200000, "currency": "KZT"}, "DEP-SAVE"),
        ({"currency": "USD"}, "DEP-USD"),
        ({"amount": 5000, "currency": "KZT"}, None),
        ({"currency": "USD", "liquidity": True}, None),
    ],
)
def test_explainable_deposit_matching(prefs, expected):
    matches = matching_products(catalog(), "deposit", Preferences(**prefs))
    assert (matches[0].id if matches else None) == expected


@pytest.mark.parametrize(
    "prefs,expected",
    [
        ({"cashback": True}, "CARD-REWARD"),
        ({"cashback": True, "fee_sensitive": True}, "CARD-DAILY"),
        ({"cash_withdrawal": True}, "CARD-CASH"),
        ({"digital_only": True, "cash_withdrawal": True}, "CARD-DAILY"),
    ],
)
def test_explainable_card_matching(prefs, expected):
    assert matching_products(catalog(), "card", Preferences(**prefs))[0].id == expected


@pytest.mark.parametrize(
    "intent,question",
    [
        ("general_discovery", "category"),
        ("deposit_interest", "liquidity"),
        ("card_interest", "card_priority"),
    ],
)
def test_one_useful_discovery_question(intent, question):
    turn = handle(ProductFixture(decision(intent)))
    assert turn.context.last_question == question
    assert turn.response_text.count("?") == 1 and not turn.public_state.products


def test_multi_turn_preferences_conditions_objection_and_explicit_interest():
    fixture = ProductFixture(
        decision("deposit_interest"),
        decision(
            "deposit_interest",
            preferences=Preferences(liquidity=True, amount=50000, currency="KZT"),
        ),
        decision("objection", objection="yield"),
        decision("application_interest", next_action="callback_requested"),
    )
    pack = ProductPromoterPack(catalog(), fixture)
    context = pack.new_context()
    for number in range(4):
        turn = asyncio.run(
            pack.handle_turn(
                "test", GlobalConversationContext(session_id="flow", turn_number=number), context
            )
        )
        context = turn.context
    assert turn.result.outcome == "interested"
    assert turn.result.selected_product_id == "DEP-FLEX"
    assert turn.result.customer_preferences.amount == 50000
    assert turn.result.objections == ["yield"]
    assert turn.result.next_action == "callback_requested"
    assert turn.result.completed and turn.result.status == "active" and turn.complete_pack
    assert "звонок не назначен" in turn.response_text


def test_comparison_includes_different_restrictions_and_keeps_grounding():
    context = ProductScenarioContext(
        product_category="deposit", preferences=Preferences(liquidity=True)
    )
    turn = handle(ProductFixture(decision("product_comparison")), context)
    assert turn.result.compared_products == ["DEP-FLEX", "DEP-SAVE"]
    assert len(turn.public_state.products) == 2
    for product in turn.public_state.products:
        assert spoken_summary(product, "ru") in turn.response_text
    assert "10,47 процента" in turn.response_text and "14,93 процента" in turn.response_text
    assert "30 календарных дней" in turn.response_text
    assert "отличаются ставка и доступ к деньгам" in turn.response_text


def test_named_conditions_skip_unneeded_discovery_without_claiming_match():
    turn = handle(ProductFixture(decision("conditions_question", product_ids=["CARD-REWARD"])))
    assert "700 тенге в месяц" in turn.response_text
    assert turn.context.last_question == "next_action"
    assert "подходят ли вам его ограничения" in turn.response_text


def test_decline_stops_pitch_and_neutral_followup_does_not_restart():
    first = handle(ProductFixture(decision("decline")))
    second = handle(ProductFixture(decision("general_discovery")), first.context)
    for turn in (first, second):
        assert turn.result.interest_level == "declined" and turn.result.status == "active"
        assert turn.result.completed and not turn.public_state.products
        assert "?" not in turn.response_text


@pytest.mark.parametrize("language", ["ru", "kk", "mixed"])
@pytest.mark.parametrize("intent,status", [("operator_request", "handoff"), ("goodbye", "ended")])
def test_terminal_replies(language, intent, status):
    reply_language = "kk" if language == "kk" else "ru"
    turn = handle(
        ProductFixture(
            ProductDecision(intent=intent, language=language, response_language=reply_language)
        ),
        ProductScenarioContext(last_question="category"),
    )
    assert turn.result.status == status and turn.complete_pack
    assert not turn.trace.clarification and turn.context.last_question is None
    if status == "handoff":
        assert turn.response_text == (
            "Әрине, диалогты операторға тапсырамын."
            if language == "kk"
            else "Конечно, передаю диалог оператору."
        )


@pytest.mark.parametrize(
    "bad", [RouterOutputError(), decision("conditions_question", product_ids=["NOT-REGISTERED"])]
)
def test_invalid_output_is_safe_and_bounded(bad):
    fixture = ProductFixture(bad, bad, bad)
    pack = ProductPromoterPack(catalog(), fixture)
    context = pack.new_context()
    for number in range(3):
        turn = asyncio.run(
            pack.handle_turn(
                "test", GlobalConversationContext(session_id="bad", turn_number=number), context
            )
        )
        assert not turn.public_state.products and not turn.result.selected_product_id
        assert turn.trace.clarification is (number < 2)
        context = turn.context
    assert turn.result.status == "handoff"


def test_agent_and_selector_sdk_schemas_and_narrow_inputs():
    for schema in (ProductDecision, PackSelection):
        assert AgentOutputSchema(schema).json_schema()["additionalProperties"] is False
    product_agent = ProductAgent(Settings(_env_file=None), catalog())
    selector = ScenarioSelector(Settings(_env_file=None))
    captured = []

    async def product_run(payload):
        captured.append(payload)
        return decision("general_discovery")

    async def selector_run(payload):
        captured.append(payload)
        return PackSelection(target_pack_id=None, confidence=1, response_language="ru")

    product_agent.transport.run = product_run
    selector.transport.run = selector_run
    asyncio.run(product_agent.decide("current", ProductScenarioContext()))
    asyncio.run(selector.select("current", "product_promoter", [{"id": "insurance_manager"}], "ru"))
    assert set(captured[0]) == {"scenario_context", "public_products", "current_text"}
    assert set(captured[1]) == {
        "current_text",
        "current_pack_id",
        "public_pack_descriptions",
        "global_language",
    }
    assert "insurance_slots" not in json.dumps(captured)


def test_real_packs_switch_resume_and_keep_local_state_results_isolated():
    insurance = InsuranceFixture("SC06", "SC06")
    built = build_services(Settings(_env_file=None), router_override=insurance)
    promoter = built.registry.get("product_promoter")
    promoter.agent = ProductFixture(
        decision("deposit_interest"),
        decision("deposit_interest", preferences=Preferences(liquidity=True)),
    )

    async def flow():
        await built.messages.process("isolation", "insurance")
        original = (
            built.dialogs.get_conversation("isolation")
            .scenario_contexts["insurance_manager"]
            .model_copy(deep=True)
        )
        await built.messages.process("isolation", "product", "product_promoter")
        both = built.dialogs.get_conversation("isolation")
        assert both.scenario_contexts["insurance_manager"].state == original.state
        assert both.scenario_contexts["insurance_manager"].result == original.result
        product = both.scenario_contexts["product_promoter"].model_copy(deep=True)
        back = await built.messages.process(
            "isolation", "insurance continuation", "insurance_manager"
        )
        assert back.trace.context_lifecycle == "resumed"
        assert (
            built.dialogs.get_conversation("isolation").scenario_contexts["product_promoter"].state
            == product.state
        )
        final = await built.messages.process("isolation", "yes liquidity", "product_promoter")
        assert final.trace.context_lifecycle == "resumed"
        assert final.state.product_category == "deposit" and final.state.preferences.liquidity
        assert final.trace.pack_switch.from_pack == "insurance_manager"
        # Default turns continue the current pack, rather than implicitly switching back.
        promoter.agent = ProductFixture(decision("decline"))
        default = await built.messages.process("isolation", "decline")
        assert default.scenario_pack_id == "product_promoter"

    asyncio.run(flow())
    assert not hasattr(promoter.agent.inputs[0][1], "slots")
    assert all(not hasattr(state, "product_category") for _, state in insurance.inputs)


@pytest.mark.parametrize("failure", [RouterProviderError(), RouterProviderError(timeout=True)])
def test_failed_pack_switch_rolls_back_all_contexts_and_trace(failure):
    built = build_services(Settings(_env_file=None), router_override=InsuranceFixture())
    built.registry.get("product_promoter").agent = ProductFixture(failure)
    asyncio.run(built.messages.process("rollback", "insurance"))
    before = built.dialogs.get_conversation("rollback")
    with pytest.raises(RouterProviderError):
        asyncio.run(built.messages.process("rollback", "product", "product_promoter"))
    assert built.dialogs.get_conversation("rollback") == before


def test_out_of_scope_never_calls_selector_and_manual_switch_preserves_insurance():
    built = build_services(
        Settings(_env_file=None),
        router_override=InsuranceFixture("SC06", "SYS_OUT_OF_SCOPE", "SC06"),
    )
    built.messages.selector = SelectorFixture(RouterProviderError())
    product = ProductFixture(decision("deposit_interest"))
    built.registry.get("product_promoter").agent = product

    async def flow():
        await built.messages.process("manual-only", "insurance")
        turn = await built.messages.process("manual-only", "Хочу депозит")
        assert turn.scenario_pack_id == "insurance_manager"
        assert turn.trace.pack_switch is None and not built.messages.selector.inputs
        before = (
            built.dialogs.get_conversation("manual-only")
            .scenario_contexts["insurance_manager"]
            .state
        )
        selected = await built.messages.process("manual-only", "Хочу депозит", "product_promoter")
        assert selected.trace.pack_switch.source == "explicit"
        assert product.inputs[0][0] == "Хочу депозит"
        assert (
            built.dialogs.get_conversation("manual-only")
            .scenario_contexts["insurance_manager"]
            .state
            == before
        )
        resumed = await built.messages.process("manual-only", "продолжим", "insurance_manager")
        assert resumed.state.active_scenario == "SC06"

    asyncio.run(flow())


def test_product_api_contract_and_unknown_switch_does_not_mutate():
    app = create_app(Settings(_env_file=None), router_override=InsuranceFixture())
    with TestClient(app) as client:
        app.state.services.registry.get("product_promoter").agent = ProductFixture(
            decision("card_interest", preferences=Preferences(cashback=True))
        )
        response = client.post(
            "/api/message",
            json={
                "session_id": "api-product",
                "text": "cashback",
                "scenario_mode": "product_promoter",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {
            "session_id",
            "response_text",
            "routing",
            "state",
            "trace",
            "conversation_status",
        }
        SalesLeadResult.model_validate(body["state"]["sales_lead"])
        assert body["trace"]["interaction_mode"] == "proactive"
        assert body["state"]["products"][0]["id"] == "CARD-REWARD"
        before = app.state.services.dialogs.get_conversation("api-product")
        unknown = client.post(
            "/api/message",
            json={"session_id": "api-product", "text": "test", "scenario_mode": "../../evil"},
        )
        assert unknown.status_code == 422
        assert app.state.services.dialogs.get_conversation("api-product") == before


@pytest.mark.parametrize("failure", [None, TimeoutError(), ValueError("invalid output")])
def test_new_sdk_transport_is_single_bounded_call_without_retries_or_memory(monkeypatch, failure):
    clients = []

    class OfflineClient:
        def __init__(self, **options):
            self.options = options
            self.closed = False
            clients.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

    run = AsyncMock(
        return_value=SimpleNamespace(final_output=decision("deposit_interest")), side_effect=failure
    )
    monkeypatch.setattr("app.packs.structured_agent.AsyncOpenAI", OfflineClient)
    monkeypatch.setattr("app.packs.structured_agent.Runner.run", run)
    settings = Settings(
        _env_file=None, openai_api_key="offline-test-key", openai_router_model="fixture"
    )
    agent = StructuredAgent(settings, "Fixture", "Fixture instructions", ProductDecision)
    if failure:
        with pytest.raises(
            RouterProviderError if isinstance(failure, TimeoutError) else RouterOutputError
        ):
            asyncio.run(agent.run({"current_text": "synthetic"}))
    else:
        asyncio.run(agent.run({"current_text": "synthetic"}))
    run.assert_awaited_once()
    built = run.call_args.args[0]
    args = run.call_args.kwargs
    assert built.tools == [] and built.handoffs == []
    assert built.model_settings.retry.max_retries == 0 and built.model_settings.store is False
    assert args["max_turns"] == 1 and args["run_config"].tracing_disabled
    assert "previous_response_id" not in args and "session" not in args
    assert "offline-test-key" not in args["input"] + built.instructions
    assert len(clients) == 1 and clients[0].closed and clients[0].options["max_retries"] == 0


def test_amount_without_currency_asks_one_currency_question_without_guessing():
    turn = handle(
        ProductFixture(
            decision("deposit_interest", preferences=Preferences(amount=50000, liquidity=True))
        )
    )
    assert turn.context.preferences.currency is None
    assert turn.context.last_question == "currency" and not turn.public_state.products


def test_semantic_candidate_ids_cannot_override_matching_policy():
    turn = handle(
        ProductFixture(
            decision(
                "deposit_interest",
                product_ids=["DEP-FLEX"],
                preferences=Preferences(liquidity=False, amount=200000, currency="KZT"),
            )
        )
    )
    assert turn.public_state.products[0].id == "DEP-SAVE"
    assert turn.routing.product_ids == []


def test_clear_kazakh_orthography_corrects_stale_reply_language_only():
    turn = asyncio.run(
        ProductPromoterPack(catalog(), ProductFixture(decision("deposit_interest"))).handle_turn(
            "Депозит таңдағым келеді.",
            GlobalConversationContext(session_id="kk"),
            ProductScenarioContext(),
        )
    )
    assert turn.routing.language == "ru"  # Model evidence remains visible.
    assert turn.routing.response_language == "kk" and "ақшаның" in turn.response_text


def test_completed_decline_survives_switch_away_back_and_new_consultation_can_start():
    built = build_services(Settings(_env_file=None), router_override=InsuranceFixture())
    built.registry.get("product_promoter").agent = ProductFixture(
        decision("decline"),
        decision("general_discovery"),
        decision("deposit_interest"),
    )

    async def flow():
        first = await built.messages.process("complete", "decline", "product_promoter")
        assert (
            first.trace.context_lifecycle == "completed" and first.conversation_status == "active"
        )
        await built.messages.process("complete", "insurance", "insurance_manager")
        back = await built.messages.process("complete", "neutral", "product_promoter")
        assert back.state.interest_level == "declined" and not back.state.products
        new = await built.messages.process("complete", "new consultation")
        assert new.trace.context_lifecycle == "active" and new.state.last_question == "liquidity"

    asyncio.run(flow())


def test_selector_rejects_unregistered_model_target():
    selector = ScenarioSelector(Settings(_env_file=None))

    async def run(payload):
        return PackSelection(target_pack_id="unregistered", confidence=1, response_language="ru")

    selector.transport.run = run
    with pytest.raises(RouterOutputError):
        asyncio.run(
            selector.select("test", "product_promoter", [{"id": "insurance_manager"}], "ru")
        )


@pytest.mark.parametrize(
    "amount,currency,language,expected",
    [
        (50000, "KZT", "ru", "50 тысяч тенге"),
        (10000, "KZT", "ru", "10 тысяч тенге"),
        (1000000, "KZT", "ru", "1 миллион тенге"),
        (700, "KZT", "ru", "700 тенге"),
        (100, "USD", "ru", "100 долларов США"),
        (2, "USD", "ru", "2 доллара США"),
        (50000, "KZT", "kk", "50 мың тенге"),
        (100, "USD", "kk", "100 АҚШ доллары"),
    ],
)
def test_human_money_words(amount, currency, language, expected):
    assert money(amount, currency, language) == expected


@pytest.mark.parametrize(
    "amount,expected",
    [(1000, "1 тысячи тенге"), (3000, "3 тысяч тенге"), (1000000, "1 миллиона тенге")],
)
def test_money_after_from_or_up_to_uses_genitive(amount, expected):
    assert money(amount, "KZT", "ru", genitive=True) == expected


def test_generic_payment_goal_still_asks_about_card_priorities():
    turn = handle(
        ProductFixture(decision("card_interest", preferences=Preferences(goal="daily_payments")))
    )
    assert turn.context.last_question == "card_priority"
    assert not turn.public_state.products and turn.response_text.count("?") == 1


def test_bot_initiates_branded_consultation_without_customer_text_or_model_call():
    fixture = ProductFixture()
    pack = ProductPromoterPack(catalog(), fixture)
    turn = asyncio.run(
        pack.open_turn(GlobalConversationContext(session_id="opening"), pack.new_context())
    )
    assert "Здравствуйте!" in turn.response_text and "Merei Demo Bank" in turn.response_text
    assert turn.response_text.count("?") == 1
    assert not fixture.inputs and turn.trace.event_type == "scenario.opened"
    assert turn.trace.transcript == "" and turn.trace.latency_ms.router is None


def test_start_api_uses_shared_context_switch_and_does_not_fabricate_user_turn():
    app = create_app(Settings(_env_file=None), router_override=InsuranceFixture())
    with TestClient(app) as client:
        first = client.post("/api/message", json={"session_id": "start", "text": "insurance"})
        assert first.status_code == 200
        before = (
            app.state.services.dialogs.get_conversation("start")
            .scenario_contexts["insurance_manager"]
            .state
        )
        opened = client.post(
            "/api/conversation/start",
            json={"session_id": "start", "scenario_mode": "product_promoter"},
        )
        assert opened.status_code == 200, opened.text
        assert opened.json()["trace"]["event_type"] == "scenario.opened"
        assert opened.json()["trace"]["pack_switch"]["from_pack"] == "insurance_manager"
        assert (
            app.state.services.dialogs.get_conversation("start")
            .scenario_contexts["insurance_manager"]
            .state
            == before
        )
        unknown = client.post(
            "/api/conversation/start", json={"session_id": "start", "scenario_mode": "unknown"}
        )
        assert unknown.status_code == 422


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_all_spoken_products_use_human_currency_and_source_conditions(language):
    for product in catalog().products:
        speech = spoken_summary(product, language)
        assert "KZT" not in speech and "USD" not in speech and product.id not in speech
        assert (product.name_ru if language == "ru" else product.name_kk) in speech
    assert "0,1 процента" in spoken_currency("0.1% годовых", "ru")
