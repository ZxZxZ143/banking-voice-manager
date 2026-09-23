"""Offline checks against canonical synthetic data, not live routing accuracy."""

import re

import pytest

from app.agent.schemas import RouterDecision
from app.core.config import Settings
from app.data.loaders import load_starter_kit
from app.data.repositories import KnowledgeRepository, MockBackendRepository
from app.dialog.models import DialogState
from app.response.routing import RoutingReplyGenerator
from app.scenarios.catalog import ScenarioCatalog
from app.scenarios.decision_policy import PolicyResult
from app.tools.read_only import find_client, get_claim, get_policy, kb_lookup


@pytest.fixture
def sources():
    kit = load_starter_kit(Settings(_env_file=None).starter_kit_path)
    knowledge = KnowledgeRepository(kit.knowledge)
    backend = MockBackendRepository(kit.mock_backend)
    return kit, knowledge, backend


@pytest.fixture
def replies(sources):
    kit, knowledge, backend = sources
    return RoutingReplyGenerator(ScenarioCatalog(kit.scenarios), kit.slots, knowledge, backend)


def respond(replies, scenario_id, slots=None, language="ru", **state_fields):
    state = DialogState(
        session_id="offline-read-only",
        active_scenario=scenario_id,
        response_language=language,
        conversation_status="awaiting_user",
        slots=slots or {},
        **state_fields,
    )
    previous = state.model_dump()
    policy = PolicyResult(
        outcome="accept",
        scenario_ids=[scenario_id],
        consecutive_low_confidence=0,
        reason="Offline grounded reply check",
    )
    result = replies.generate_result(state, policy)
    assert state.model_dump() == previous
    assert state.conversation_status == "awaiting_user"
    return result


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_office_reply_uses_only_matching_source_city(replies, sources, language):
    result = respond(replies, "SC33", {"city": "Astana"}, language)
    office = next(item for item in sources[1].get("offices") if item["city"] == "Astana")
    assert "55" in result.text and "Мәңгілік Ел" in result.text
    assert all(time in result.text for time in re.findall(r"\d{2}:\d{2}", office["hours"]))
    assert ("суббота" if language == "ru" else "сенбі") in result.text
    assert not re.search(r"[A-Za-z]", result.text)
    assert "Abai Ave 150" not in result.text
    assert result.actions == ["get_offices"]
    assert result.source_keys == ["knowledge_base.offices"]
    assert result.completed
    assert "SMS" not in result.text


def test_one_missing_city_question_and_unavailable_city_do_not_complete(replies, sources):
    missing = respond(replies, "SC33")
    city = next(slot for slot in sources[0].slots.slots if slot.name == "city")
    assert missing.text == city.prompt.ru
    assert not missing.completed and not missing.actions
    unknown = respond(replies, "SC33", {"city": "Unknown"})
    assert not unknown.completed
    assert "Abai" not in unknown.text


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_payment_answer_is_grounded_and_keeps_dms_enum_unchanged(replies, sources, language):
    result = respond(replies, "SC31", {"product_type": "dms"}, language)
    if language == "ru":
        assert "банковской картой в приложении или на сайте" in result.text
        assert (
            "по ссылке из СМС" in result.text and "банковским переводом для компаний" in result.text
        )
        assert "терминал в любом офисе" in result.text and "Наличные: не принимаются" in result.text
        assert "ДМС для физических лиц): 2 платежа" in result.text
    else:
        assert "қолданбада немесе сайтта банк картасымен" in result.text
        assert "СМС арқылы келген сілтемемен" in result.text and "банк аударымымен" in result.text
        assert "Қолма-қол төлем: қабылданбайды" in result.text
        assert "ерікті медициналық сақтандыру): 2 төлем" in result.text
    assert "4" not in result.text and not re.search(r"[A-Za-z]", result.text)
    assert result.completed and result.actions == ["kb_lookup"]


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_app_help_includes_localized_source_steps_and_no_transfer_claim(replies, language):
    result = respond(replies, "SC34", language=language)
    assert "60" in result.text and "5" in result.text
    if language == "ru":
        assert "одноразовому СМС-коду" in result.text and "проверьте номер телефона" in result.text
        assert "попробуйте другую карту" in result.text and "интернет-платежи" in result.text
        assert "перевод здесь не подключён" in result.text
    else:
        assert "бір реттік СМС коды" in result.text and "телефон нөмірін тексеріңіз" in result.text
        assert "басқа картаны" in result.text and "интернет төлемдерге" in result.text
        assert "операторға қосу іске қосылмаған" in result.text
    assert not re.search(r"[A-Za-z]", result.text)
    assert result.completed
    assert result.actions == ["kb_lookup"]


