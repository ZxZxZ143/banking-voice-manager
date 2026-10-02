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
from app.packs.product_promoter.presentation import (
    opening_instructions,
    sales_details,
    sales_pitch,
    spoken_currency,
    spoken_summary,
)
from app.tracing.models import LatencyRecord, TraceRecord

PRODUCT_MANIFEST = ScenarioManifest(
    id="product_promoter",
    name="Продажа депозита",
    interaction_mode=InteractionMode.PROACTIVE,
    supported_languages=("ru", "kk", "mixed"),
    output_schema="SalesLeadResult",
    public_description="Outbound synthetic deposit offer. Campaign assigned before the call; "
    "explain conditions and opening, adapt to explicit needs, one refusal follow-up. "
    "No real bank actions or automatic campaign switching.",
)

CAMPAIGNS = {
    "deposit": ("product_promoter", "Продажа депозита", "депозита", "депозит", "DEP-FLEX"),
    "card": ("card_promoter", "Продажа карты", "карты", "карта", "CARD-DAILY"),
    "loan": ("loan_promoter", "Продажа кредита", "кредита", "несие", "LOAN-DIGITAL"),
}

QUESTIONS = {
    "currency": (
        "В какой валюте указана сумма: в тенге или в долларах США?",
        "Сома қай валютада көрсетілген: теңгемен бе, АҚШ долларымен бе?",
    ),
    "offer_details": (
        "Можно коротко рассказать об условиях?",
        "Шарттарын қысқаша айтып берейін бе?",
    ),
    "amount": ("Какую сумму вы хотели бы рассмотреть?", "Қандай соманы қарастырғыңыз келеді?"),
    "opening_offer": (
        "Рассказать, как оформить?",
        "Оны қалай рәсімдеуге болатынын айтайын ба?",
    ),
    "refusal_check": (
        "Вы уверены, что не хотите даже коротко узнать условия?",
        "Шарттарын қысқаша тыңдағыңыз келмейтініне сенімдісіз бе?",
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
        "Хотите оформить?",
        "Басқа нұсқамен салыстырамыз ба, әлде осы өнімге қызығушылықты тіркейміз бе?",
    ),
}

CAMPAIGN_QUESTIONS = {
    "opening_offer": {
        "deposit": (
            "Рассказать, как открыть депозит?",
            "Депозитті қалай ашуға болатынын айтайын ба?",
        ),
        "card": (
            "Рассказать, как оформить карту?",
            "Картаны қалай рәсімдеуге болатынын айтайын ба?",
        ),
        "loan": ("Рассказать, как подать заявку?", "Өтінішті қалай беруге болатынын айтайын ба?"),
    },
    "next_action": {
        "deposit": ("Хотите открыть этот депозит?", "Осы депозитті ашқыңыз келе ме?"),
        "card": ("Хотите оформить эту карту?", "Осы картаны рәсімдегіңіз келе ме?"),
        "loan": ("Хотите подать заявку на этот кредит?", "Осы несиеге өтініш бергіңіз келе ме?"),
    },
}


