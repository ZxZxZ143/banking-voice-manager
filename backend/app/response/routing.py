"""Local slot replies and a small, explicitly read-only grounded response slice."""

from datetime import date

from pydantic import Field

from app.agent.schemas import RouterDecision
from app.core.contracts import Contract
from app.data.models import SlotDataset
from app.data.repositories import KnowledgeRepository, MockBackendRepository
from app.dialog.models import DialogState
from app.scenarios.catalog import ScenarioCatalog
from app.scenarios.decision_policy import PolicyResult
from app.tools.read_only import find_client, get_claim, get_policy, kb_lookup

# Exact translations of the supplied source values, never replacement business data.
# Unknown values must stay unavailable until a grounded translation is added.
_SOURCE_TEXT = {
    "Abai Ave 150": ("проспект Абая, 150", "Абай даңғылы, 150"),
    "Mangilik El Ave 55": ("проспект Мәңгілік Ел, 55", "Мәңгілік Ел даңғылы, 55"),
    "Tauke Khan Ave 40": ("проспект Тауке хана, 40", "Тәуке хан даңғылы, 40"),
    "Bukhar Zhyrau Ave 60": ("проспект Бухар Жырау, 60", "Бұқар жырау даңғылы, 60"),
    "Abilkaiyr Khan Ave 30": ("проспект Абилкайыр хана, 30", "Әбілқайыр хан даңғылы, 30"),
    "Satpayev Ave 20": ("проспект Сатпаева, 20", "Сәтбаев даңғылы, 20"),
    "Lomov St 45": ("улица Ломова, 45", "Ломов көшесі, 45"),
    "Kazakhstan St 70": ("улица Казахстан, 70", "Қазақстан көшесі, 70"),
    "Mon-Fri 09:00-18:00, Sat 10:00-15:00": (
        "понедельник–пятница 09:00–18:00, суббота 10:00–15:00",
        "дүйсенбі–жұма 09:00–18:00, сенбі 10:00–15:00",
    ),
    "Mon-Fri 09:00-18:00": (
        "понедельник–пятница 09:00–18:00",
        "дүйсенбі–жұма 09:00–18:00",
    ),
    "Bank card in the app or on the website": (
        "банковской картой в приложении или на сайте",
        "қолданбада немесе сайтта банк картасымен",
    ),
    "Payment link by SMS": ("по ссылке из СМС", "СМС арқылы келген сілтемемен"),
    "Bank transfer (companies)": (
        "банковским переводом для компаний",
        "компаниялар үшін банк аударымымен",
    ),
    "Card terminal in any office": (
        "картой через терминал в любом офисе",
        "кез келген кеңседе терминал арқылы картамен",
    ),
    "Not accepted.": ("не принимаются", "қабылданбайды"),
    "2 or 4 equal payments, no overpayment": (
        "2 или 4 равных платежа без переплаты",
        "артық төлемсіз 2 немесе 4 тең төлем",
    ),
    "2 payments": ("2 платежа", "2 төлем"),
    "Full payment only": ("только полная оплата", "тек толық төлем"),
    "casco": ("КАСКО", "КАСКО"),
    "dms_individual": (
        "ДМС для физических лиц",
        "жеке тұлғаларға арналған ерікті медициналық сақтандыру",
    ),
    "ogpo": ("ОГПО", "көлік иесінің жауапкершілігін міндетті сақтандыру"),
    "travel": ("страхование путешественников", "саяхатшыларды сақтандыру"),
    "Log in with the phone number and a one-time SMS code.": (
        "Войдите по номеру телефона и одноразовому СМС-коду.",
        "Телефон нөмірі мен бір реттік СМС коды арқылы кіріңіз.",
    ),
    "Check the phone number": ("проверьте номер телефона", "телефон нөмірін тексеріңіз"),
    "Wait 60 seconds and request a new code": (
        "подождите 60 секунд и запросите новый код",
        "60 секунд күтіп, жаңа код сұраңыз",
    ),
    "Maximum 5 codes per hour": (
        "можно запросить не более 5 кодов в час",
        "сағатына ең көбі 5 код сұрауға болады",
    ),
    "Try another card": ("попробуйте другую карту", "басқа картаны қолданып көріңіз"),
    "Check that online payments are enabled in your bank": (
        "проверьте, разрешены ли интернет-платежи в вашем банке",
        "банкіңізде интернет төлемдерге рұқсат берілгенін тексеріңіз",
    ),
    "paid": ("выплачено", "төленді"),
    "approved": ("одобрено", "мақұлданды"),
    "documents_requested": ("запрошены документы", "құжаттар сұратылды"),
    "under_review": ("на рассмотрении", "қарастырылып жатыр"),
    "Payout completed on 2026-05-29.": (
        "Выплата выполнена 2026-05-29.",
        "Төлем 2026-05-29 күні жасалды.",
    ),
    "Payout of 412 000 KZT scheduled for 2026-10-02. The amount follows the insurer's "
    "independent assessment; the service station estimate was 830 000 KZT.": (
        "Выплата 412 000 тенге запланирована на 2026-10-02. "
        "Сумма определена по независимой оценке страховщика; "
        "оценка станции технического обслуживания составила 830 000 тенге.",
        "412 000 теңге төлем 2026-10-02 күніне жоспарланған. "
        "Сома сақтандырушының тәуелсіз бағалауына негізделген; "
        "техникалық қызмет көрсету станциясының бағалауы 830 000 теңге болған.",
    ),
    "Upload the act from the building management company; review starts after that.": (
        "Загрузите акт управляющей компании; после этого начнётся рассмотрение.",
        "Басқарушы компанияның актісін жүктеңіз; содан кейін қарау басталады.",
    ),
    "All documents received. Decision due by 2026-10-09, the client will get an SMS.": (
        "Все документы получены. Решение ожидается до 2026-10-09, клиент получит СМС.",
        "Барлық құжаттар алынды. Шешім 2026-10-09 күніне дейін күтіледі, клиентке СМС келеді.",
    ),
}
_UNAVAILABLE_TEXT = {
    "ru": "Сведения на русском языке пока недоступны",
    "kk": "Бұл мәлімет қазақ тілінде әзірге қолжетімсіз",
}


