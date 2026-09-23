from typing import Literal

from app.core.contracts import Contract
from app.dialog.models import DialogState
from app.scenarios.catalog import ScenarioCatalog


class ExecutionRequirements(Contract):
    scenario_id: str
    status: Literal["identify", "collect_slot", "executor_not_implemented"]
    missing_slot: str | None = None
    allowed_actions: list[str]
    requires_confirmation: bool


class ScenarioEngine:
    def __init__(self, catalog: ScenarioCatalog) -> None:
        self.catalog = catalog

    def inspect_requirements(self, scenario_id: str, state: DialogState) -> ExecutionRequirements:
        """Read-only planning from the supplied schema; this does not execute or confirm actions."""
        scenario = self.catalog.get_by_id(scenario_id)
        if scenario is None:
            raise ValueError(f"Unknown business scenario: {scenario_id}")
        status = "executor_not_implemented"
        missing = None
        if scenario.requires_identification and not state.client_id:
            status = "identify"
        else:
            missing = next(
                (
                    name
                    for name in scenario.slots.required
                    if state.slots.get(name) in (None, "", [])
                ),
                None,
            )
            if missing is not None:
                status = "collect_slot"
        return ExecutionRequirements(
            scenario_id=scenario_id,
            status=status,
            missing_slot=missing,
            allowed_actions=scenario.actions,
            requires_confirmation=scenario.requires_confirmation,
        )

    async def execute(self, scenario_id: str, state: DialogState) -> None:
        raise NotImplementedError(
            "Scenario execution and confirmation-bound action dispatch are not implemented"
        )
