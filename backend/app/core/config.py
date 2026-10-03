from pathlib import Path

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
    starter_kit_path: Path = PROJECT_ROOT / "data" / "starter_kit"
    product_catalog_path: Path = PROJECT_ROOT / "data" / "product_promoter" / "catalog.json"
    security_policy_path: Path = PROJECT_ROOT / "data" / "security" / "policy.json"
    event_db_path: Path = PROJECT_ROOT / "data" / "runtime" / "veyra_events.db"
