from dataclasses import dataclass

from app.agent.router import Router, RouterAgent
from app.core.config import Settings
from app.data.loaders import StarterKit, load_starter_kit
from app.data.repositories import KnowledgeRepository, MockBackendRepository
from app.dialog.message import MessageService
from app.dialog.store import InMemoryDialogStore
from app.response.generator import UnconfiguredResponseGenerator
from app.response.routing import RoutingReplyGenerator
from app.scenarios.catalog import ScenarioCatalog
from app.scenarios.decision_policy import DecisionPolicy, PolicySettings
from app.scenarios.engine import ScenarioEngine
from app.tools.registry import ActionRegistry
from app.tracing.collector import TraceCollector
from app.triage.service import TriageService


@dataclass
class Services:
    kit: StarterKit
    catalog: ScenarioCatalog
    knowledge: KnowledgeRepository
    mock_backend: MockBackendRepository
    dialogs: InMemoryDialogStore
    traces: TraceCollector
    triage: TriageService
    router: Router
    policy: DecisionPolicy
    engine: ScenarioEngine
    actions: ActionRegistry
    responses: UnconfiguredResponseGenerator
    messages: MessageService


def build_services(settings: Settings, *, router_override: Router | None = None) -> Services:
    kit = load_starter_kit(settings.starter_kit_path)
    catalog = ScenarioCatalog(kit.scenarios)
    router = (
        router_override
        if router_override is not None
        else RouterAgent(catalog, settings=settings, slots=kit.slots)
    )
    dialogs = InMemoryDialogStore()
    traces = TraceCollector()
    knowledge = KnowledgeRepository(kit.knowledge)
    mock_backend = MockBackendRepository(kit.mock_backend)
    policy = DecisionPolicy(
        catalog,
        PolicySettings(
            accept_threshold=settings.router_accept_threshold,
            low_threshold=settings.router_low_threshold,
            handoff_after=settings.router_handoff_after,
            max_unclear_turns=settings.router_max_unclear_turns,
        ),
    )
    return Services(
        kit=kit,
        catalog=catalog,
        knowledge=knowledge,
        mock_backend=mock_backend,
        dialogs=dialogs,
        traces=traces,
        triage=TriageService(),
        router=router,
        policy=policy,
        engine=ScenarioEngine(catalog),
        actions=ActionRegistry(kit.actions),
        responses=UnconfiguredResponseGenerator(),
        messages=MessageService(
            router,
            dialogs,
            traces,
            policy,
            RoutingReplyGenerator(catalog, kit.slots, knowledge, mock_backend),
        ),
    )
