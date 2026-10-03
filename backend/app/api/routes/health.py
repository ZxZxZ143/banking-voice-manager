from typing import Literal

from fastapi import APIRouter, Request

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


class HealthResponse(Contract):
    status: str = "ok"
    service: str = "voice-router"
    mode: str = "foundation"
    starter_kit: DataCounts
    analytics: StorageHealth
    telephony: TelephonyHealth


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
        telephony=TelephonyHealth(**telephony),
        analytics=request.app.state.services.events.health(),
        starter_kit=DataCounts(
            scenarios=len(kit.scenarios.scenarios),
            system_intents=len(kit.scenarios.system_intents),
            actions=len(kit.actions.actions),
            dev_utterances=len(kit.dev_utterances.utterances),
        ),
    )
