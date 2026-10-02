"""Explicit ONE outbound trial call to the configured verified signup destination."""

import sys

from app.core.config import Settings
from app.core.logging import configure_logging
from app.telephony.vonage_calls import VonageConfigurationError, create_trial_call


def main() -> int:
    configure_logging()
    try:
        settings = Settings()
        call_uuid = create_trial_call(settings)
        print(f"Vonage accepted one call; call UUID: {call_uuid}")
        return 0
    except VonageConfigurationError as error:
        print(str(error), file=sys.stderr)  # Static safe configuration errors only.
    except Exception:  # noqa: BLE001 - never emit credential-bearing validation/SDK exceptions
        print(
            "Call request failed or outcome unknown. Check Vonage Dashboard before retrying.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
