from fastapi import APIRouter, Request

from app.core.contracts import Contract

router = APIRouter()


class DataCounts(Contract):
    scenarios: int
    system_intents: int
    actions: int
    dev_utterances: int


class HealthResponse(Contract):
    status: str = "ok"
    service: str = "voice-router"
    mode: str = "foundation"
    starter_kit: DataCounts


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    kit = request.app.state.services.kit
    return HealthResponse(
        starter_kit=DataCounts(
            scenarios=len(kit.scenarios.scenarios),
            system_intents=len(kit.scenarios.system_intents),
            actions=len(kit.actions.actions),
            dev_utterances=len(kit.dev_utterances.utterances),
        )
    )