@pytest.mark.parametrize("product", ["property", "accident"])
def test_missing_product_installment_terms_leave_question_incomplete(replies, product):
    result = respond(replies, "SC31", {"product_type": product})
    assert "Условия рассрочки для этого продукта в базе не указаны" in result.text
    assert not result.completed
    assert result.actions == ["kb_lookup"]
    assert result.source_keys == ["knowledge_base.payments"]


def test_policy_reports_expired_at_dataset_date_and_only_owned_fields(replies):
    result = respond(replies, "SC25", {"phone": "+77010000003"})
    assert result.completed
    assert "2026-10-01" in result.text
    assert "SQ-OGPO-102850" in result.text
    assert "2026-09-29" in result.text and "срок истёк" in result.text
    assert "Yerlan" not in result.text and "222ABC17" not in result.text
    assert result.actions == ["find_client", "get_policy"]


def test_multiple_policies_ask_for_identifier_without_listing_others(replies):
    result = respond(replies, "SC25", {"phone": "+77010000001"})
    assert not result.completed
    assert "номер полиса" in result.text
    assert "SQ-" not in result.text


@pytest.mark.parametrize(
    "scenario_id, number_slot, number",
    [
        ("SC25", "policy_number", "SQ-OGPO-104501"),
        ("SC17", "claim_number", "CL-500198"),
    ],
)
def test_client_id_alone_is_not_identification(replies, scenario_id, number_slot, number):
    result = respond(replies, scenario_id, {number_slot: number}, client_id="C001")
    assert not result.completed and result.actions == []
    assert "телефона" in result.text
    assert number not in result.text


@pytest.mark.parametrize(
    "scenario_id, number_slot, number",
    [
        ("SC25", "policy_number", "SQ-OGPO-104501"),
        ("SC17", "claim_number", "CL-500198"),
    ],
)
def test_cross_client_identifiers_do_not_disclose_records(
    replies, scenario_id, number_slot, number
):
    result = respond(replies, scenario_id, {"phone": "+77010000002", number_slot: number})
    assert not result.completed
    assert number not in result.text
    assert "2027-03-14" not in result.text and "185000" not in result.text


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_claim_status_uses_owned_record_and_localizes_next_step(replies, sources, language):
    result = respond(replies, "SC17", {"phone": "+77010000007"}, language)
    record = sources[2].find("claims", client_id="C007")[0]
    assert result.completed
    assert record["claim_number"] in result.text
    assert ("на рассмотрении" if language == "ru" else "қарастырылып жатыр") in result.text
    assert "2026-10-09" in result.text
    assert (
        "Все документы получены" if language == "ru" else "Барлық құжаттар алынды"
    ) in result.text
    assert not re.search(r"[A-Za-z]", result.text.replace(record["claim_number"], ""))
    assert "2026-05-29" not in result.text


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_all_source_offices_and_claims_have_grounded_localized_replies(replies, sources, language):
    kit, knowledge, backend = sources
    before_knowledge, before_claims = knowledge.get_all(), backend.get_all("claims")
    for office in knowledge.get("offices"):
        result = respond(replies, "SC33", {"city": office["city"]}, language)
        assert result.completed
        assert office["address"].split()[-1] in result.text
        assert all(time in result.text for time in re.findall(r"\d{2}:\d{2}", office["hours"]))
        assert not re.search(r"[A-Za-z]", result.text)
    for claim in backend.get_all("claims"):
        owner = next(
            item for item in kit.mock_backend.clients if item.client_id == claim["client_id"]
        )
        result = respond(
            replies, "SC17", {"phone": owner.phone, "claim_number": claim["claim_number"]}, language
        )
        assert result.completed and claim["claim_number"] in result.text
        assert all(number in result.text for number in re.findall(r"\d+", claim["next_step"]))
        assert not re.search(r"[A-Za-z]", result.text.replace(claim["claim_number"], ""))
    assert knowledge.get_all() == before_knowledge and backend.get_all("claims") == before_claims


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_all_installment_products_are_localized_without_english_internal_keys(replies, language):
    result = respond(replies, "SC31", language=language)
    assert result.completed and "2" in result.text and "4" in result.text
    assert ("без переплаты" if language == "ru" else "артық төлемсіз") in result.text
    assert ("только полная оплата" if language == "ru" else "тек толық төлем") in result.text
    assert not re.search(r"[A-Za-z]", result.text)


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_approved_claim_preserves_distinct_assessment_amounts_and_payment_date(
    replies, sources, language
):
    claim = next(item for item in sources[0].mock_backend.claims if item.status == "approved")
    owner = next(
        item for item in sources[0].mock_backend.clients if item.client_id == claim.client_id
    )
    result = respond(
        replies, "SC17", {"phone": owner.phone, "claim_number": claim.claim_number}, language
    )
    assert result.completed
    assert "412 000" in result.text and "830 000" in result.text and "2026-10-02" in result.text
    assert ("независимой оценке" if language == "ru" else "тәуелсіз бағалауына") in result.text
    assert ("одобрено" if language == "ru" else "мақұлданды") in result.text


