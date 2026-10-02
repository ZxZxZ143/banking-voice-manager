"""Print only the configured synthetic local profile, never credentials or other clients."""

import json

from app.core.config import Settings
from app.packs.insurance_manager.data.demo_profile import demo_profile


def main():
    phone = Settings().demo_test_phone
    if not phone:
        raise SystemExit("Set DEMO_TEST_PHONE in the ignored .env first.")
    data = demo_profile(phone.get_secret_value())
    data["manual_tests"] = {
        "identity": "Phone in +7 or domestic 8 form; or the synthetic IIN",
        "policy": "Existing policy status / add driver / renew / cancellation",
        "payment": "Payment on 2026-10-01, amount 28560, policy not issued",
        "claim": "Claim status or dispute; never a real registered insurance claim",
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
