from app.packs.contracts import ConversationContext, ScenarioContextEntry
from app.packs.registry import ScenarioRegistry


class ScenarioLifecycle:
    """Only selects trusted packs and manages isolated contexts; performs no routing."""

    def __init__(self, registry: ScenarioRegistry) -> None:
        self.registry = registry

    def suspend(self, conversation: ConversationContext) -> None:
        active = conversation.active_scenario_pack
        if active is not None:
            entry = conversation.scenario_contexts[active]
            if entry.lifecycle != "completed":
                entry.lifecycle = "suspended"
            conversation.active_scenario_pack = None

    def activate(
        self, conversation: ConversationContext, pack_id: str, *, preserve_completed: bool = False
    ) -> ScenarioContextEntry:
        pack = self.registry.get(pack_id)  # Reject unknown IDs before changing any context.
        entry = conversation.scenario_contexts.get(pack_id)
        if entry is None or (entry.lifecycle == "completed" and not preserve_completed):
            entry = ScenarioContextEntry(state=pack.new_context(), lifecycle="active")
        if type(entry.state) is not pack.state_schema:
            raise ValueError("Scenario context does not match the registered pack schema")
        if conversation.active_scenario_pack != pack_id:
            self.suspend(conversation)
        conversation.scenario_contexts[pack_id] = entry
        if entry.lifecycle == "suspended":
            entry.lifecycle = "resumed"
        elif entry.lifecycle == "inactive":
            entry.lifecycle = "active"
        conversation.active_scenario_pack = pack_id
        return entry

    def complete(self, conversation: ConversationContext) -> None:
        active = conversation.active_scenario_pack
        if active is None:
            raise ValueError("No active scenario pack")
        conversation.scenario_contexts[active].lifecycle = "completed"
