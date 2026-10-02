"""Optional runtime-only synthetic overlay. Canonical starter-kit data is untouched."""

import re

from app.packs.insurance_manager.data.models import MockBackendDataset


def normalize_phone(value: str) -> str:
    digits = re.sub(r"[\s()+-]", "", value.strip())
    if re.fullmatch(r"\d{10}", digits):
        return "+7" + digits
    if not re.fullmatch(r"[78]\d{10}", digits):
        raise ValueError("DEMO_TEST_PHONE requires a full Kazakhstan phone number")
    return "+7" + digits[1:]


def demo_profile(phone: str) -> dict:
    """Only the supplied phone is personal; all other records are fictional fixtures."""
    return {
        "clients": [
            dict(
                client_id="DEMO-LOCAL",
                full_name="Демо Клиент (вымышленный)",
                phone=normalize_phone(phone),
                iin="000101300000",
                city="Almaty",
                email="demo@example.invalid",
                address="Вымышленный тестовый адрес",
                bm_class="7",
                preferred_language="ru",
            )
        ],
        "policies": [
            dict(
                policy_number="SQ-OGPO-990001",
                client_id="DEMO-LOCAL",
                product="ogpo",
                start_date="2026-01-01",
                end_date="2026-12-31",
                premium=28560,
                details={"vehicle_plate": "999DEM02", "synthetic": True},
            )
        ],
        "payments": [
            dict(
                payment_id="DEMO-PAY-990001",
                client_id="DEMO-LOCAL",
                date="2026-10-01",
                amount=28560,
                product="ogpo",
                status="success",
                policy_number=None,
            )
        ],
        "claims": [
            dict(
                claim_number="CL-990001",
                client_id="DEMO-LOCAL",
                policy_number="SQ-OGPO-990001",
                claim_type="ogpo",
                incident_date="2026-09-25",
                status="under_review",
                next_step=(
                    "All documents received. Decision due by 2026-10-09, "
                    "the client will get an SMS."
                ),
            )
        ],
    }


def with_demo_profile(dataset: MockBackendDataset, phone: str | None) -> MockBackendDataset:
    if not phone:
        return dataset.model_copy(deep=True)
    data = dataset.model_dump(mode="json")
    overlay = demo_profile(phone)
    # Local client takes precedence for this number; every other canonical record remains.
    data["clients"] = [c for c in data["clients"] if c["phone"] != overlay["clients"][0]["phone"]]
    for collection, records in overlay.items():
        data[collection].extend(records)
    return MockBackendDataset.model_validate(data)
