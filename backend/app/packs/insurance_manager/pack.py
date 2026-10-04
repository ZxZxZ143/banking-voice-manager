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
from app.speech.structured.context import context_for_capture
from app.speech.structured.recognition import resolve_recognition
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
    def after_security_guidance(context, public, language):
        """Retain business work; mark only the pack's conversational next step."""
        from app.packs.insurance_manager.conversation_flow import (
            enter_wrap_up,
            more_questions,
            remember_relationship,
            unfinished_request,
        )

        context = context.model_copy(deep=True)
        public = public.model_copy(deep=True)
        context.conversation = context.conversation or ConversationState()
        context.response_language = language
        if unfinished_request(context):
            context.conversation.resume_after_risk = True
            followup = ""
        else:
            remember_relationship(context.conversation, "not_applicable")
            enter_wrap_up(context.conversation, language)
            followup = more_questions(language)
        public.conversation = context.conversation.model_copy(deep=True)
        if public.conversation.structured_capture:
            public.conversation.last_question = "[проверка произнесённого номера]"
            public.conversation.structured_capture = None
        public.response_language = language
        return context, public, followup

    @staticmethod
    def redact_trace(trace, slots=None):
        trace.transcript = redact_text(trace.transcript, slots)
        if trace.recognition and trace.recognition.expected_kind not in {"none", "region_code"}:
            trace.transcript = "[произнесённый номер скрыт]"
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
        speech = global_context.speech_answer
        if speech is None and global_context.channel == "voice":
            stt_context = context_for_capture(
                previous.conversation.expected_slot if previous.conversation else None,
                previous.response_language,
                previous.conversation.structured_capture if previous.conversation else None,
                previous.slots.get("contact_field"),
            )
            if stt_context.expected_kind != "none":
                speech = await resolve_recognition(text, b"", stt_context)
        (
            state,
            decision,
            trace,
            reply,
            completed_flow,
            collected_data,
        ) = await self.processor.process(
            previous,
            text,
            speech=speech,
            channel=global_context.channel,
            manual_input_available=global_context.manual_input_available,
        )
        capture = state.conversation.structured_capture if state.conversation else None
        if capture and (
            capture.slot != state.conversation.expected_slot
            or capture.scenario != state.active_scenario
            or state.conversation_status in {"ended", "handoff"}
            or state.conversation.phase == "wrap_up"
            or state.conversation.last_question != capture.prompt
        ):
            state.conversation.structured_capture = None
        selected = decision.scenarios[0].scenario_id if decision.scenarios else None
        result = InsuranceResult(
            scenario_id=(
                selected
                if state.conversation_status in ("handoff", "ended")
                else completed_flow or state.active_scenario or selected
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
        if public_state.conversation and public_state.conversation.structured_capture:
            public_state.conversation.last_question = "[проверка произнесённого номера]"
            public_state.conversation.structured_capture = None
        public_state.identification.failed_attempts = []
        public_state.identification.provided_values = {}
        for memory in public_state.scenario_identification.values():
            memory.failed_attempts = []
            memory.provided_values = {}
        public_state.slots = safe_slots(state.slots)
        public_state.scenario_slots = {
            key: safe_slots(value) for key, value in state.scenario_slots.items()
        }
        for item in public_state.history:
            item.text = redact_text(item.text, state.slots)
        if speech and speech.metadata.expected_kind not in {"none", "region_code"}:
            for item in reversed(public_state.history):
                if item.role == "user":
                    item.text = "[произнесённый номер скрыт]"
                    break
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
            response_text=(
                reply.text
                if trace.conversation_act == "verify_identifier"
                or (
                    trace.recognition
                    and trace.recognition.outcome in {"manual_fallback", "exhausted"}
                )
                else state.history[-1].text
            ),
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
