from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    openai_api_key: SecretStr | None = None
    openai_router_model: str | None = None
    openai_response_model: str | None = None
    demo_test_phone: SecretStr | None = None
    router_timeout_seconds: float = Field(default=45.0, gt=0, le=120)
    risk_timeout_seconds: float = Field(default=8.0, gt=0, le=15)
    router_max_output_tokens: int = Field(default=2500, ge=256, le=10000)
    router_temperature: float | None = Field(default=None, ge=0, le=2)
    router_accept_threshold: float = Field(default=0.75, ge=0, le=1)
    router_low_threshold: float = Field(default=0.45, ge=0, le=1)
    router_handoff_after: int = Field(default=2, ge=1, le=10)
    router_max_unclear_turns: int = Field(default=3, ge=1, le=10)
    backend_host: str = "127.0.0.1"
    backend_port: int = Field(default=8000, ge=1, le=65535)
    frontend_origin: str = "http://localhost:5173"
    enable_dev_stand: bool = False
    twilio_enabled: bool = False
    twilio_account_sid: str | None = Field(default=None, pattern=r"^AC[0-9a-fA-F]{32}$")
    twilio_auth_token: SecretStr | None = None
    twilio_phone_number: str | None = None
    public_base_url: str | None = None
    tts_provider: Literal["auto", "openai", "browser"] = "auto"
    backend_tts_model: str | None = "gpt-4o-mini-tts"
    backend_tts_voice: str | None = "cedar"
    backend_tts_instructions_ru: str = Field(
        default=(
            "Говорите по-русски, как спокойный профессиональный консультант. "
            "Естественный разговорный темп, короткие паузы, чёткие числа и проценты. "
            "Без дикторской подачи и преувеличенных эмоций."
        ),
        max_length=1000,
    )
    backend_tts_instructions_kk: str = Field(
        default=(
            "Қазақ тілінде сабырлы кәсіби кеңесші ретінде сөйлеңіз. "
            "Табиғи қарқын, қысқа үзілістер, сандар мен пайыздарды анық айтыңыз. "
            "Дикторлық мәнер мен әсіре эмоциясыз."
        ),
        max_length=1000,
    )
    phone_endpoint_silence_ms: int = Field(default=1200, ge=800, le=5000)
    vonage_enabled: bool = False
    vonage_application_id: str | None = None
    vonage_private_key_path: Path | None = Field(default=None, repr=False)
    vonage_api_key: str | None = None
    vonage_signature_secret: SecretStr | None = None
    vonage_test_from_number: str | None = Field(default=None, repr=False)
    vonage_test_to_number: str | None = Field(default=None, repr=False)
    starter_kit_path: Path = PROJECT_ROOT / "data" / "starter_kit"
    product_catalog_path: Path = PROJECT_ROOT / "data" / "product_promoter" / "catalog.json"
    security_policy_path: Path = PROJECT_ROOT / "data" / "security" / "policy.json"
    event_db_path: Path = PROJECT_ROOT / "data" / "runtime" / "veyra_events.db"
    analytics_window_seconds: int = Field(default=3600, ge=60, le=86400)
    analytics_baseline_windows: int = Field(default=6, ge=2, le=48)
    analytics_min_volume: int = Field(default=5, ge=2, le=10000)
    analytics_anomaly_multiplier: float = Field(default=3, gt=1, le=100)
