from time import perf_counter

from app.agent.errors import RouterOutputError
from app.conversation.language import reply_language
from app.conversation.terminal import terminal_reply
from app.core.contracts import Contract
from app.packs.contracts import (
    GlobalConversationContext,
    InteractionMode,
    PackTurn,
    ScenarioManifest,
)
from app.packs.product_promoter.agent import PROMOTER_INSTRUCTIONS
from app.packs.product_promoter.catalog import conditions, matching_products
from app.packs.product_promoter.models import (
    ProductCatalog,
    ProductConditions,
    ProductDecision,
    ProductPublicState,
    ProductScenarioContext,
    SalesLeadResult,
)
from app.packs.product_promoter.presentation import spoken_currency, spoken_summary
from app.tracing.models import LatencyRecord, TraceRecord

PRODUCT_MANIFEST = ScenarioManifest(
    id="product_promoter",
    name="Product Promoter",
    interaction_mode=InteractionMode.PROACTIVE,
    supported_languages=("ru", "kk", "mixed"),
    output_schema="SalesLeadResult",
    public_description="Synthetic deposits and debit/payment cards: discover preferences, explain "
    "conditions, compare, handle objections and record application interest. "
    "Excludes insurance, loans, fraud/security and technical support.",
)

QUESTIONS = {
    "currency": (
        "В какой валюте указана сумма: в тенге или в долларах США?",
        "Сома қай валютада көрсетілген: теңгемен бе, АҚШ долларымен бе?",
    ),
    "category": (
        "Что хотите подобрать: депозит для накоплений или карту для платежей?",
        "Қайсысын таңдаймыз: жинақ үшін депозит пе, төлем үшін карта ма?",
    ),
    "liquidity": (
        "Нужно ли снимать часть денег в течение срока, "
        "или готовы оставить их до конца ради более высокой ставки?",
        "Мерзім ішінде ақшаның бір бөлігін алу керек пе, "
        "әлде жоғары мөлшерлеме үшін соңына дейін қалдыра аласыз ба?",
    ),
    "card_priority": (
        "Что для вас важнее в карте: кешбэк за покупки, "
        "бесплатное обслуживание или снятие наличных?",
        "Қайсысы маңызды: cashback, қызмет ақысының болмауы немесе қолма-қол ақша алу?",
    ),
    "next_action": (
        "Вам подходит этот вариант или хотите посмотреть другой?",
        "Басқа нұсқамен салыстырамыз ба, әлде осы өнімге қызығушылықты тіркейміз бе?",
    ),
}


