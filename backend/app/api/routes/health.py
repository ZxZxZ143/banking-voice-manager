from typing import Literal

from fastapi import APIRouter, Request

from app.analytics.demo import REFRESH_SECONDS
from app.analytics.models import StorageHealth
from app.core.contracts import Contract

router = APIRouter()


class DataCounts(Contract):
    scenarios: int
    system_intents: int
    actions: int
    dev_utterances: int


class TelephonyHealth(Contract):
    twilio: Literal["disabled", "unavailable", "ready"]
    vonage: Literal["disabled", "unavailable", "ready"]


class AnalyticsDemoHealth(Contract):
    enabled: bool
    version: str | None = None
    time_policy: Literal["rolling_5m"] = "rolling_5m"
    refresh_seconds: int = REFRESH_SECONDS


class HealthResponse(Contract):
    status: str = "ok"
    service: str = "voice-router"
    mode: str = "foundation"
    starter_kit: DataCounts
    analytics: StorageHealth
    telephony: TelephonyHealth
    analytics_demo: AnalyticsDemoHealth


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    kit = request.app.state.services.kit
    settings = request.app.state.settings
    telephony = {
        provider: (
            "ready"
            if getattr(request.app.state, f"{provider}_gateway", None)
            else "unavailable"
            if getattr(settings, f"{provider}_enabled")
            else "disabled"
        )
        for provider in ("twilio", "vonage")
    }
    return HealthResponse(
        analytics_demo=AnalyticsDemoHealth(
            enabled=request.app.state.services.demo_data is not None,
            version=(
                request.app.state.services.demo_data.dataset.fixture.version
                if request.app.state.services.demo_data
                else None
            ),
        ),
        telephony=TelephonyHealth(**telephony),
        analytics=request.app.state.services.events.health(),
        starter_kit=DataCounts(
            scenarios=len(kit.scenarios.scenarios),
            system_intents=len(kit.scenarios.system_intents),
            actions=len(kit.actions.actions),
            dev_utterances=len(kit.dev_utterances.utterances),
        ),
    )
