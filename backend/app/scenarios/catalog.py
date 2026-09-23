"""Complete, compact routing catalog built only from the authoritative dataset."""

from pydantic import JsonValue

from app.data.models import Scenario, ScenarioDataset, SystemIntent


class ScenarioCatalog:
    def __init__(self, dataset: ScenarioDataset) -> None:
        self._dataset = dataset.model_copy(deep=True)
        self._by_id = {scenario.scenario_id: scenario for scenario in self._dataset.scenarios}
        self._system_by_id = {intent.id: intent for intent in self._dataset.system_intents}

    def get_all(self) -> list[Scenario]:
        return [scenario.model_copy(deep=True) for scenario in self._dataset.scenarios]

    def get_by_id(self, scenario_id: str) -> Scenario | None:
        scenario = self._by_id.get(scenario_id)
        return scenario.model_copy(deep=True) if scenario else None

    def get_system_intent(self, intent_id: str) -> SystemIntent | None:
        intent = self._system_by_id.get(intent_id)
        return intent.model_copy(deep=True) if intent else None

    def get_compact_router_catalog(self) -> dict[str, JsonValue]:
        """All scenarios and system intents; omit execution/response templates."""
        return {
            "reference_date": self._dataset.meta.as_of_date.isoformat(),
            "scenarios": [
                {
                    "scenario_id": scenario.scenario_id,
                    "name": scenario.name,
                    "description": scenario.description,
                    "not_this_if": [rule.model_dump() for rule in scenario.not_this_if],
                    "priority": scenario.priority,
                    "slots": scenario.slots.model_dump(),
                    "examples": {
                        "ru": scenario.examples.ru[:2],
                        "kk": scenario.examples.kk[:2],
                    },
                }
                for scenario in self._dataset.scenarios
            ],
            "system_intents": [
                {"id": intent.id, "description": intent.description, "behavior": intent.behavior}
                for intent in self._dataset.system_intents
            ],
        }
