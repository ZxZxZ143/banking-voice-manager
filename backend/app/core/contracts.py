from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

Language = Literal["ru", "kk", "mixed"]
Slots = dict[str, JsonValue]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ErrorDetail(Contract):
    code: str
    message: str


class ErrorResponse(Contract):
    error: ErrorDetail
