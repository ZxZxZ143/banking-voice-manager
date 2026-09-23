from typing import Protocol

from pydantic import Field, JsonValue

from app.core.contracts import Contract, Language, Slots
from app.dialog.models import DialogState


class ResponseInput(Contract):
    language: Language
    scenario_id: str
    dialog_state: DialogState
    slots: Slots
    tool_results: list[dict[str, JsonValue]]
    knowledge: dict[str, JsonValue]


class GeneratedResponse(Contract):
    text: str = Field(min_length=1)
    language: Language


class ResponseGenerator(Protocol):
    async def generate(self, context: ResponseInput) -> GeneratedResponse: ...


class UnconfiguredResponseGenerator:
    async def generate(self, context: ResponseInput) -> GeneratedResponse:
        raise NotImplementedError("Grounded response generation is not implemented")