def _localized_source(value: object, language: str) -> str | None:
    versions = _SOURCE_TEXT.get(value) if isinstance(value, str) else None
    return versions[0 if language == "ru" else 1] if versions else None


class RoutingReplyResult(Contract):
    text: str
    actions: list[str] = Field(default_factory=list)
    source_keys: list[str] = Field(default_factory=list)
    completed: bool = False


class RoutingReplyGenerator:
    def __init__(
        self,
        catalog: ScenarioCatalog,
        slots: SlotDataset,
        knowledge: KnowledgeRepository | None = None,
        backend: MockBackendRepository | None = None,
    ) -> None:
        self.catalog = catalog
        self.slots = {slot.name: slot for slot in slots.slots}
        self.knowledge = knowledge
        self.backend = backend

    def generate(self, state: DialogState, policy: PolicyResult) -> str:
        return self.generate_result(state, policy).text

    def generate_result(
        self,
        state: DialogState,
        policy: PolicyResult,
        decision: RouterDecision | None = None,
    ) -> RoutingReplyResult:
        language = state.response_language
        if state.conversation_status == "handoff":
            return RoutingReplyResult(
                text={
                    "ru": (
                        "Нужна помощь оператора. "
                        "В этой версии перевод на оператора ещё не подключён."
                    ),
                    "kk": (
                        "Оператордың көмегі қажет. Бұл нұсқада операторға қосу әлі іске қосылмаған."
                    ),
                }[language]
            )
        selected = policy.scenario_ids[0]
        if selected == "SYS_UNCLEAR":
            # The source template requires option_a/option_b, which may be absent.
            # Do not invent alternatives or expose unfilled template placeholders.
            question = getattr(decision, "clarification_question", None)
            if isinstance(question, str) and question.strip():
                return RoutingReplyResult(text=question.strip())
            return RoutingReplyResult(
                text={
                    "ru": "Уточните, пожалуйста, какой вопрос по страхованию вы хотите решить?",
                    "kk": "Сақтандыру бойынша қандай мәселені шешкіңіз келетінін нақтылаңызшы.",
                }[language]
            )
        system = self.catalog.get_system_intent(selected)
        if system is not None:
            return RoutingReplyResult(text=getattr(system.response, language))
        scenario = self.catalog.get_by_id(state.active_scenario or selected)
        if scenario is None:
            raise ValueError("Cannot respond to an unknown scenario")
        if scenario.scenario_id in {"SC25", "SC17"} and self.backend is not None:
            return self._private_reply(state, scenario.scenario_id)
        for name in scenario.slots.required:
            if state.slots.get(name) in (None, "", []):
                return self._ask(state, name)
        if self.knowledge is not None and scenario.scenario_id in {"SC33", "SC31", "SC34"}:
            return self._knowledge_reply(state, scenario.scenario_id)
        return RoutingReplyResult(
            text={
                "ru": "Запрос определён. Выполнение операций по этому сценарию пока не подключено.",
                "kk": (
                    "Сұрау анықталды. "
                    "Бұл сценарий бойынша операцияларды орындау әлі іске қосылмаған."
                ),
            }[language]
        )

    def _ask(self, state: DialogState, name: str) -> RoutingReplyResult:
        return RoutingReplyResult(text=getattr(self.slots[name].prompt, state.response_language))

    @staticmethod
    def _string_slot(state: DialogState, name: str) -> str | None:
        value = state.slots.get(name)
        return value if isinstance(value, str) and value else None

    def _knowledge_reply(self, state: DialogState, scenario_id: str) -> RoutingReplyResult:
        assert self.knowledge is not None
        language = state.response_language
        topic = {"SC33": "offices", "SC31": "payments", "SC34": "app_help"}[scenario_id]
        result = kb_lookup(self.knowledge, topic)
        if not result.success:
            return RoutingReplyResult(
                text={
                    "ru": "Эта информация отсутствует в базе знаний.",
                    "kk": "Бұл ақпарат білім қорында жоқ.",
                }[language],
                actions=["kb_lookup"],
            )
        answer = result.data["answer"]
        completed = True

        def localized(value: object) -> str:
            nonlocal completed
            text = _localized_source(value, language)
            if text is None:
                completed = False
                return _UNAVAILABLE_TEXT[language]
            return text

        if scenario_id == "SC33":
            offices = [office for office in answer if office["city"] == state.slots["city"]]
            if not offices:
                return RoutingReplyResult(
                    text={
                        "ru": "Для этого города офис не найден. В каком вы городе?",
                        "kk": "Бұл қалада кеңсе табылмады. Қай қаладасыз?",
                    }[language],
                    actions=["get_offices"],
                )
            label = {"ru": "Офис", "kk": "Кеңсе"}[language]
            hours = {"ru": "Часы работы", "kk": "Жұмыс уақыты"}[language]
            text = " ".join(
                f"{label}: {localized(item['address'])}. {hours}: {localized(item['hours'])}."
                for item in offices
            )
            actions = ["get_offices"]
        elif scenario_id == "SC31":
            label = {"ru": "Способы оплаты", "kk": "Төлем тәсілдері"}[language]
            cash = {"ru": "Наличные", "kk": "Қолма-қол төлем"}[language]
            installments = {"ru": "Рассрочка", "kk": "Бөліп төлеу"}[language]
            methods = "; ".join(localized(method) for method in answer["methods"])
            text = f"{label}: {methods}. {cash}: {localized(answer['cash'])}."
            product = self._string_slot(state, "product_type")
            options = answer["installments"]
            if product:
                # dms_individual is a KB key, never a new product_type slot value.
                key = "dms_individual" if product == "dms" else product
                if key in options:
                    text += f" {installments} ({localized(key)}): {localized(options[key])}."
                else:
                    completed = False
                    text += {
                        "ru": " Условия рассрочки для этого продукта в базе не указаны.",
                        "kk": " Бұл өнімнің бөліп төлеу шарттары қорда көрсетілмеген.",
                    }[language]
            else:
                text += (
                    f" {installments}: "
                    + "; ".join(
                        f"{localized(key)}: {localized(value)}" for key, value in options.items()
                    )
                    + "."
                )
            actions = ["kb_lookup"]
        else:
            login = {"ru": "Вход", "kk": "Кіру"}[language]
            sms = {"ru": "Если СМС-код не пришёл", "kk": "СМС коды келмесе"}[language]
            payment = {"ru": "Ошибка оплаты", "kk": "Төлем қатесі"}[language]
            text = (
                f"{login}: {localized(answer['login'])} "
                f"{sms}: {'; '.join(localized(step) for step in answer['sms_code_not_received'])}. "
                f"{payment}: {'; '.join(localized(step) for step in answer['payment_error'])}."
            )
            # The source advises escalation; this app cannot perform that transfer.
            text += {
                "ru": " Если шаги не помогли, нужна помощь оператора; перевод здесь не подключён.",
                "kk": (
                    " Қадамдар көмектеспесе, оператор қажет; мұнда операторға қосу іске қосылмаған."
                ),
            }[language]
            actions = ["kb_lookup"]
        return RoutingReplyResult(
            text=text,
            actions=actions,
            source_keys=[f"knowledge_base.{topic}"],
            completed=completed,
        )

    def _private_reply(self, state: DialogState, scenario_id: str) -> RoutingReplyResult:
        assert self.backend is not None
        language = state.response_language
        phone, iin = self._string_slot(state, "phone"), self._string_slot(state, "iin")
        if phone is None and iin is None:
            return self._ask(state, "phone")
        client = find_client(self.backend, phone=phone, iin=iin)
        if not client.success:
            return RoutingReplyResult(
                text={
                    "ru": "Не удалось найти клиента в демонстрационных данных. Уточните телефон.",
                    "kk": "Демонстрациялық деректерден клиент табылмады. Телефонды нақтылаңызшы.",
                }[language],
                actions=["find_client"],
            )
        identifier = "policy_number" if scenario_id == "SC25" else "claim_number"
        function = get_policy if scenario_id == "SC25" else get_claim
        action = "get_policy" if scenario_id == "SC25" else "get_claim"
        result = function(
            self.backend,
            client_id=client.data["client_id"],
            **{identifier: self._string_slot(state, identifier)},
        )
        actions = ["find_client", action]
        if not result.success:
            missing = self._string_slot(state, identifier) is None
            text = (
                self._ask(state, identifier).text
                if missing
                else {
                    "ru": (
                        "В демонстрационных данных запись для этого клиента не найдена. "
                        "Уточните номер."
                    ),
                    "kk": (
                        "Демонстрациялық деректерден бұл клиенттің жазбасы табылмады. "
                        "Нөмірді нақтылаңызшы."
                    ),
                }[language]
            )
            return RoutingReplyResult(text=text, actions=actions)
        record = result.data
        prefix = {"ru": "По демонстрационным данным", "kk": "Демонстрациялық деректер бойынша"}[
            language
        ]
        completed = True
        if scenario_id == "SC25":
            reference = str(self.catalog.get_compact_router_catalog()["reference_date"])
            current = date.fromisoformat(reference)
            start, end = (
                date.fromisoformat(record["start_date"]),
                date.fromisoformat(record["end_date"]),
            )
            status = "future" if current < start else "expired" if current > end else "active"
            label = {
                "ru": {
                    "future": "ещё не начал действовать",
                    "expired": "срок истёк",
                    "active": "действует",
                },
                "kk": {
                    "future": "әлі күшіне енбеген",
                    "expired": "мерзімі аяқталған",
                    "active": "жарамды",
                },
            }[language][status]
            text = (
                f"{prefix}, {reference}: {record['policy_number']} — {label}. "
                f"{record['start_date']} — {record['end_date']}."
            )
            source = f"mock_backend.policies.{record['policy_number']}"
        else:
            label = {"ru": "Статус", "kk": "Мәртебесі"}[language]
            status = _localized_source(record["status"], language)
            next_step = _localized_source(record["next_step"], language)
            completed = status is not None and next_step is not None
            text = (
                f"{prefix}: {record['claim_number']}. "
                f"{label}: {status or _UNAVAILABLE_TEXT[language]}. "
                f"{next_step or _UNAVAILABLE_TEXT[language]}"
            )
            source = f"mock_backend.claims.{record['claim_number']}"
        return RoutingReplyResult(
            text=text,
            actions=actions,
            source_keys=["mock_backend.clients", source],
            completed=completed,
        )