@pytest.mark.parametrize("language", ["ru", "kk"])
@pytest.mark.parametrize("topic", ["offices", "payments", "app_help", "claim_status", "claim_step"])
def test_unknown_source_text_is_not_rendered_or_silently_replaced_with_facts(
    sources, topic, language
):
    kit = sources[0]
    knowledge_data = kit.knowledge.model_copy(deep=True)
    backend_data = kit.mock_backend.model_copy(deep=True)
    unknown = "Unmapped English source content 99999"
    if topic == "offices":
        knowledge_data.offices[0]["address"] = unknown
        scenario, slots = "SC33", {"city": knowledge_data.offices[0]["city"]}
    elif topic == "payments":
        knowledge_data.payments["methods"] = [unknown]
        scenario, slots = "SC31", {}
    elif topic == "app_help":
        knowledge_data.app_help["login"] = unknown
        scenario, slots = "SC34", {}
    else:
        claim = backend_data.claims[0]
        owner = next(item for item in backend_data.clients if item.client_id == claim.client_id)
        setattr(claim, "status" if topic == "claim_status" else "next_step", unknown)
        scenario, slots = "SC17", {"phone": owner.phone, "claim_number": claim.claim_number}
    replies = RoutingReplyGenerator(
        ScenarioCatalog(kit.scenarios),
        kit.slots,
        KnowledgeRepository(knowledge_data),
        MockBackendRepository(backend_data),
    )
    result = respond(replies, scenario, slots, language)
    assert not result.completed and unknown not in result.text and "99999" not in result.text
    assert ("пока недоступны" if language == "ru" else "әзірге қолжетімсіз") in result.text


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_policy_reply_localizes_status_and_preserves_only_identifiers_and_dates(replies, language):
    result = respond(replies, "SC25", {"phone": "+77010000003"}, language)
    assert result.completed and "SQ-OGPO-102850" in result.text
    assert "2026-09-29" in result.text and "2026-10-01" in result.text
    assert ("срок истёк" if language == "ru" else "мерзімі аяқталған") in result.text
    assert not re.search(r"[A-Za-z]", result.text.replace("SQ-OGPO-102850", ""))


def test_exact_helpers_reject_ambiguous_or_conflicting_identity_and_return_copies(sources):
    _, knowledge, backend = sources
    assert not find_client(backend).success
    assert not find_client(backend, phone="invalid").success
    assert not find_client(backend, phone="+77010000001", iin="920607400233").success
    assert find_client(backend, iin="850314300121").data == {"client_id": "C001"}
    assert not get_policy(backend, client_id="C001").success
    assert not get_policy(backend, client_id="C002", policy_number="SQ-OGPO-104501").success
    assert not get_claim(backend, client_id="C002", claim_number="CL-500198").success
    result = get_claim(backend, client_id="C001")
    assert set(result.data) == {"claim_number", "status", "next_step"}
    result.data["status"] = "changed"
    assert get_claim(backend, client_id="C001").data["status"] == "paid"
    assert not kb_lookup(knowledge, "payments.missing").success
    payment_result = kb_lookup(knowledge, "payments.methods")
    payment_result.data["answer"].clear()
    assert kb_lookup(knowledge, "payments.methods").data["answer"]


def test_uncertain_decision_can_supply_one_clarification_without_business_actions(replies):
    decision = RouterDecision.model_construct(clarification_question="О полисе или о выплате?")
    state = DialogState(session_id="clarify")
    policy = PolicyResult(
        outcome="clarify",
        scenario_ids=["SYS_UNCLEAR"],
        consecutive_low_confidence=0,
        reason="Offline ambiguity",
    )
    # model_construct does not retain unknown extras; add the optional forthcoming field
    # solely to verify the backward-compatible getattr path before/after schema updates.
    object.__setattr__(decision, "clarification_question", "О полисе или о выплате?")
    result = replies.generate_result(state, policy, decision)
    assert result.text == "О полисе или о выплате?"
    assert not result.actions and not result.completed
