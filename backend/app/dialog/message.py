"""Compatibility constructor and insurance debug views over shared orchestration."""

from app.conversation.service import MessageResult as MessageResult
from app.conversation.service import MessageService as SharedMessageService
from app.conversation.service import SessionClosedError as SessionClosedError
from app.dialog.store import InMemoryDialogStore
from app.packs.insurance_manager.agent.router import Router
from app.packs.insurance_manager.pack import INSURANCE_MANIFEST, InsuranceManagerPack
from app.packs.insurance_manager.processor import InsuranceTurnProcessor
from app.packs.insurance_manager.processor import reply_language_for_turn as reply_language_for_turn
from app.packs.insurance_manager.response.routing import RoutingReplyGenerator
from app.packs.insurance_manager.scenarios.decision_policy import DecisionPolicy
from app.packs.registry import ScenarioRegistry
from app.tracing.collector import TraceCollector


class MessageService(SharedMessageService):
    def __init__(
        self,
        router: Router,
        dialogs: InMemoryDialogStore,
        traces: TraceCollector,
        policy: DecisionPolicy,
        replies: RoutingReplyGenerator,
        *,
        registry: ScenarioRegistry | None = None,
        risk=None,
        events=None,
    ) -> None:
        if registry is None:
            registry = ScenarioRegistry(default_pack_id=INSURANCE_MANIFEST.id)
            registry.register(InsuranceManagerPack(InsuranceTurnProcessor(router, policy, replies)))
        super().__init__(registry, dialogs, traces, risk=risk, events=events)

    @property
    def router(self) -> Router:
        return self.registry.get(INSURANCE_MANIFEST.id).processor.router

    @property
    def policy(self) -> DecisionPolicy:
        return self.registry.get(INSURANCE_MANIFEST.id).processor.policy

    @property
    def replies(self) -> RoutingReplyGenerator:
        return self.registry.get(INSURANCE_MANIFEST.id).processor.replies
