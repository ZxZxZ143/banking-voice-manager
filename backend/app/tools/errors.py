"""Shared business and foundation error payload, without input/credential echoes."""

from pydantic import BaseModel, ConfigDict, Field


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Business codes come from actions.json; foundation can report unimplemented work.
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
