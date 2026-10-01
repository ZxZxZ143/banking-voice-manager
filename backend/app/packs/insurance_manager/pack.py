from pathlib import Path

from pydantic import Field

from app.core.contracts import Contract, Slots
from app.packs.contracts import (
    GlobalConversationContext,
    InteractionMode,
    PackTurn,
    ScenarioManifest,
    ScenarioResult,
)
from app.packs.insurance_manager.agent.prompts import build_router_instructions
from app.packs.insurance_manager.agent.router import Router, RouterAgent
from app.packs.insurance_manager.data.loaders import load_starter_kit
from app.packs.insurance_manager.data.repositories import KnowledgeRepository, MockBackendRepository
from app.packs.insurance_manager.processor import InsuranceTurnProcessor
from app.packs.insurance_manager.response.generator import UnconfiguredResponseGenerator
from app.packs.insurance_manager.response.routing import RoutingReplyGenerator
from app.packs.insurance_manager.scenarios.catalog import ScenarioCatalog
from app.packs.insurance_manager.scenarios.decision_policy import DecisionPolicy, PolicySettings
from app.packs.insurance_manager.scenarios.engine import ScenarioEngine
from app.packs.insurance_manager.state import InsuranceScenarioContext
from app.packs.insurance_manager.tools.registry import ActionRegistry

INSURANCE_MANIFEST = ScenarioManifest(
    id="insurance_manager",
    name="Insurance Manager",
    interaction_mode=InteractionMode.CONSULTATIVE,
    supported_languages=("ru", "kk", "mixed"),
    output_schema="InsuranceResult",
)


class InsuranceResult(ScenarioResult):
    scenario_id: str | None
    collected_data: Slots = Field(default_factory=dict)
    actions: list[str] = Field(default_factory=list)
    source_keys: list[str] = Field(default_factory=list)


class InsuranceManagerPack:
    manifest = INSURANCE_MANIFEST
    state_schema = InsuranceScenarioContext
    output_schema = InsuranceResult
    completion_rules = (
        "A read-only flow completes and resumes pending insurance work. "
        "Only operator handoff or goodbye closes the conversation. Business writes are disabled."
    )

    def __init__(self, processor: InsuranceTurnProcessor) -> None:
        self.processor = processor
        self.kit = None
        self.engine = ScenarioEngine(processor.replies.catalog)
        self.actions = None
        self.responses = UnconfiguredResponseGenerator()

    @property
    def prompt(self) -> str:
        return build_router_instructions(
            self.processor.replies.catalog, self.processor.replies.slot_dataset
        )

    @property
    def knowledge(self) -> object:
        return self.processor.replies.knowledge

    @property
    def tools(self) -> object:
        return self.actions

    @property
    def policies(self) -> DecisionPolicy:
        return self.processor.policy

    def new_context(self) -> InsuranceScenarioContext:
        return InsuranceScenarioContext()

    async def handle_turn(
        self, text: str, global_context: GlobalConversationContext, context: Contract
    ) -> PackTurn:
        if type(context) is not InsuranceScenarioContext:
            raise ValueError("Insurance Manager requires its own scenario context")
        previous = context.to_dialog(global_context)
        (
            state,
            decision,
            trace,
            reply,
            completed_flow,
            collected_data,
        ) = await self.processor.process(previous, text)
        result = InsuranceResult(
            scenario_id=(
                decision.scenarios[0].scenario_id
                if state.conversation_status in ("handoff", "ended")
                else completed_flow or state.active_scenario or decision.scenarios[0].scenario_id
            ),
            status=state.conversation_status,
            collected_data=collected_data,
            actions=reply.actions,
            source_keys=reply.source_keys,
            completed=reply.completed,
            handoff=state.conversation_status == "handoff",
        )
        return PackTurn(
            context=InsuranceScenarioContext.from_dialog(state),
            language=state.language,
            response_text=state.history[-1].text,
            routing=decision,
            public_state=state,
            trace=trace,
            result=result,
        )


def build_insurance_pack(
    dataset_path: Path,
    *,
    router_settings,
    policy_settings: PolicySettings,
    router_override: Router | None = None,
) -> InsuranceManagerPack:
    kit = load_starter_kit(dataset_path)
    catalog = ScenarioCatalog(kit.scenarios)
    knowledge = KnowledgeRepository(kit.knowledge)
    backend = MockBackendRepository(kit.mock_backend)
    router = (
        router_override
        if router_override is not None
        else RouterAgent(catalog, settings=router_settings, slots=kit.slots)
    )
    pack = InsuranceManagerPack(
        InsuranceTurnProcessor(
            router,
            DecisionPolicy(catalog, policy_settings),
            RoutingReplyGenerator(catalog, kit.slots, knowledge, backend),
        )
    )
    pack.kit = kit
    pack.actions = ActionRegistry(kit.actions)
    return pack
