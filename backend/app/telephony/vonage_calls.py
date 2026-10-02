"""Explicit one-call trial trigger using the official Voice SDK and application JWT."""

import logging
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import TypeAdapter
from vonage_http_client import HttpClient, HttpClientOptions
from vonage_http_client.auth import Auth
from vonage_voice import CreateCallRequest, Phone, ToPhone, Voice

from app.core.config import PROJECT_ROOT, Settings
from app.telephony.providers.vonage_messages import CallUuid, PhoneNumber

ANSWER_PATH = "/api/v1/telephony/vonage/answer"
EVENTS_PATH = "/api/v1/telephony/vonage/events"
MEDIA_PATH = "/api/v1/telephony/vonage/media"
logger = logging.getLogger(__name__)


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


def create_trial_call(settings: Settings, *, voice_override=None) -> str:
    """One destination only; no CLI destination override, loops, retries, or public dial API."""
    if not settings.vonage_enabled:
        raise VonageConfigurationError("Set VONAGE_ENABLED=true before initiating a demo call.")
    app_id = application_id(settings)
    origin = public_origin(settings.public_base_url)
    from_number, to_number = trial_numbers(settings)
    if not settings.vonage_api_key or not settings.vonage_signature_secret:
        raise VonageConfigurationError(
            "Set VONAGE_API_KEY and VONAGE_SIGNATURE_SECRET for authenticated callbacks."
        )
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
    logging.getLogger("vonage_http_client").setLevel(logging.WARNING)
    # API key/secret are NOT passed to Voice auth: application JWT only.
    voice = voice_override or Voice(
        HttpClient(
            Auth(application_id=app_id, private_key=private_key),
            http_client_options=HttpClientOptions(timeout=10, max_retries=0, pool_maxsize=1),
        )
    )
    request = CreateCallRequest(
        to=[ToPhone(number=to_number, type="phone")],
        from_=Phone(number=from_number, type="phone"),
        answer_url=[origin + ANSWER_PATH],
        answer_method="POST",
        event_url=[origin + EVENTS_PATH],
        event_method="POST",
        ringing_timer=45,
        length_timer=600,
    )
    # The SDK uses this serialization for POST /v1/calls. Keep its typed model;
    # reject an omitted/incorrect CLI before submitting, rather than sending raw JSON.
    payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
    if payload.get("from") != {"type": "phone", "number": from_number} or payload.get("to") != [
        {"type": "phone", "number": to_number}
    ]:
        raise VonageConfigurationError(
            "Vonage SDK did not serialize the configured phone endpoints; no call submitted."
        )
    # Only flags and validated endpoint types: no numbers, payloads, auth or key material.
    logger.info(
        "Vonage outbound endpoints validated: from_configured=%s to_configured=%s "
        "from_type=%s to_type=%s trial_cli=%s",
        bool(from_number),
        bool(to_number),
        payload["from"]["type"],
        payload["to"][0]["type"],
        from_number == "123456789",
    )
    # No automatic retry: an ambiguous timeout may already have placed the call.
    try:
        response = voice.create_call(request)
        return TypeAdapter(CallUuid).validate_python(response.uuid)
    except Exception:
        raise RuntimeError(
            "Vonage call request failed or its outcome is unknown; check Dashboard before retrying."
        ) from None
