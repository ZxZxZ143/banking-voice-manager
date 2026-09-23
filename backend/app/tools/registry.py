"""Explicit action registrations; no business side effects ship in the foundation."""

from copy import deepcopy

from pydantic import JsonValue

from app.data.models import ActionDataset, ActionDefinition
from app.tools.actions import ActionHandler, ToolResult


class ActionRegistry:
    def __init__(self, dataset: ActionDataset) -> None:
        self._definitions = {
            action.name: action.model_copy(deep=True) for action in dataset.actions
        }
        self._handlers: dict[str, ActionHandler] = {}

    def get_all(self) -> list[ActionDefinition]:
        return [action.model_copy(deep=True) for action in self._definitions.values()]

    def get_by_name(self, name: str) -> ActionDefinition | None:
        definition = self._definitions.get(name)
        return definition.model_copy(deep=True) if definition else None

    def register(self, name: str, handler: ActionHandler) -> None:
        definition = self._definitions.get(name)
        if definition is None:
            raise ValueError(f"Unknown action: {name}")
        if definition.irreversible:
            raise ValueError("Irreversible actions require a future confirmation executor")
        if name in self._handlers:
            raise ValueError(f"Action already registered: {name}")
        self._handlers[name] = handler

    async def execute(self, name: str, inputs: dict[str, JsonValue]) -> ToolResult:
        definition = self._definitions.get(name)
        if definition is None:
            return ToolResult.failure("unknown_action", "Action is not in the starter-kit catalog")
        if definition.irreversible:
            return ToolResult.failure(
                "irreversible_action_disabled",
                "Irreversible action execution is not implemented; no action was performed",
            )
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult.failure("not_implemented", "Action handler is not implemented")
        # Alternatives are explicitly represented as pipe-separated names by the kit.
        for requirement in definition.inputs:
            if not any(inputs.get(key) not in (None, "", []) for key in requirement.split("|")):
                return ToolResult.failure("invalid_input", f"Missing required input: {requirement}")
        # Handlers own typed value validation and bounded I/O once implemented.
        # Programming/provider exceptions propagate to the application error boundary.
        result = await handler(deepcopy(inputs))
        return ToolResult.model_validate(result).model_copy(deep=True)
