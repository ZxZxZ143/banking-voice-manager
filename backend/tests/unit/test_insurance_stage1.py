"""Domain examples protect quote arithmetic, input bounds and ownership."""

import pytest

from app.core.config import Settings
from app.core.services import build_services
from app.dialog.models import DialogState
from app.scenarios.decision_policy import PolicyResult


@pytest.fixture(scope="module")
def replies():
    return build_services(Settings(_env_file=None)).messages.replies


def respond(replies, sid, slots, language="ru"):
    return replies.generate_result(
        DialogState(
            session_id="quote", active_scenario=sid, response_language=language, slots=slots
        ),
        PolicyResult(
            outcome="accept",
            scenario_ids=[sid],
            consecutive_low_confidence=0,
            reason="Offline domain test",
        ),
    )


@pytest.mark.parametrize("language", ["ru", "kk"])
@pytest.mark.parametrize(
    ("sid", "slots", "price"),
    [
        ("SC01", dict(region="almaty", vehicle_type="car", drivers_iin=["850314300121"]), 30400),
        (
            "SC01",
            dict(region="almaty", vehicle_type="car", drivers_iin=["850314300121", "111111111111"]),
            38000,
        ),
        ("SC03", dict(car_value=10000000, car_year=2024, franchise=100000), 320000),
        ("SC07", dict(property_type="house", sum_insured=10000000), 37500),
        ("SC08", dict(sum_insured=3000000), 15000),
        (
            "SC06",
            dict(
                trip_country="Түркия",
                trip_start="2026-10-10",
                trip_end="2026-10-23",
                travelers_count=2,
                traveler_max_age=65,
            ),
            61600,
        ),
    ],
)
def test_quote_uses_real_tariffs_and_inclusive_travel_days(replies, language, sid, slots, price):
    result = respond(replies, sid, slots, language)
    assert str(price) in result.text
    assert result.source_keys[0].startswith("knowledge_base.products.")
    assert result.actions[0] in {
        "get_bm_class",
        "calc_casco_price",
        "calc_property_price",
        "calc_accident_price",
        "calc_travel_price",
    }
    assert "create_policy" not in result.actions
    assert result.handoff == (sid == "SC06")
    if sid == "SC06":
        assert "14" in result.text and "50 000 USD" in result.text


@pytest.mark.parametrize(
    ("slots", "handoff"),
    [
        (
            dict(
                trip_country="Турция",
                trip_start="2026-10-10",
                trip_end="2026-10-09",
                travelers_count=1,
                traveler_max_age=30,
            ),
            False,
        ),
        (
            dict(
                trip_country="Турция",
                trip_start="2026-10-10",
                trip_end="2026-10-23",
                travelers_count=0,
                traveler_max_age=30,
            ),
            False,
        ),
        (
            dict(
                trip_country="Турция",
                trip_start="2026-10-10",
                trip_end="2026-10-23",
                travelers_count=1,
                traveler_max_age=76,
            ),
            True,
        ),
        (
            dict(
                trip_country="Unknown destination",
                trip_start="2026-10-10",
                trip_end="2026-10-23",
                travelers_count=1,
                traveler_max_age=30,
            ),
            False,
        ),
    ],
)
def test_invalid_or_unknown_quote_never_fabricates_price(replies, slots, handoff):
    result = respond(replies, "SC06", slots)
    assert not result.completed
    assert result.handoff == handoff
    assert set(result.actions) <= {"kb_lookup"}
    assert "Предварительная стоимость" not in result.text


def test_paid_claim_prevents_refund_promise_and_no_cancellation_runs(replies):
    result = respond(
        replies,
        "SC28",
        dict(phone="+77010000001", policy_number="SQ-CASCO-204118", cancel_reason="Продажа"),
    )
    assert "возврат не предусмотрен" in result.text
    assert "cancel_policy" not in result.actions
    assert "knowledge_base.cancellation" in result.source_keys


def test_other_customers_payment_is_not_disclosed(replies):
    result = respond(replies, "SC30", dict(phone="+77010000001", payment_date="2026-06-01"))
    assert "22800" not in result.text
    assert not result.handoff
