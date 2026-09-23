from dataclasses import dataclass

from app.agent.router import RouterAgent
from app.core.config import Settings
from app.data.loaders import StarterKit, load_starter_kit
from app.data.repositories import KnowledgeRepository, MockBackendRepository
from app.dialog.store import InMemoryDialogStore
from app.response.generator import UnconfiguredResponseGenerator
from app.scenarios.catalog import ScenarioCatalog
from app.scenarios.decision_policy import DecisionPolicy
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
    router: RouterAgent
    policy: DecisionPolicy
    engine: ScenarioEngine
    actions: ActionRegistry
    responses: UnconfiguredResponseGenerator


def build_services(settings: Settings) -> Services:
    kit = load_starter_kit(settings.starter_kit_path)
    catalog = ScenarioCatalog(kit.scenarios)
    return Services(
        kit=kit,
        catalog=catalog,
        knowledge=KnowledgeRepository(kit.knowledge),
        mock_backend=MockBackendRepository(kit.mock_backend),
        dialogs=InMemoryDialogStore(),
        traces=TraceCollector(),
        triage=TriageService(),
        router=RouterAgent(catalog),
        policy=DecisionPolicy(catalog),
        engine=ScenarioEngine(catalog),
        actions=ActionRegistry(kit.actions),
        responses=UnconfiguredResponseGenerator(),
    )