class ProductPromoterPack:
    manifest = PRODUCT_MANIFEST
    state_schema = ProductScenarioContext
    output_schema = SalesLeadResult
    prompt = PROMOTER_INSTRUCTIONS
    tools = ()  # No bank writes, callback service or application delivery integration.
    policies = ("explicit preferences only", "catalog-grounded", "respect decline")
    completion_rules = (
        "Interest completes the lead; final refusal, explicit stop, "
        "handoff/goodbye closes the call."
    )

    def __init__(self, catalog: ProductCatalog, agent, *, campaign="deposit"):
        if campaign not in CAMPAIGNS:
            raise ValueError("Unknown outbound sales campaign")
        self.campaign = campaign
        mode, name, *_ = CAMPAIGNS[campaign]
        self.manifest = PRODUCT_MANIFEST.model_copy(
            update={
                "id": mode,
                "name": name,
                "public_description": f"Outbound synthetic {campaign} campaign, "
                "assigned before the call. "
                "No customer campaign selection, actual bank writes or automatic switching.",
            }
        )
        self.knowledge = catalog.model_copy(deep=True)
        self.agent = agent
        self._products = {p.id: p for p in catalog.products}

    def new_context(self):
        return ProductScenarioContext(campaign=self.campaign, product_category=self.campaign)

    async def open_turn(self, global_context: GlobalConversationContext, context: Contract):
        if type(context) is not ProductScenarioContext or context.campaign != self.campaign:
            raise ValueError("Product Promoter requires its own context")
        language = (
            global_context.language
            if global_context.language in ("ru", "kk")
            else context.response_language
        )
        context.response_language = language
        context.last_intent = "general_discovery"
        ru = language == "ru"
        greeting = self._greeting(language)
        shown = []
        if context.interest_level == "declined":
            response = greeting + (
                " Ваш отказ сохранён. Всего доброго."
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
            context.product_category = self.campaign
            product = self._products[CAMPAIGNS[self.campaign][4]]
            shown = [product]
            context.recommended_product_id = product.id
            if product.id not in context.presented_products:
                context.presented_products.append(product.id)
            context.last_question = "offer_details"
            context.sales_phase = "pitch"
            response = (
                greeting
                + " "
                + sales_pitch(product, language)
                + " "
                + QUESTIONS["offer_details"][0 if ru else 1]
            )
            outcome = "consulting"
        context.last_assistant_text = response
        context.last_question_text = (
            self._question(context.last_question, language)
            if context.last_question in QUESTIONS
            else None
        )
        lead = self._lead(context, "active", outcome, context.completed)
        return PackTurn(
            context=context,
            language=language,
            response_text=response,
            routing=ProductDecision(
                intent="general_discovery", language=language, response_language=language
            ),
            public_state=self._public_state(context, lead, global_context, shown),
            trace=TraceRecord(
                turn=global_context.turn_number + 1,
                transcript="",
                language=language,
                reason="Assistant initiated assigned outbound sales campaign",
                event_type="scenario.opened",
                source_keys=[f"product_catalog.{p.id}" for p in shown],
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
        if type(context) is not ProductScenarioContext or context.campaign != self.campaign:
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
        model_intent = decision.intent
        has_preferences = any(v is not None for v in decision.preferences.model_dump().values())
        if (
            not invalid
            and decision.accepts_explanation
            and not has_preferences
            and decision.intent
            in {
                "general_discovery",
                "deposit_interest",
                "card_interest",
                "loan_interest",
                "conditions_question",
                "opening_question",
            }
        ):
            if context.last_question == "opening_offer":
                decision.intent = "opening_question"
            elif context.last_question in {"offer_details", "refusal_check"}:
                decision.intent = "conditions_question"
        if not invalid and decision.intent in {
            "deposit_interest",
            "card_interest",
            "loan_interest",
        }:
            # Interpret the model's typed interest/focus against the actual offered next
            # step. This is dialogue progression, not a text/keyword intent classifier.
            if not has_preferences and decision.question_topic != "overview":
                decision.intent = "conditions_question"
        if not invalid:
            requested_category = (
                "deposit"
                if model_intent == "deposit_interest"
                else "card"
                if model_intent == "card_interest"
                else "loan"
                if model_intent == "loan_interest"
                else decision.category
            )
            if (requested_category and requested_category != self.campaign) or any(
                self._products[pid].category != self.campaign for pid in decision.product_ids
            ):
                decision.intent = "out_of_scope"
                decision.product_ids = []
        if decision.intent in (
            "deposit_interest",
            "card_interest",
            "loan_interest",
            "objection",
            "general_discovery",
        ):
            # Semantic extraction cannot override the deterministic recommendation policy.
            decision.product_ids = []
        if context.interest_level == "declined" and decision.intent in (
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
        clarification = False
        shown = []
        context.last_intent = decision.intent

        if invalid or decision.confidence < 0.6:
            context.unclear_turns += 1
            if context.unclear_turns >= 3:
                status, outcome, complete = "handoff", "handoff", True
                context.next_action = "operator_handoff"
                response = terminal_reply(status, language)
            else:
                clarification = True
                response = pick(
                    (
                        "Не расслышал последнюю часть. Что хотите уточнить по моему предложению?",
                        "Соңғы бөлігін естімедім. Ұсыныс бойынша нені нақтылағыңыз келеді?",
                    )
                )
        elif decision.intent in ("operator_request", "goodbye"):
            status = "handoff" if decision.intent == "operator_request" else "ended"
            outcome, complete = status, True
            if status == "handoff":
                context.next_action = "operator_handoff"
            response = terminal_reply(status, language)
        elif decision.intent == "decline":
            context.refusal_count = min(2, context.refusal_count + 1)
            if context.refusal_count == 1 and not decision.stop_sales:
                context.interest_level = "low"
                context.sales_phase = "refusal_check"
                context.last_question = "refusal_check"
                clarification = True
                response = pick(QUESTIONS["refusal_check"])
            else:
                context.interest_level, context.next_action = "declined", "declined"
                context.sales_phase = "closed"
                status, outcome, complete = "ended", "declined", True
                context.last_question = None
                response = pick(
                    (
                        "Хорошо, больше не буду предлагать. Спасибо за ваше время, всего доброго.",
                        "Жақсы, бұдан әрі ұсынбаймын. Уақытыңызға рақмет, сау болыңыз.",
                    )
                )
        elif decision.intent == "out_of_scope":
            response = pick(
                (
                    f"Этот звонок посвящён предложению {CAMPAIGNS[self.campaign][2]}. "
                    "Другие продукты обсуждаются в отдельном звонке. "
                    "Можно продолжить по моему предложению?",
                    f"Бұл қоңырау {CAMPAIGNS[self.campaign][3]} ұсынысына арналған. "
                    "Басқа өнімдер бөлек қоңырауда талқыланады. Осы ұсынысты жалғастырайық па?",
                )
            )
        elif (
            decision.intent == "general_discovery"
            and context.sales_phase == "pitch"
            and not any(value is not None for value in decision.preferences.model_dump().values())
        ):
            context.product_category = self.campaign
            product = self._products[CAMPAIGNS[self.campaign][4]]
            context.recommended_product_id = product.id
            shown = [product]
            if product.id not in context.presented_products:
                context.presented_products.append(product.id)
            context.last_question = "offer_details"
            response = sales_pitch(product, language) + " " + pick(QUESTIONS["offer_details"])
        else:
            context.unclear_turns = 0
            context.product_category = self.campaign
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
                    context.sales_phase = "closed"
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
                    response = pick(QUESTIONS["offer_details"])
                    context.last_question = "offer_details"
            else:
                question = None
                if (
                    context.product_category == "deposit"
                    and context.preferences.amount is not None
                    and context.preferences.currency is None
                    and not decision.product_ids
                ):
                    question = "currency"
                elif not decision.product_ids and decision.intent not in (
                    "conditions_question",
                    "opening_question",
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
                    elif context.product_category == "loan" and context.preferences.amount is None:
                        question = "amount"
                if question:
                    clarification = True
                    context.last_question = question
                    context.sales_phase = "needs"
                    if question == "amount":
                        response = pick(
                            (
                                "Какую сумму вы хотели бы рассмотреть?",
                                "Қандай соманы қарастырғыңыз келеді?",
                            )
                        )
                    else:
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
                            else [self._products[context.recommended_product_id]]
                            if decision.intent in {"conditions_question", "opening_question"}
                            and context.recommended_product_id in {p.id for p in candidates}
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
                        if decision.intent != "product_comparison":
                            rationale = ""
                        objection = (
                            pick(
                                (
                                    "Тогда предложу другой вариант.",
                                    "Онда басқа нұсқаны ұсынамын.",
                                )
                            )
                            if decision.intent == "objection"
                            else ""
                        )
                        details = (
                            [opening_instructions(p, language) for p in shown]
                            if decision.intent == "opening_question"
                            else [
                                sales_details(p, language, decision.question_topic) for p in shown
                            ]
                            if decision.intent == "conditions_question"
                            else [spoken_summary(p, language) for p in shown]
                            if decision.intent == "product_comparison"
                            else [sales_pitch(p, language) for p in shown]
                        )
                        followup = (
                            "next_action"
                            if decision.intent == "opening_question"
                            else "opening_offer"
                        )
                        context.sales_phase = (
                            "opening" if decision.intent == "opening_question" else "conditions"
                        )
                        response = "\n\n".join(
                            v
                            for v in (
                                objection,
                                rationale,
                                *details,
                                self._question(followup, language),
                            )
                            if v
                        )
                        context.last_question = followup
        context.completed = complete
        context.customer_turns += 1
        if status in ("handoff", "ended"):
            context.last_question = None
        if first_response and status == "active":
            response = (self._greeting(language)) + " " + response
        context.last_assistant_text = response
        context.last_question_text = (
            self._question(context.last_question, language)
            if context.last_question in QUESTIONS
            else None
        )
        lead = self._lead(context, status, outcome, complete)
        trace = TraceRecord(
            turn=global_context.turn_number + 1,
            transcript=text,
            language=decision.language,
            reason=f"Outbound sales: model={model_intent}; dialogue_act={decision.intent}",
            routing_error="invalid_structure" if invalid else None,
            clarification=clarification,
            source_keys=[f"product_catalog.{p.id}" for p in shown],
            product_category=context.product_category,
            presented_products=[p.id for p in shown],
            selected_product_id=context.selected_product_id,
            lead_status=lead.outcome,
            next_action=lead.next_action,
            conversation_phase=context.sales_phase,
            conversation_act=decision.intent,
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

    def _question(self, key, language):
        pair = (
            CAMPAIGN_QUESTIONS[key][self.campaign] if key in CAMPAIGN_QUESTIONS else QUESTIONS[key]
        )
        return pair[0 if language == "ru" else 1]

    def _greeting(self, language):
        return (
            f"Здравствуйте! Я виртуальный представитель демонстрационного Merei Demo Bank. "
            f"Звоню, чтобы предложить вам вариант {CAMPAIGNS[self.campaign][2]}."
            if language == "ru"
            else f"Сәлеметсіз бе! Мен демонстрациялық Merei Demo Bank виртуалды өкілімін. "
            f"Сізге {CAMPAIGNS[self.campaign][3]} ұсыну үшін қоңырау шалып тұрмын."
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
            scenario_mode=self.manifest.id,
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
        if context.product_category == "loan":
            return (
                "Рассмотрим кредит с учётом желаемой суммы и срока."
                if ru
                else "Қалаған сома мен мерзімге сай несиені қарастырайық."
            )
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
