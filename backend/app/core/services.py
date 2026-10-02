"""Composition root: explicitly register production packs and shared services."""

from dataclasses import dataclass, replace

from pydantic import SecretStr

from app.core.config import Settings
from app.dialog.message import MessageService
from app.dialog.store import InMemoryDialogStore
from app.packs.insurance_manager.agent.router import Router
from app.packs.insurance_manager.pack import INSURANCE_MANIFEST, build_insurance_pack
from app.packs.insurance_manager.scenarios.decision_policy import PolicySettings
from app.packs.product_promoter.agent import ProductAgent
from app.packs.product_promoter.catalog import load_catalog
from app.packs.product_promoter.pack import ProductPromoterPack
from app.packs.registry import ScenarioRegistry
from app.packs.selector import ScenarioSelector
from app.tracing.collector import TraceCollector
from app.triage.service import TriageService


@dataclass(frozen=True)
class RouterSettings:
    """Only router transport receives these values; no general Settings/env access."""

    openai_api_key: SecretStr | None
    openai_router_model: str | None
    router_temperature: float | None
    router_max_output_tokens: int
    router_timeout_seconds: float


@dataclass
class Services:
    registry: ScenarioRegistry
    dialogs: InMemoryDialogStore
    traces: TraceCollector
    messages: MessageService
    triage: TriageService

    @property
    def insurance(self):
        return self.registry.get(INSURANCE_MANIFEST.id)

    @property
    def kit(self):
        return self.insurance.kit

    @property
    def catalog(self):
        return self.insurance.processor.replies.catalog

    @property
    def knowledge(self):
        return self.insurance.knowledge

    @property
    def mock_backend(self):
        return self.insurance.processor.replies.backend

    @property
    def router(self):
        return self.insurance.processor.router

    @property
    def policy(self):
        return self.insurance.policies

    @property
    def engine(self):
        return self.insurance.engine

    @property
    def actions(self):
        return self.insurance.actions

    @property
    def responses(self):
        return self.insurance.responses


def build_services(settings: Settings, *, router_override: Router | None = None) -> Services:
    transport = RouterSettings(
        settings.openai_api_key,
        settings.openai_router_model,
        settings.router_temperature,
        settings.router_max_output_tokens,
        settings.router_timeout_seconds,
    )
    pack = build_insurance_pack(
        settings.starter_kit_path,
        router_settings=transport,
        policy_settings=PolicySettings(
            accept_threshold=settings.router_accept_threshold,
            low_threshold=settings.router_low_threshold,
            handoff_after=settings.router_handoff_after,
            max_unclear_turns=settings.router_max_unclear_turns,
        ),
        router_override=router_override,
        composer_settings=(
            replace(
                transport,
                openai_router_model=settings.openai_response_model or settings.openai_router_model,
            )
            if router_override is None
            else None
        ),
    )
    registry = ScenarioRegistry(default_pack_id=pack.manifest.id)
    registry.register(pack)
    products = load_catalog(settings.product_catalog_path)
    registry.register(ProductPromoterPack(products, ProductAgent(transport, products)))
    dialogs = InMemoryDialogStore()
    traces = TraceCollector()
    messages = MessageService(
        pack.processor.router,
        dialogs,
        traces,
        pack.policies,
        pack.processor.replies,
        registry=registry,
    )
    if settings.openai_api_key and settings.openai_router_model:
        messages.selector = ScenarioSelector(transport)
    return Services(registry, dialogs, traces, messages, TriageService())
