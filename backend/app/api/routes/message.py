from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator

from app.agent.errors import RouterConfigurationError, RouterError
from app.conversation.service import ScenarioOpeningError, SessionClosedError
from app.conversation.store import SessionCapacityError
from app.conversation.wire import PlatformMessageResponse
from app.core.contracts import Contract
from app.packs.insurance_manager.wire import InsuranceMessageResponse
from app.packs.product_promoter.wire import ProductMessageResponse
from app.packs.registry import UnknownScenarioPackError

router = APIRouter(prefix="/api", tags=["message"])


class MessageRequest(Contract):
    session_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=10000)
    scenario_mode: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("session_id", "text")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank")
        return value


@router.post(
    "/message",
    response_model=InsuranceMessageResponse | ProductMessageResponse | PlatformMessageResponse,
)
async def message(payload: MessageRequest, request: Request):
    return await _process(request, payload.session_id, payload.text, payload.scenario_mode)


class ScenarioStartRequest(Contract):
    session_id: str = Field(min_length=1, max_length=128)
    scenario_mode: str = Field(min_length=1, max_length=64)

    @field_validator("session_id", "scenario_mode")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank")
        return value


@router.post(
    "/conversation/start", response_model=InsuranceMessageResponse | ProductMessageResponse
)
async def start_scenario(payload: ScenarioStartRequest, request: Request):
    return await _process(
        request, payload.session_id, "", payload.scenario_mode, start_scenario=True
    )


async def _process(request, session_id, text, scenario_mode, *, start_scenario=False):
    try:
        return await request.app.state.services.messages.process(
            session_id, text, scenario_mode, start_scenario=start_scenario
        )
    except ScenarioOpeningError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "scenario_has_no_opener",
                    "message": str(exc),
                }
            },
        )
    except UnknownScenarioPackError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "unknown_scenario_pack", "message": str(exc)}},
        )
    except RouterError as exc:
        status = 503 if isinstance(exc, RouterConfigurationError) else 502
        if exc.code == "router_timeout":
            status = 504
        return JSONResponse(
            status_code=status, content={"error": {"code": exc.code, "message": exc.message}}
        )
    except SessionClosedError as exc:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "session_closed", "message": str(exc)}},
        )
    except SessionCapacityError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "session_capacity", "message": str(exc)}},
        )
