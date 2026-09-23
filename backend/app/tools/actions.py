"""Tool execution contract; action handlers can be added independently of routing."""

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from app.tools.errors import ToolError


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    data: dict[str, JsonValue] | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def consistent_result(self) -> "ToolResult":
        if self.success and (self.error is not None or self.data is None):
            raise ValueError("Successful tools require data and cannot contain an error")
        if not self.success and (self.error is None or self.data is not None):
            raise ValueError("Failed tools require an error and cannot contain success data")
        return self

    @classmethod
    def failure(cls, code: str, message: str) -> "ToolResult":
        return cls(success=False, error=ToolError(code=code, message=message))

    def to_payload(self) -> dict[str, JsonValue]:
        """Preserve the starter-kit failure shape: {error: {code, message}}."""
        if self.error:
            return {"error": self.error.model_dump()}
        return self.model_copy(deep=True).data or {}


ActionHandler = Callable[[dict[str, JsonValue]], Awaitable[ToolResult]]
