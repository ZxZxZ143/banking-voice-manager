"""Insurance-only grounded calculations and assisted workflows.

The supplied backend is a read-only synthetic snapshot. Quotes are calculated;
external writes/delivery end in an application handoff, never fabricated success.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.packs.insurance_manager.data.models import Scenario
from app.packs.insurance_manager.data.repositories import KnowledgeRepository, MockBackendRepository
from app.packs.insurance_manager.response.lookup import (
    IDENTIFIERS,
    can_ask,
    lookup_client,
    lookup_exhausted,
    lookup_record,
    remember,
)
from app.packs.insurance_manager.scenarios.catalog import ScenarioCatalog
from app.packs.insurance_manager.state import DialogState

_SOURCE_TRANSLATIONS = {
    "Driving under the influence": ("вождение в состоянии опьянения", "мас күйінде жүргізу"),
    "Driver not listed in the policy": ("водитель не указан в полисе", "жүргізуші полисте жоқ"),
    "Intentional damage": ("умышленный ущерб", "қасақана келтірілген зиян"),
    "Wear and tear, mechanical breakdown": ("износ и поломки", "тозу және ақаулар"),
    "Using the car as a taxi unless declared": (
        "использование как такси без уведомления",
        "хабарламай такси ретінде пайдалану",
    ),
    "Damage due to unauthorized reconstruction": (
        "ущерб от несогласованной перепланировки",
        "келісілмеген қайта жоспарлаудан болған зиян",
    ),
    "Wear and tear": ("износ", "тозу"),
    "Professional sports": ("профессиональный спорт", "кәсіби спорт"),
    "Intoxication": ("опьянение", "мас болу"),
    "Self-harm": ("самоповреждение", "өзіне зиян келтіру"),
    "Illness (not an accident)": ("болезнь, не несчастный случай", "ауру, жазатайым оқиға емес"),
    "Therapist visits": ("приём терапевта", "терапевт қабылдауы"),
    "Specialists by therapist referral": (
        "специалисты по направлению терапевта",
        "терапевт жолдамасымен мамандар",
    ),
    "Basic lab tests by referral": (
        "базовые анализы по направлению",
        "жолдамамен негізгі талдаулар",
    ),
    "Emergency care": ("экстренная помощь", "шұғыл көмек"),
    "Emergency hospitalization": ("экстренная госпитализация", "шұғыл ауруханаға жатқызу"),
    "MRI and CT": ("МРТ и КТ", "МРТ және КТ"),
    "Dentistry": ("стоматология", "стоматология"),
    "Planned hospitalization": ("плановая госпитализация", "жоспарлы ауруханаға жатқызу"),
    "Outpatient medications": ("амбулаторные лекарства", "амбулаториялық дәрілер"),
    "Specialists without referral (ENT, cardiologist, gynecologist, etc.)": (
        "специалисты без направления: ЛОР, кардиолог, гинеколог и другие",
        "жолдамасыз мамандар: ЛОР, кардиолог, гинеколог және басқалар",
    ),
    "Lab tests by doctor's referral": (
        "анализы по направлению врача",
        "дәрігер жолдамасымен талдаулар",
    ),
    "Ultrasound": ("УЗИ", "УДЗ"),
    "MRI and CT by referral, up to 2 per year": (
        "МРТ и КТ по направлению, до двух в год",
        "жолдамамен МРТ және КТ, жылына екіге дейін",
    ),
    "Dental treatment (caries, extraction)": (
        "лечение зубов: кариес и удаление",
        "тіс емдеу: кариес және жұлу",
    ),
    "Emergency and planned hospitalization": (
        "экстренная и плановая госпитализация",
        "шұғыл және жоспарлы ауруханаға жатқызу",
    ),
    "Medications during hospitalization": (
        "лекарства во время госпитализации",
        "ауруханада жатқан кездегі дәрілер",
    ),
    "Dental prosthetics and implants": (
        "зубные протезы и импланты",
        "тіс протездері мен импланттар",
    ),
    "Cosmetology": ("косметология", "косметология"),
    "Fire, water damage, theft, natural disasters, liability to neighbours.": (
        "пожар, залив, кража, стихийные бедствия и ответственность перед соседями",
        "өрт, су басу, ұрлық, табиғи апаттар және көршілер алдындағы жауапкершілік",
    ),
    "Damage the driver causes to other people's health and property in a road accident. "
    "Own car is not covered.": (
        "ущерб здоровью и имуществу других людей в ДТП; собственный автомобиль не покрывается",
        "жол апатында өзге адамдардың денсаулығы мен мүлкіне келтірілген зиян; өз көлігі өтелмейді",
    ),
}


def translated_listing(values, language):
    """Unknown source values stay visibly unavailable instead of being guessed."""
    return "; ".join(
        _SOURCE_TRANSLATIONS[value][0 if language == "ru" else 1]
        if value in _SOURCE_TRANSLATIONS
        else "перевод условий нужно уточнить"
        if language == "ru"
        else "шарттар аудармасын нақтылау керек"
        for value in values
    )


class InsuranceReplies:
    def __init__(
        self,
        catalog,
        slots,
        knowledge: KnowledgeRepository,
        backend: MockBackendRepository,
        capabilities=None,
    ):
        self.catalog: ScenarioCatalog = catalog
        self.slots = slots
        self.knowledge = knowledge
        self.backend = backend
        self.capabilities = capabilities
        self.today = date.fromisoformat(catalog.get_compact_router_catalog()["reference_date"])

    def reply(self, state: DialogState, scenario: Scenario, decision=None) -> dict | None:
        sid, lang, values = scenario.scenario_id, state.response_language, state.slots
        if sid in {"SC17", "SC25", "SC31", "SC33", "SC34"}:
            return None

        def text(ru, kk):
            return ru if lang == "ru" else kk

        def answer(
            message,
            sources=(),
            actions=("kb_lookup",),
            completed=True,
            handoff=False,
            expected_slot=None,
        ):
            return dict(
                text=message,
                source_keys=list(sources),
                actions=list(actions),
                completed=completed,
                handoff=handoff,
                expected_slot=expected_slot,
            )

        def ask(name):
            if name in IDENTIFIERS:
                if not can_ask(state, name):
                    return lookup_exhausted(state, scenario, self.capabilities)
                remember(state.identification.requested_fields, name)
            return {
                **answer(getattr(self.slots[name].prompt, lang), actions=(), completed=False),
                "expected_slot": name,
            }

        def transfer(message="", sources=(), actions=(), reason="operation_requires_human"):
            result = answer(
                message
                + text(
                    " Передаю диалог оператору вместе с собранными данными. "
                    "Операция ещё не выполнена.",
                    " Жиналған мәліметтермен бірге диалогты операторға "
                    "тапсырамын. Операция әлі орындалған жоқ.",
                ),
                sources,
                actions,
                completed=False,
                handoff=True,
            )
            if self.capabilities:
                result["manager_summary"] = self.capabilities.summary(
                    state, scenario, actions, reason
                )
            return result

        # Give urgent guidance before collecting identifiers or other required slots.
        if sid == "SC11":
            if values.get("injured") is not None and values.get("location"):
                return transfer(
                    text(
                        "Если нужна экстренная помощь, сначала звоните 112. "
                        "Место происшествия и сведения о пострадавших сохранены в диалоге.",
                        "Шұғыл көмек керек болса, алдымен 112-ге қоңырау шалыңыз. "
                        "Оқиға орны мен зардап шеккендер туралы мәлімет диалогта сақталды.",
                    ),
                    ["knowledge_base.claims.road_accident_now"],
                )
            return answer(
                text(
                    "Если есть пострадавшие, сначала звоните 112. Включите аварийную сигнализацию, "
                    "выставьте знак, сфотографируйте место, повреждения и номера автомобилей. "
                    "Не перемещайте машины до оформления ДТП. Есть пострадавшие? Где вы сейчас?",
                    "Зардап шеккендер болса, алдымен 112-ге қоңырау шалыңыз. Апаттық шамды қосып, "
                    "белгі қойыңыз, оқиға орнын, зақым мен көлік нөмірлерін суретке түсіріңіз. "
                    "Жол апаты рәсімделгенше көліктерді қозғамаңыз. Зардап "
                    "шеккендер бар ма? Қай жердесіз?",
                ),
                ["knowledge_base.claims.road_accident_now"],
                completed=False,
                handoff=values.get("injured") is True,
            )
        if sid == "SC15":
            guidance = text(
                "По условиям туристической страховки сначала свяжитесь с круглосуточной "
                "медицинской помощью. Самостоятельно оплаченные расходы возмещаются "
                "только по предварительному согласованию с assistance.",
                "Саяхат сақтандыруы бойынша алдымен тәулік бойғы медициналық көмекке "
                "хабарласыңыз. Өзіңіз төлеген шығындар assistance қызметімен алдын ала "
                "келісілгенде ғана өтеледі.",
            )
            missing = next(
                (
                    name
                    for name in scenario.slots.required
                    if name != "policy_number" and values.get(name) in (None, "", [])
                ),
                None,
            )
            if missing:
                return {
                    **ask(missing),
                    "fact_text": guidance,
                    "source_keys": ["knowledge_base.products.travel.notes"],
                }
            # Urgent guidance precedes the shared finite identification path below.
        if sid == "SC38":
            guidance = text(
                "Никому не сообщайте СМС-коды, CVV или PIN и не переводите деньги на личную "
                "карту. Saqta не отменяет полис за отказ сообщить код. Статус можно проверить "
                "в приложении.",
                "Ешкімге СМС кодын, CVV немесе PIN айтпаңыз, жеке картаға ақша аудармаңыз. "
                "Saqta код бермегеніңіз үшін полисті жоймайды. Мәртебесін қолданбадан "
                "тексеруге болады.",
            )
            missing = next(
                (name for name in scenario.slots.required if values.get(name) in (None, "", [])),
                None,
            )
            if missing:
                return {
                    **ask(missing),
                    "fact_text": guidance,
                    "source_keys": ["knowledge_base.fraud_policy"],
                }
            return transfer(
                guidance,
                ["knowledge_base.fraud_policy"],
            )
        if sid == "SC09":
            prices = self.knowledge.get("products.dms.individual_price_per_year_kzt")
            return answer(
                text(
                    "ДМС доступно через работодателя и индивидуально. "
                    "Годовые тарифы в демонстрационных данных: "
                    f"Basic — {prices['Basic']} тенге; Comfort — {prices['Comfort']} тенге. "
                    "Basic включает базовые анализы и специалистов по направлению терапевта; "
                    "Comfort дополнительно включает стоматологическое лечение и "
                    "МРТ/КТ по направлению.",
                    f"Ерікті медициналық сақтандыру жұмыс беруші арқылы немесе жеке рәсімделеді. "
                    f"Демонстрациялық жылдық тарифтер: Basic — {prices['Basic']} теңге; "
                    f"Comfort — {prices['Comfort']} теңге. Basic жолдамамен негізгі талдаулар мен "
                    "мамандарды, Comfort қосымша тіс емдеуді және жолдамамен МРТ/КТ-ны қамтиды.",
                ),
                ["knowledge_base.products.dms"],
            )
        client_id = state.client_id
        if scenario.requires_identification:
            identifier = next(
                (
                    name
                    for name in ("policy_number", "claim_number")
                    if name in scenario.slots.required
                ),
                None,
            )
            # Keep the existing business-question order when the requested record number
            # was supplied. An alternative identity still bypasses a missing record field.
            if (
                identifier
                and values.get(identifier)
                and not client_id
                and not values.get("phone")
                and not values.get("iin")
            ):
                missing_detail = next(
                    (
                        name
                        for name in scenario.slots.required
                        if name not in IDENTIFIERS and values.get(name) in (None, "", [])
                    ),
                    None,
                )
                if missing_detail:
                    return ask(missing_detail)
            if (
                identifier
                and not values.get(identifier)
                and not client_id
                and not values.get("phone")
                and not values.get("iin")
                and not state.identification.attempted_fields
                and can_ask(state, identifier)
            ):
                return ask(identifier)
            client_id, alternative, checks = lookup_client(state, self.backend)
            if alternative:
                return alternative
            if not client_id:
                return lookup_exhausted(state, scenario, self.capabilities, checks)
            if identifier:
                record, record_checks = lookup_record(state, self.backend, identifier)
                checks += record_checks
                if record is None:
                    if not values.get(identifier) and can_ask(state, identifier):
                        return {**ask(identifier), "actions": checks}
                    return lookup_exhausted(state, scenario, self.capabilities, checks)
                values[identifier] = record[identifier]
        for name in scenario.slots.required:
            if name in {"phone", "iin"} and client_id and scenario.requires_identification:
                continue
            if name == "phone" and values.get("iin"):
                continue
            if values.get(name) in (None, "", []):
                return ask(name)

        if sid in {"SC01", "SC02", "SC03", "SC06", "SC07", "SC08"}:
            return self._quote(state, sid, ask, answer, transfer, text)
        if sid == "SC18":
            product = values["product_type"]
            key = "ogpo_victim" if product == "ogpo" else product
            docs = self.knowledge.get("claims.documents")
            if key not in docs:
                return answer(
                    text(
                        "Для этого продукта перечень документов не указан.",
                        "Бұл өнім үшін құжаттар тізімі көрсетілмеген.",
                    ),
                    ["knowledge_base.claims.documents"],
                )
            # Source-specific translation, rather than generated claims/documents.
            translated = {
                "ID card": ("удостоверение личности", "жеке куәлік"),
                "Driving licence": ("водительское удостоверение", "жүргізуші куәлігі"),
                "Vehicle registration certificate": ("техпаспорт", "көліктің тіркеу куәлігі"),
                "Road accident documents from the police": (
                    "документы полиции о ДТП",
                    "жол апаты туралы полиция құжаттары",
                ),
                "Bank details": ("банковские реквизиты", "банк деректемелері"),
                "Photos of the damage": ("фотографии повреждений", "зақым суреттері"),
                "Police documents (if police was involved)": (
                    "документы полиции, если она участвовала",
                    "полиция қатысқан болса, оның құжаттары",
                ),
                "Policy number": ("номер полиса", "полис нөмірі"),
                "Act from the building management company (for water damage) "
                "or fire service report (for fire)": (
                    "акт управляющей компании при заливе или пожарной службы при пожаре",
                    "су басса басқарушы компания актісі, өрт болса өрт қызметінің актісі",
                ),
                "Medical certificate from the trauma centre or hospital": (
                    "справка травмпункта или больницы",
                    "жарақат пунктінің немесе аурухананың анықтамасы",
                ),
                "Medical documents from abroad": (
                    "медицинские документы из-за границы",
                    "шетелдегі медициналық құжаттар",
                ),
                "Receipts (only for expenses agreed with assistance)": (
                    "чеки только по согласованным с assistance расходам",
                    "assistance қызметімен келісілген шығындардың түбіртектері",
                ),
            }
            if any(value not in translated for value in docs[key]):
                return answer(
                    text(
                        "Актуальный перевод списка нужно уточнить у оператора.",
                        "Тізімнің өзекті аудармасын оператордан нақтылау керек.",
                    )
                )
            listing = "; ".join(text(*translated[value]) for value in docs[key])
            return answer(
                text("Нужны: ", "Қажет: ")
                + listing
                + text(
                    ". Загрузите документы в «Мои заявления» или отправьте на ",
                    ". Құжаттарды «Менің өтініштерім» бөліміне жүктеңіз немесе "
                    "мына мекенжайға жіберіңіз: ",
                )
                + self.knowledge.get("company.claims_email"),
                [f"knowledge_base.claims.documents.{key}", "knowledge_base.company.claims_email"],
            )
        if sid == "SC23":
            specialty = str(values.get("doctor_specialty", "")).casefold()
            aliases = {
                "терапевт": "therapist",
                "лор": "ent",
                "стоматолог": "dentist",
                "тіс дәрігері": "dentist",
                "гинеколог": "gynecologist",
                "кардиолог": "cardiologist",
                "педиатр": "pediatrician",
            }
            specialty = aliases.get(specialty, specialty)
            clinics = [
                record
                for record in self.knowledge.get("clinics")
                if record["city"] == values["city"]
                and (not specialty or specialty in [s.casefold() for s in record["specialties"]])
            ]
            return answer(
                text("Партнёрские клиники: ", "Серіктес клиникалар: ")
                + "; ".join(record["name"] + " — " + record["address"] for record in clinics)
                if clinics
                else text(
                    "Для этого города клиники в базе не указаны.",
                    "Бұл қала үшін клиникалар қорда көрсетілмеген.",
                ),
                ["knowledge_base.clinics"],
                ["list_clinics"],
            )
        if sid == "SC32":
            matches = self.backend.find("clients", iin=values["iin"])
            bm = (
                matches[0]["bm_class"]
                if matches
                else self.backend.get_defaults()["unknown_iin_bm_class"]
            )
            return answer(
                text(
                    f"В демонстрационных данных класс бонус-малус: {bm}. "
                    "Неизвестному ИИН присваивается класс 3 по правилам этой базы.",
                    f"Демонстрациялық деректердегі бонус-малус класы: {bm}. "
                    "Белгісіз ЖСН-ге осы қор ережесімен 3-класс беріледі.",
                ),
                ["mock_backend.clients", "mock_backend.defaults"],
                ["get_bm_class"],
            )
        if sid == "SC40":
            product = values.get("product_type")
            if not product:
                return ask("product_type")
            terms = self.knowledge.get(f"products.{product}")
            sections = []
            if "covers" in terms:
                sections.append(
                    text("Покрывается: ", "Қамтылады: ")
                    + translated_listing([terms["covers"]], lang)
                )
            if product == "casco":
                sections.append(
                    text("Варианты франшизы в тарифе: ", "Тарифтегі франшиза нұсқалары: ")
                    + ", ".join(terms["pricing"]["franchise_coef"])
                    + text(" тенге.", " теңге.")
                )
            # Exact source facts: numbers and exclusions must never come from an LLM.
            if "exclusions" in terms:
                sections.append(
                    text("Не покрывается: ", "Қамтылмайды: ")
                    + translated_listing(terms["exclusions"], lang)
                )
            if sections:
                return answer(". ".join(sections), [f"knowledge_base.products.{product}"])
            return answer(
                text(
                    "Условия продукта нужно уточнить: в базе нет ответа на этот "
                    "вопрос. Можно обратиться к оператору.",
                    "Өнім шарттарын нақтылау керек: қорда бұл сұрақтың жауабы "
                    "жоқ. Операторға жүгінуге болады.",
                ),
                [f"knowledge_base.products.{product}"],
            )

        if sid == "SC24":
            return transfer(
                text(
                    "Электронная карта ДМС находится в приложении в разделе «Мои полисы». "
                    "В клинике достаточно показать её на экране. Отправку СМС выполняет оператор.",
                    "Электрондық медициналық карта қолданбаның «Менің полистерім» бөлімінде. "
                    "Клиникада экраннан көрсету жеткілікті. СМС жіберуді оператор орындайды.",
                ),
                ["knowledge_base.products.dms.e_card"],
                ["find_client", "kb_lookup"],
            )

        if sid == "SC30":
            records = self.backend.find(
                "payments", client_id=client_id, date=values["payment_date"]
            )
            if values.get("payment_amount") is not None:
                records = [
                    record for record in records if record["amount"] == values["payment_amount"]
                ]
            if not records:
                return answer(
                    text(
                        "В демонстрационных данных платёж не найден. Уточните дату и "
                        "сумму; оператор может проверить банк.",
                        "Демонстрациялық деректерден төлем табылмады. Күнін және "
                        "сомасын нақтылаңыз; оператор банктен тексере алады.",
                    ),
                    ["mock_backend.payments"],
                    ["find_client", "check_payment"],
                    completed=False,
                    expected_slot="payment_date",
                )
            status_labels = {
                "success": ("успешен", "сәтті"),
                "failed": ("не прошёл", "өтпеді"),
                "pending": ("ожидает обработки", "өңделуде"),
            }
            description = "; ".join(
                f"{r['date']} — {r['amount']} "
                + text("тенге", "теңге")
                + ", "
                + text(
                    *status_labels.get(
                        r["status"], ("статус нужно уточнить", "мәртебені нақтылау керек")
                    )
                )
                for r in records
            )
            return transfer(
                text("По демонстрационным записям: ", "Демонстрациялық жазбалар бойынша: ")
                + description
                + ".",
                ["mock_backend.payments"],
                ["find_client", "check_payment"],
            )

        policy = None
        if values.get("policy_number") and client_id:
            records = self.backend.find(
                "policies", client_id=client_id, policy_number=values["policy_number"]
            )
            if len(records) != 1:
                return answer(
                    text(
                        "Полис для этого клиента не найден. Уточните номер полиса.",
                        "Бұл клиенттің полисі табылмады. Полис нөмірін нақтылаңыз.",
                    ),
                    actions=["find_client", "get_policy"],
                    completed=False,
                )
            policy = records[0]

        if sid == "SC26":
            records = self.backend.find("policies", client_id=client_id)
            if values.get("policy_number"):
                records = [r for r in records if r["policy_number"] == values["policy_number"]]
            if not records:
                return answer(
                    text("Полисы для клиента не найдены.", "Клиенттің полистері табылмады."),
                    actions=["find_client", "get_policies"],
                    completed=False,
                )
            return transfer(
                text(
                    "В демонстрационных данных найдены полисы: ",
                    "Демонстрациялық деректерде табылған полистер: ",
                )
                + ", ".join(r["policy_number"] for r in records)
                + text(". Документы ещё не отправлены.", ". Құжаттар әлі жіберілген жоқ."),
                ["mock_backend.policies"],
                ["find_client", "get_policies"],
            )
        if sid == "SC22" and policy:
            if policy["product"] != "dms":
                return answer(
                    text(
                        "Этот полис не относится к ДМС.",
                        "Бұл полис медициналық сақтандыруға жатпайды.",
                    ),
                    ["mock_backend.policies"],
                    ["find_client", "get_policy"],
                )
            package = policy.get("details", {}).get("package")
            if package not in self.knowledge.get("products.dms.packages"):
                return transfer(
                    text(
                        "Пакет ДМС в записи не указан.", "Жазбада медициналық пакет көрсетілмеген."
                    )
                )
            terms = self.knowledge.get(f"products.dms.packages.{package}")
            return answer(
                text(
                    f"Пакет {package}. Покрывается: ",
                    f"{package} пакеті. Қамтылады: ",
                )
                + translated_listing(terms["covered"], lang)
                + text(". Не покрывается: ", ". Қамтылмайды: ")
                + translated_listing(terms["not_covered"], lang)
                + text(
                    ". Соответствие вашей услуги уточнит оператор.",
                    ". Қызметіңізге сәйкестігін оператор нақтылайды.",
                ),
                [f"knowledge_base.products.dms.packages.{package}", "mock_backend.policies"],
                ["find_client", "get_policy", "kb_lookup"],
            )
        if sid == "SC28" and policy:
            paid = any(
                r["status"] == "paid" and r["policy_number"] == policy["policy_number"]
                for r in self.backend.find("claims", client_id=client_id)
            )
            if paid:
                return answer(
                    text(
                        "По этому полису есть выплаченный страховой случай. По "
                        "правилам базы возврат не предусмотрен. Полис не расторгнут.",
                        "Бұл полис бойынша сақтандыру төлемі жасалған. Қор ережесі "
                        "бойынша ақша қайтарылмайды. Полис тоқтатылған жоқ.",
                    ),
                    ["mock_backend.claims", "knowledge_base.cancellation"],
                    ["find_client", "get_policy", "get_claim"],
                )
            return transfer(
                text(
                    "По правилам базы возврат рассчитывается за неиспользованные "
                    "полные месяцы с удержанием 10%; срок возврата — 10 рабочих "
                    "дней. Полис пока не расторгнут.",
                    "Қор ережесі бойынша пайдаланылмаған толық айлар үшін 10% "
                    "ұсталып қайтарылады; мерзімі — 10 жұмыс күні. Полис әлі "
                    "тоқтатылған жоқ.",
                ),
                ["knowledge_base.cancellation"],
                ["find_client", "get_policy"],
            )
        if sid in {"SC19", "SC20"} and client_id:
            records = self.backend.find(
                "claims", client_id=client_id, claim_number=values["claim_number"]
            )
            if not records:
                return answer(
                    text(
                        "Заявление этого клиента не найдено. Уточните номер.",
                        "Бұл клиенттің өтініші табылмады. Нөмірін нақтылаңыз.",
                    ),
                    actions=["find_client", "get_claim"],
                    completed=False,
                )

        if sid == "SC12":
            policies = [
                record
                for record in self.backend.get_all("policies")
                if record.get("details", {}).get("vehicle_plate") == values["culprit_vehicle_plate"]
            ]
            if not policies:
                return transfer(
                    text(
                        (
                            "По указанному автомобилю полис в доступной базе не найден. "
                            "Проверку и регистрацию случая продолжит специалист."
                        ),
                        (
                            "Көрсетілген көлік полисі қорда табылмады. Тексеру мен оқиғаны "
                            "тіркеуді маман жалғастырады."
                        ),
                    ),
                    reason="record_not_found",
                )
            return transfer(
                text(
                    (
                        "Сведения об автомобиле и происшествии собраны. Заявление должен "
                        "зарегистрировать специалист."
                    ),
                    "Көлік пен оқиға туралы мәліметтер жиналды. Өтінішті маман тіркеуі керек.",
                ),
                ["mock_backend.policies"],
                ["get_policy"],
            )

        # All remaining catalog workflows collect their real required slots and
        # hand over to the actual authority; no ticket, booking or sent SMS is invented.
        sources = ["mock_backend.policies"] if policy else []
        actions = ["find_client", "get_policy"] if policy else ["find_client"] if client_id else []
        if sid in {"SC19", "SC20"}:
            actions.append("get_claim")
            sources.append("mock_backend.claims")
        if sid == "SC04":
            self.backend.find("clients", iin=values["new_driver_iin"])
            actions.append("get_bm_class")
        unavailable = self.capabilities.next_unavailable(scenario) if self.capabilities else None
        descriptions = {
            "update_policy": ("изменение полиса", "полисті өзгерту"),
            "renew_policy": ("продление полиса", "полисті ұзарту"),
            "cancel_policy": ("расторжение полиса", "полисті тоқтату"),
            "create_claim": ("регистрацию страхового случая", "сақтандыру оқиғасын тіркеу"),
            "create_dispute": ("регистрацию возражения", "қарсылықты тіркеу"),
            "book_inspection": ("запись на осмотр", "тексерілуге жазылу"),
            "book_appointment": ("запись к врачу", "дәрігерге жазылу"),
            "update_contact": ("изменение контактов", "байланыс мәліметтерін өзгерту"),
            "request_document": ("подготовку документа", "құжат дайындау"),
            "create_callback": ("организацию обратного звонка", "кері қоңырауды ұйымдастыру"),
            "create_complaint": ("регистрацию жалобы", "шағымды тіркеу"),
        }
        operation = text(
            *descriptions.get(unavailable, ("дальнейшую обработку", "әрі қарай өңдеуді"))
        )
        return transfer(
            text(
                f"Данные собраны. {operation.capitalize()} выполнит специалист.",
                f"Мәліметтер жиналды. {operation.capitalize()} маман орындайды.",
            ),
            sources,
            actions,
        )

    def _quote(self, state, sid, ask, answer, transfer, text):
        values = state.slots
        product = {
            "SC01": "ogpo",
            "SC02": "ogpo",
            "SC03": "casco",
            "SC06": "travel",
            "SC07": "property",
            "SC08": "accident",
        }[sid]
        data = self.knowledge.get(f"products.{product}")
        sources = [f"knowledge_base.products.{product}"]
        actions = [f"calc_{product}_price"]
        price = None
        details = ""
        if product == "ogpo":
            for name in ("region", "vehicle_type", "drivers_iin"):
                if not values.get(name):
                    return ask(name)
            classes = []
            for iin in values["drivers_iin"]:
                clients = self.backend.find("clients", iin=iin)
                classes.append(
                    clients[0]["bm_class"]
                    if clients
                    else self.backend.get_defaults()["unknown_iin_bm_class"]
                )
            rules = data["pricing"]
            price = (
                Decimal(str(rules["base_by_region_kzt"][values["region"]]))
                * Decimal(str(rules["vehicle_type_coef"][values["vehicle_type"]]))
                * max(Decimal(str(rules["bm_coef"][bm])) for bm in classes)
            )
            details = text("Срок расчёта — 12 месяцев. ", "Есептеу мерзімі — 12 ай. ")
            actions.insert(0, "get_bm_class")
            sources.extend(["mock_backend.clients", "mock_backend.defaults"])
        elif product == "casco":
            age = self.today.year - values["car_year"]
            if values["car_value"] <= 0 or age < 0:
                return answer(
                    text(
                        "Уточните положительную стоимость и год выпуска автомобиля.",
                        "Көліктің оң бағасын және шығарылған жылын нақтылаңыз.",
                    ),
                    actions=(),
                    completed=False,
                )
            if age > 10:
                return transfer(
                    text(
                        "Для стандартного КАСКО автомобиль старше допустимого "
                        "возраста. Возможность Lite уточнит оператор.",
                        "Стандартты КАСКО үшін көліктің жасы рұқсат етілгеннен "
                        "үлкен. Lite мүмкіндігін оператор нақтылайды.",
                    ),
                    sources,
                )
            rules = data["pricing"]
            rate = rules["rate_by_car_age"]["0-3" if age <= 3 else "4-7" if age <= 7 else "8-10"]
            franchise = values.get("franchise", 0)
            price = (
                Decimal(values["car_value"])
                * Decimal(str(rate))
                * Decimal(str(rules["franchise_coef"][str(franchise)]))
            )
            details = text(
                f"Standard, франшиза {franchise} тенге. ", f"Standard, франшиза {franchise} теңге. "
            )
        elif product in {"property", "accident"}:
            prices = data["price_per_year_kzt"]
            if str(values["sum_insured"]) not in prices:
                return answer(
                    text(
                        "Для этой страховой суммы тарифа нет. Доступные суммы: ",
                        "Бұл сақтандыру сомасына тариф жоқ. Қолжетімді сомалар: ",
                    )
                    + ", ".join(prices),
                    sources,
                    completed=False,
                )
            price = Decimal(prices[str(values["sum_insured"])])
            if product == "property" and values["property_type"] == "house":
                price *= Decimal(str(data["house_coef"]))
            details = text("За один год. ", "Бір жылға. ")
        else:
            start, end = (
                date.fromisoformat(values["trip_start"]),
                date.fromisoformat(values["trip_end"]),
            )
            if (
                start < self.today
                or end < start
                or values["travelers_count"] <= 0
                or values["traveler_max_age"] < 0
            ):
                return answer(
                    text(
                        "Проверьте даты поездки, количество и возраст путешественников.",
                        "Сапар күндерін, жолаушылар санын және жасын тексеріңіз.",
                    ),
                    actions=(),
                    completed=False,
                )
            if values["traveler_max_age"] > 75:
                return transfer(
                    text(
                        "Страхование путешественников старше 75 лет оформляется "
                        "только через оператора.",
                        "75 жастан асқан жолаушыларды сақтандыру тек оператор арқылы рәсімделеді.",
                    ),
                    sources,
                )
            # Resolve only explicitly named destinations; never guess an unknown zone.
            country = str(values["trip_country"]).strip().casefold()
            zones = {
                "D": {"usa", "united states", "сша", "ақш", "canada", "канада"},
                "B": {
                    "schengen",
                    "шенген",
                    "germany",
                    "германия",
                    "france",
                    "франция",
                    "italy",
                    "италия",
                    "spain",
                    "испания",
                    "uk",
                    "великобритания",
                    "ұлыбритания",
                },
                "A": {
                    "georgia",
                    "грузия",
                    "russia",
                    "россия",
                    "ресей",
                    "kyrgyzstan",
                    "кыргызстан",
                    "қырғызстан",
                    "uzbekistan",
                    "узбекистан",
                    "өзбекстан",
                },
                "C": {
                    "turkey",
                    "турция",
                    "түркия",
                    "uae",
                    "оаэ",
                    "баә",
                    "dubai",
                    "дубай",
                    "thailand",
                    "таиланд",
                    "тайланд",
                    "egypt",
                    "египет",
                    "мысыр",
                },
            }
            zone = next((name for name, names in zones.items() if country in names), None)
            if zone is None:
                return answer(
                    text(
                        "Уточните страну назначения; её тарифная зона не определена "
                        "в базе. Можно обратиться к оператору.",
                        "Баратын елді нақтылаңыз; қорда оның тарифтік аймағы "
                        "анықталмаған. Операторға жүгінуге болады.",
                    ),
                    sources,
                    completed=False,
                )
            zone_data = data["zones"][zone]
            days = (end - start).days + 1
            coefficient = data["pricing"]["age_coef"][
                "0-64" if values["traveler_max_age"] <= 64 else "65-75"
            ]
            price = (
                Decimal(zone_data["rate_per_day_kzt"])
                * days
                * values["travelers_count"]
                * Decimal(str(coefficient))
            )
            details = text(
                f"{days} дней, {values['travelers_count']} человек; "
                f"покрытие {zone_data['coverage']}. ",
                f"{days} күн, {values['travelers_count']} адам; "
                f"өтеу сомасы {zone_data['coverage']}. ",
            )
        price = price.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        message = (
            text(
                f"Предварительная стоимость по демонстрационным тарифам: {price} тенге. ",
                f"Демонстрациялық тариф бойынша алдын ала баға: {price} теңге. ",
            )
            + details
        )
        if sid in {"SC02", "SC06"}:
            return transfer(
                message
                + text(
                    "Полис ещё не выпущен, платёж не списан.",
                    "Полис әлі шығарылған жоқ, төлем алынған жоқ.",
                ),
                sources,
                actions,
            )
        return answer(message, sources, actions)
