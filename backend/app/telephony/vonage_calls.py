"""Teammate Vonage configuration checks; outbound dialing is not integrated."""

from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import TypeAdapter

from app.core.config import PROJECT_ROOT, Settings
from app.telephony.providers.vonage_messages import CallUuid, PhoneNumber

ANSWER_PATH = "/api/v1/telephony/vonage/answer"
EVENTS_PATH = "/api/v1/telephony/vonage/events"
MEDIA_PATH = "/api/v1/telephony/vonage/media"


class VonageConfigurationError(ValueError):
    pass


def public_origin(value: str | None) -> str:
    parsed = urlsplit(value or "")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise VonageConfigurationError("Set PUBLIC_BASE_URL to an HTTPS origin with no path/query.")
    return (value or "").rstrip("/")


def trial_numbers(settings: Settings) -> tuple[str, str]:
    try:
        adapter = TypeAdapter(PhoneNumber)
        return (
            adapter.validate_python(settings.vonage_test_from_number),
            adapter.validate_python(settings.vonage_test_to_number),
        )
    except ValueError:
        raise VonageConfigurationError(
            "Set VONAGE_TEST_TO_NUMBER to the verified signup number, digits only (no +)."
        ) from None


def application_id(settings: Settings) -> str:
    try:
        return TypeAdapter(CallUuid).validate_python(settings.vonage_application_id)
    except ValueError:
        raise VonageConfigurationError(
            "Set VONAGE_APPLICATION_ID to the application UUID."
        ) from None


def validate_private_key(settings: Settings) -> None:
    path = settings.vonage_private_key_path
    if path is None:
        raise VonageConfigurationError("Set VONAGE_PRIVATE_KEY_PATH to your local application key.")
    path = path if path.is_absolute() else PROJECT_ROOT / path
    try:
        if not path.is_file() or path.stat().st_size > 16384:
            raise ValueError("Invalid key file")
        private_key = path.read_text(encoding="utf-8")
        key = load_pem_private_key(private_key.encode(), password=None)
        if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("Expected RSA private key")
    except (OSError, UnicodeError, ValueError, TypeError):
        raise VonageConfigurationError("Application private key is missing or invalid.") from None