class ProductPromoterPack:
    manifest = PRODUCT_MANIFEST
    state_schema = ProductScenarioContext
    output_schema = SalesLeadResult
    prompt = PROMOTER_INSTRUCTIONS
    tools = ()  # No bank writes, callback service or application delivery integration.
    policies = ("explicit preferences only", "catalog-grounded", "respect decline")
    completion_rules = (
        "Interest/decline completes the lead; only handoff/goodbye closes the conversation."
    )

    def __init__(self, catalog: ProductCatalog, agent):
        self.knowledge = catalog.model_copy(deep=True)
        self.agent = agent
        self._products = {p.id: p for p in catalog.products}

    def new_context(self):
        return ProductScenarioContext()

    async def open_turn(self, global_context: GlobalConversationContext, context: Contract):
        if type(context) is not ProductScenarioContext:
            raise ValueError("Product Promoter requires its own context")
        language = (
            global_context.language
            if global_context.language in ("ru", "kk")
            else context.response_language
        )
        context.response_language = language
        context.last_intent = "general_discovery"
        ru = language == "ru"
        greeting = (
            "Здравствуйте! Я виртуальный консультант демонстрационного Merei Demo Bank. "
            "Помогу подобрать удобный депозит или карту под ваши задачи."
            if ru
            else "Сәлеметсіз бе! Мен демонстрациялық Merei Demo Bank виртуалды кеңесшісімін. "
            "Мақсатыңызға сай депозит немесе карта таңдауға көмектесемін."
        )
        if context.interest_level == "declined":
            response = greeting + (
                " Ваш отказ сохранён, подбор остановлен."
                if ru
                else " Бас тартуыңыз сақталды, өнім таңдау тоқтатылды."
            )
            outcome = "declined"
        elif context.completed:
            response = greeting + (
                " Ваш интерес к продукту сохранён. Чем ещё могу помочь?"
                if ru
                else " Өнімге қызығушылығыңыз сақталды. Тағы қалай көмектесе аламын?"
            )
            outcome = "interested"
        else:
            question = context.last_question if context.last_question in QUESTIONS else "category"
            if context.product_category and question == "category":
                question = "next_action"
            context.last_question = question
            response = greeting + " " + QUESTIONS[question][0 if ru else 1]
            outcome = "consulting"
        lead = self._lead(context, "active", outcome, context.completed)
        return PackTurn(
            context=context,
            language=language,
            response_text=response,
            routing=ProductDecision(
                intent="general_discovery", language=language, response_language=language
            ),
            public_state=self._public_state(context, lead, global_context, []),
            trace=TraceRecord(
                turn=global_context.turn_number + 1,
                transcript="",
                language=language,
                reason="Assistant initiated product consultation",
                event_type="scenario.opened",
                product_category=context.product_category,
                lead_status=outcome,
                next_action=context.next_action,
            ),
            result=lead,
            complete_pack=context.completed,
        )

    async def handle_turn(
        self, text: str, global_context: GlobalConversationContext, context: Contract
    ):
        if type(context) is not ProductScenarioContext:
            raise ValueError("Product Promoter requires its own context")
        started = perf_counter()
        first_response = context.last_intent is None
        invalid = False
        try:
            decision = await self.agent.decide(text, context.model_copy(deep=True))
            if type(decision) is not ProductDecision or any(
                pid not in self._products for pid in decision.product_ids
            ):
                raise RouterOutputError()
            if len({self._products[pid].category for pid in decision.product_ids}) > 1:
                raise RouterOutputError()
            if decision.category and any(
                self._products[pid].category != decision.category for pid in decision.product_ids
            ):
                raise RouterOutputError()
        except RouterOutputError:
            invalid = True
            decision = ProductDecision(
                intent="general_discovery",
                language=global_context.language or "ru",
                response_language=context.response_language,
                confidence=0,
            )
        router_ms = (perf_counter() - started) * 1000
        if not invalid:
            decision.response_language = reply_language(
                text, decision.language, decision.response_language
            )
        if decision.intent in (
            "deposit_interest",
            "card_interest",
            "objection",
            "general_discovery",
        ):
            # Semantic extraction cannot override the deterministic recommendation policy.
            decision.product_ids = []
        if context.completed and decision.intent in ("deposit_interest", "card_interest"):
            context = ProductScenarioContext(response_language=decision.response_language)
        elif context.interest_level == "declined" and decision.intent in (
            "general_discovery",
            "conditions_question",
            "objection",
            "application_interest",
        ):
            # A neutral continuation after refusal never restarts a sales pitch.
            decision.intent = "decline"
        language = decision.response_language
        context.response_language = language
        ru = language == "ru"

        def pick(pair):
            return pair[0 if ru else 1]

        status, outcome, complete = "active", "consulting", False
        shown = []
        context.last_intent = decision.intent

        if invalid or decision.confidence < 0.6:
            context.unclear_turns += 1
            if context.unclear_turns >= 3:
                status, outcome, complete = "handoff", "handoff", True
                context.next_action = "operator_handoff"
                response = terminal_reply(status, language)
            else:
                response = pick(
                    (
                        "Уточните, пожалуйста, что хотите узнать о депозите или карте?",
                        "Депозит немесе карта туралы нені білгіңіз келетінін нақтылаңызшы?",
                    )
                )
        elif decision.intent in ("operator_request", "goodbye"):
            status = "handoff" if decision.intent == "operator_request" else "ended"
            outcome, complete = status, True
            if status == "handoff":
                context.next_action = "operator_handoff"
            response = terminal_reply(status, language)
        elif decision.intent == "decline":
            context.interest_level, context.next_action = "declined", "declined"
            outcome, complete = "declined", True
            context.last_question = None
            response = pick(
                (
                    "Понял, подбор продуктов прекращаю. Если появится другой вопрос, обращайтесь.",
                    "Түсіндім, өнім таңдауды тоқтатамын. Басқа сұрағыңыз болса, айтыңыз.",
                )
            )
        elif decision.intent == "out_of_scope":
            response = pick(
                (
                    "Я консультирую по демонстрационным депозитам и картам. "
                    "Этот вопрос вне моего профиля.",
                    "Мен демонстрациялық депозиттер мен карталар бойынша кеңес беремін. "
                    "Бұл сұрақ менің бағытыма кірмейді.",
                )
            )
        else:
            context.unclear_turns = 0
            category = decision.category
            if decision.product_ids:
                category = self._products[decision.product_ids[0]].category
            if decision.intent == "deposit_interest":
                category = "deposit"
            elif decision.intent == "card_interest":
                category = "card"
            if category and category != context.product_category:
                # Category-local preferences/products are reset; language stays local.
                context = ProductScenarioContext(
                    product_category=category, response_language=language
                )
                context.last_intent = decision.intent
            for key, value in decision.preferences.model_dump().items():
                if value is not None:
                    setattr(context.preferences, key, value)
            if decision.objection and decision.objection not in context.objections:
                context.objections.append(decision.objection)
            if decision.intent == "application_interest":
                candidate = (
                    decision.product_ids[0]
                    if decision.product_ids
                    else context.recommended_product_id
                )
                if candidate:
                    context.selected_product_id = candidate
                    context.interest_level = "high"
                    context.next_action = (
                        decision.next_action
                        if decision.next_action
                        in ("application_interest", "send_application_link", "callback_requested")
                        else "application_interest"
                    )
                    outcome, complete = "interested", True
                    name = (
                        self._products[candidate].name_ru
                        if ru
                        else self._products[candidate].name_kk
                    )
                    response = pick(
                        (
                            f"Зафиксировал интерес к продукту «{name}». "
                            "Это демонстрационная заявка: "
                            "продукт не открыт, ссылка не отправлена, звонок не назначен. "
                            "Для реального оформления нужны официальный канал банка "
                            "и проверка условий.",
                            f"«{name}» өніміне қызығушылық тіркелді. Бұл демонстрациялық өтініш: "
                            "өнім ашылған жоқ, сілтеме жіберілген жоқ, қоңырау белгіленген жоқ. "
                            "Нақты рәсімдеу үшін банктің ресми арнасы "
                            "және шарттарды тексеру қажет.",
                        )
                    )
                    context.last_question = None
                else:
                    response = pick(
                        (
                            "Сначала выберем продукт: депозит или карту?",
                            "Алдымен өнімді таңдайық: депозит пе, карта ма?",
                        )
                    )
                    context.last_question = "category"
            else:
                question = None
                if context.product_category is None:
                    question = "category"
                elif (
                    context.product_category == "deposit"
                    and context.preferences.amount is not None
                    and context.preferences.currency is None
                    and not decision.product_ids
                ):
                    question = "currency"
                elif not decision.product_ids and decision.intent not in (
                    "conditions_question",
                    "product_comparison",
                    "objection",
                ):
                    if (
                        context.product_category == "deposit"
                        and context.preferences.liquidity is None
                    ):
                        question = "liquidity"
                    elif context.product_category == "card" and not any(
                        (
                            context.preferences.cashback is not None,
                            context.preferences.fee_sensitive is not None,
                            context.preferences.cash_withdrawal is not None,
                            context.preferences.goal in ("cashback", "withdrawals"),
                        )
                    ):
                        question = "card_priority"
                if question:
                    context.last_question = question
                    response = pick(QUESTIONS[question])
                else:
                    candidates = matching_products(
                        self.knowledge, context.product_category, context.preferences
                    )
                    shown = (
                        [self._products[pid] for pid in decision.product_ids]
                        if decision.product_ids
                        else (
                            [
                                p
                                for p in self.knowledge.products
                                if p.category == context.product_category
                            ][:2]
                            if decision.intent == "product_comparison"
                            else candidates[:1]
                        )
                    )
                    if not shown:
                        context.recommended_product_id = None
                        response = pick(
                            (
                                "В демо-каталоге нет продукта, "
                                "который соответствует всем этим условиям. "
                                "Какое условие вы готовы пересмотреть?",
                                "Демо-каталогта осы шарттардың бәріне сай өнім жоқ. "
                                "Қай шартты өзгертуге болады?",
                            )
                        )
                    else:
                        context.interest_level = "medium"
                        context.recommended_product_id = shown[0].id
                        if decision.product_ids and decision.intent != "product_comparison":
                            context.selected_product_id = shown[0].id
                        for p in shown:
                            if p.id not in context.presented_products:
                                context.presented_products.append(p.id)
                        if decision.intent == "product_comparison":
                            context.compared_products = [p.id for p in shown]
                        rationale = self._rationale(context, shown, language)
                        if decision.product_ids and decision.intent != "product_comparison":
                            rationale = pick(
                                (
                                    "Расскажу об этом варианте. "
                                    "Проверьте, подходят ли вам его ограничения.",
                                    "Осы нұсқа туралы айтып берейін. "
                                    "Шектеулері сізге сәйкес келе ме, тексеріңіз.",
                                )
                            )
                        objection = (
                            pick(
                                (
                                    "Понимаю, это условие может не подойти. "
                                    "Его изменить нельзя, "
                                    "но можно рассмотреть другой вариант.",
                                    "Түсінемін, бұл шарт сәйкес келмеуі мүмкін. "
                                    "Оны өзгертуге болмайды, "
                                    "бірақ басқа нұсқаны қарастыруға болады.",
                                )
                            )
                            if decision.intent == "objection"
                            else ""
                        )
                        response = "\n\n".join(
                            v
                            for v in (
                                objection,
                                rationale,
                                *(spoken_summary(p, language) for p in shown),
                                pick(QUESTIONS["next_action"]),
                            )
                            if v
                        )
                        context.last_question = "next_action"
        context.completed = complete
        if first_response and status == "active":
            response = (
                "Здравствуйте! Я консультант демонстрационного Merei Demo Bank. "
                if ru
                else "Сәлеметсіз бе! Мен демонстрациялық Merei Demo Bank кеңесшісімін. "
            ) + response
        lead = self._lead(context, status, outcome, complete)
        trace = TraceRecord(
            turn=global_context.turn_number + 1,
            transcript=text,
            language=decision.language,
            reason=f"Product consultation: {decision.intent}",
            routing_error="invalid_structure" if invalid else None,
            clarification=context.last_question
            in ("category", "currency", "liquidity", "card_priority"),
            source_keys=[f"product_catalog.{p.id}" for p in shown],
            product_category=context.product_category,
            presented_products=[p.id for p in shown],
            selected_product_id=context.selected_product_id,
            lead_status=lead.outcome,
            next_action=lead.next_action,
            latency_ms=LatencyRecord(
                router=router_ms, response=(perf_counter() - started) * 1000 - router_ms
            ),
        )
        return PackTurn(
            context=context,
            language=decision.language,
            response_text=response,
            routing=decision,
            public_state=self._public_state(context, lead, global_context, shown),
            trace=trace,
            result=lead,
            complete_pack=complete,
            out_of_domain=decision.intent == "out_of_scope",
        )

    def _lead(self, context, status, outcome, complete):
        return SalesLeadResult(
            status=status,
            completed=complete,
            handoff=status == "handoff",
            outcome=outcome,
            product_category=context.product_category,
            selected_product_id=context.selected_product_id,
            customer_preferences=context.preferences.model_copy(deep=True),
            presented_products=context.presented_products.copy(),
            compared_products=context.compared_products.copy(),
            objections=context.objections.copy(),
            interest_level=context.interest_level,
            next_action=context.next_action,
        )

    def _public_state(self, context, lead, global_context, shown):
        return ProductPublicState(
            **context.model_dump(),
            session_id=global_context.session_id,
            turn_number=global_context.turn_number + 1,
            sales_lead=lead,
            products=[p.model_copy(deep=True) for p in shown],
            product_conditions=[
                ProductConditions(
                    product_id=p.id,
                    name=p.name_ru if context.response_language == "ru" else p.name_kk,
                    text=spoken_currency(
                        conditions(p, context.response_language), context.response_language
                    ),
                )
                for p in shown
            ],
        )

    def _rationale(self, context, shown, language):
        ru = language == "ru"
        if len(shown) > 1:
            return (
                "Давайте сравним: у этих депозитов отличаются ставка и доступ к деньгам."
                if context.product_category == "deposit" and ru
                else "Давайте сравним плату за карту, кешбэк и лимиты снятия."
                if ru
                else "Бұл депозиттердің мөлшерлемесі мен ақшаны алу шарттарын салыстырайық."
                if context.product_category == "deposit"
                else "Карталардың ақысын, cashback пен ақша алу лимитін салыстырайық."
            )
        prefs = context.preferences
        if context.product_category == "deposit":
            return (
                "Предлагаю этот депозит: вы сможете снимать часть денег, когда понадобится."
                if prefs.liquidity and shown[0].partial_withdrawal and ru
                else "Предлагаю рассмотреть этот депозит для накоплений."
                if ru
                else "Сіздің қалауыңызға сай осы депозитті қарастыруды ұсынамын."
            )
        criterion = (
            "снятие наличных"
            if prefs.cash_withdrawal
            else "cashback"
            if prefs.cashback
            else "плата за обслуживание"
        )
        return (
            f"Если для вас важнее {criterion}, стоит рассмотреть эту карту."
            if ru
            else "Сіздің басымдығыңызға сай осы картаны қарастыруға болады."
        )
