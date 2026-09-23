from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator

from app.core.contracts import Contract, ErrorDetail, ErrorResponse

router = APIRouter(prefix="/api/v1/turns")


class TextTurnRequest(Contract):
    session_id: UUID
    text: str = Field(min_length=1, max_length=10000)

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


@router.post("/text", status_code=501, response_model=ErrorResponse)
async def text_turn(payload: TextTurnRequest) -> JSONResponse:
    error = ErrorResponse(
        error=ErrorDetail(
            code="not_implemented",
            message="Text-turn orchestration is not implemented. No actions were run.",
        )
    )
    return JSONResponse(status_code=501, content=error.model_dump())
