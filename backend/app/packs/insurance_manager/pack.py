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
from app.packs.insurance_manager.agent.schemas import RouterDecision
from app.packs.insurance_manager.composer import ConversationComposer
from app.packs.insurance_manager.data.demo_profile import with_demo_profile
from app.packs.insurance_manager.data.loaders import load_starter_kit
from app.packs.insurance_manager.data.repositories import KnowledgeRepository, MockBackendRepository
from app.packs.insurance_manager.history import append_turn
from app.packs.insurance_manager.privacy import redact_text, safe_slots
from app.packs.insurance_manager.processor import InsuranceTurnProcessor
from app.packs.insurance_manager.response.generator import UnconfiguredResponseGenerator
from app.packs.insurance_manager.response.routing import RoutingReplyGenerator
from app.packs.insurance_manager.scenarios.catalog import ScenarioCatalog
from app.packs.insurance_manager.scenarios.decision_policy import DecisionPolicy, PolicySettings
from app.packs.insurance_manager.scenarios.engine import ScenarioEngine
from app.packs.insurance_manager.state import (
    ConversationState,
    DialogTurn,
    InsuranceScenarioContext,
)
from app.packs.insurance_manager.tools.capabilities import ActionCapabilities, ManagerSummary
from app.packs.insurance_manager.tools.registry import ActionRegistry
from app.tracing.models import TraceRecord

INSURANCE_MANIFEST = ScenarioManifest(
    id="insurance_manager",
    name="Insurance Manager",
    interaction_mode=InteractionMode.CONSULTATIVE,
    supported_languages=("ru", "kk", "mixed"),
    output_schema="InsuranceResult",
    public_description="Insurance policies, quotes, coverage, claims, policy documents, "
    "insurance payments and insurance service support. Excludes bank deposits/cards.",
)


class InsuranceResult(ScenarioResult):
    scenario_id: str | None
    collected_data: Slots = Field(default_factory=dict)
    actions: list[str] = Field(default_factory=list)
    source_keys: list[str] = Field(default_factory=list)
    manager_summary: ManagerSummary | None = Field(default=None, exclude_if=lambda v: v is None)


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
        return InsuranceScenarioContext(
            conversation=ConversationState() if self.processor.composer is not None else None
        )

    async def open_turn(self, global_context, context):
        if type(context) is not InsuranceScenarioContext:
            raise ValueError("Insurance Manager requires its own scenario context")
        language = (
            global_context.language
            if global_context.language in {"ru", "kk"}
            else context.response_language
        )
        question = (
            "Расскажите, пожалуйста, что случилось или чем могу помочь?"
            if language == "ru"
            else "Не болғанын айтып беріңізші, қалай көмектесе аламын?"
        )
        response = (
            "Здравствуйте! Я виртуальный помощник Saqta Insurance. "
            "Помогу разобраться со страховкой. "
            if language == "ru"
            else "Сәлеметсіз бе! Мен Saqta Insurance виртуалды көмекшісімін. "
            "Сақтандыру бойынша көмектесемін. "
        ) + question
        state = context.to_dialog(global_context)
        state.response_language = language
        state.conversation = ConversationState(
            last_assistant_act="greet",
            last_question=question,
            expected_answer_type="problem_description",
        )
        state = append_turn(state, DialogTurn(role="assistant", text=response))
        state.turn_number = global_context.turn_number + 1
        return PackTurn(
            context=InsuranceScenarioContext.from_dialog(state),
            language=language,
            response_text=response,
            routing=RouterDecision(
                language=language,
                response_language=language,
                scenarios=[
                    dict(
                        scenario_id="SYS_UNCLEAR",
                        confidence=1,
                        reason="Assistant opening, no routing",
                    )
                ],
            ),
            public_state=state,
            trace=TraceRecord(
                event_type="scenario.opened",
                turn=state.turn_number,
                transcript="",
                language=language,
                reason="Assistant initiated insurance consultation",
                conversation_act="greet",
                expected_answer_type="problem_description",
                conversation_phase="discover",
                repair_attempts=0,
            ),
            result=InsuranceResult(
                scenario_id=None, status="active", completed=False, handoff=False
            ),
        )

    @staticmethod
    def redact_trace(trace, slots=None):
        trace.transcript = redact_text(trace.transcript, slots)
        trace.reason = redact_text(trace.reason, slots)
        trace.slots = safe_slots(trace.slots)
        trace.source_keys = [redact_text(key, slots) for key in trace.source_keys]
        for selection in trace.scenarios:
            selection.reason = redact_text(selection.reason, slots)

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
            manager_summary=reply.manager_summary,
            completed=reply.completed,
            handoff=state.conversation_status == "handoff",
        )
        public_state = state.model_copy(deep=True)
        public_state.slots = safe_slots(state.slots)
        public_state.scenario_slots = {
            key: safe_slots(value) for key, value in state.scenario_slots.items()
        }
        for item in public_state.history:
            item.text = redact_text(item.text, state.slots)
        public_decision = decision.model_copy(deep=True)
        public_decision.slots = safe_slots(decision.slots)
        for item in public_decision.scenarios:
            item.reason = redact_text(item.reason, state.slots)
        for item in public_decision.segments:
            item.text = redact_text(item.text, state.slots)
            item.reason = redact_text(item.reason, state.slots)
        self.redact_trace(trace, state.slots)
        return PackTurn(
            context=InsuranceScenarioContext.from_dialog(state),
            language=state.language,
            response_text=state.history[-1].text,
            routing=public_decision,
            public_state=public_state,
            trace=trace,
            result=result,
            out_of_domain=any(s.scenario_id == "SYS_OUT_OF_SCOPE" for s in decision.scenarios),
        )


def build_insurance_pack(
    dataset_path: Path,
    *,
    router_settings,
    policy_settings: PolicySettings,
    router_override: Router | None = None,
    composer_settings=None,
    demo_test_phone=None,
) -> InsuranceManagerPack:
    kit = load_starter_kit(dataset_path)
    catalog = ScenarioCatalog(kit.scenarios)
    knowledge = KnowledgeRepository(kit.knowledge)
    backend = MockBackendRepository(with_demo_profile(kit.mock_backend, demo_test_phone))
    router = (
        router_override
        if router_override is not None
        else RouterAgent(
            catalog,
            settings=router_settings,
            slots=kit.slots,
            local_phone=backend.get_all("clients")[-1]["phone"] if demo_test_phone else None,
        )
    )
    pack = InsuranceManagerPack(
        InsuranceTurnProcessor(
            router,
            DecisionPolicy(catalog, policy_settings),
            RoutingReplyGenerator(
                catalog, kit.slots, knowledge, backend, ActionCapabilities(kit.actions)
            ),
            ConversationComposer(composer_settings) if composer_settings is not None else None,
        )
    )
    pack.kit = kit
    pack.actions = ActionRegistry(kit.actions)
    return pack
