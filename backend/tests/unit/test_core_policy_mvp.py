"""Focused offline checks for urgent routing and non-executing MVP boundaries."""

import asyncio

import pytest

from app.agent.schemas import RouterDecision
from app.core.config import Settings
from app.data.loaders import load_starter_kit
from app.dialog.message import MessageService
from app.dialog.models import DialogState
from app.dialog.store import InMemoryDialogStore
from app.response.routing import RoutingReplyGenerator
from app.scenarios.catalog import ScenarioCatalog
from app.scenarios.decision_policy import DecisionPolicy, PolicySettings
from app.tools.actions import ToolResult
from app.tools.registry import ActionRegistry
from app.tracing.collector import TraceCollector


@pytest.fixture(scope="module")
def kit():
    return load_starter_kit(Settings(_env_file=None).starter_kit_path)


def decision(*selections):
    return RouterDecision(
        language="ru",
        response_language="ru",
        scenarios=[
            {"scenario_id": scenario_id, "confidence": confidence, "reason": "Offline fixture"}
            for scenario_id, confidence in selections
        ],
    )


@pytest.mark.parametrize("secondary_confidence", [0.2, 0.6])
@pytest.mark.parametrize("prior_low", [0, 1])
def test_confident_urgent_request_survives_weak_secondary_and_prior_uncertainty(
    kit, secondary_confidence, prior_low
):
    state = DialogState(session_id="urgent", consecutive_low_confidence=prior_low, unclear_count=2)
    routing = decision(("SC01", secondary_confidence), ("SC33", 0.9), ("SC11", 0.75))
    original = routing.model_dump()
    result = DecisionPolicy(ScenarioCatalog(kit.scenarios)).decide(routing, state)
    assert result.outcome == "accept"
    assert result.scenario_ids == ["SC11", "SC33"]
    assert result.consecutive_low_confidence == 0
    assert routing.model_dump() == original
    assert state.consecutive_low_confidence == prior_low and state.unclear_count == 2


def test_explicit_operator_request_takes_precedence_over_confident_urgent_intent(kit):
    routing = decision(("SC11", 0.98), ("SC01", 0.2), ("SC37", 0.75))
    result = DecisionPolicy(ScenarioCatalog(kit.scenarios)).decide(
        routing, DialogState(session_id="operator", consecutive_low_confidence=1)
    )
    assert result.outcome == "handoff" and result.scenario_ids == ["SC37"]


def test_uncertain_urgent_selection_is_not_promoted_to_accepted_intent(kit):
    result = DecisionPolicy(ScenarioCatalog(kit.scenarios)).decide(
        decision(("SC11", 0.6), ("SC33", 0.98)), DialogState(session_id="uncertain")
    )
    assert result.outcome == "clarify" and result.scenario_ids == ["SYS_UNCLEAR"]


def test_urgent_confidence_uses_configured_accept_threshold(kit):
    policy = DecisionPolicy(ScenarioCatalog(kit.scenarios), PolicySettings(accept_threshold=0.9))
    result = policy.decide(
        decision(("SC11", 0.89), ("SC01", 0.6)), DialogState(session_id="threshold")
    )
    assert result.outcome == "clarify"


def test_urgent_turn_retains_secondary_evidence_without_accepting_uncertain_pending_work(kit):
    catalog = ScenarioCatalog(kit.scenarios)
    dialogs = InMemoryDialogStore()
    traces = TraceCollector()
    routing = decision(("SC01", 0.2), ("SC33", 0.9), ("SC11", 0.98))

    class FixtureRouter:
        async def route(self, text, state):
            return routing.model_copy(deep=True)

    dialogs.save(
        DialogState(
            session_id="urgent",
            active_scenario="SC27",
            pending_scenarios=["SC04"],
            consecutive_low_confidence=1,
            unclear_count=2,
        )
    )
    service = MessageService(
        FixtureRouter(),
        dialogs,
        traces,
        DecisionPolicy(catalog),
        RoutingReplyGenerator(catalog, kit.slots),
    )
    result = asyncio.run(
        service.process("urgent", "Urgent request and an uncertain second request")
    )
    assert result.state.active_scenario == "SC11"
    assert result.state.pending_scenarios == ["SC33", "SC04"]
    assert result.state.scenario_stack == ["SC27"]
    assert result.state.unclear_count == result.state.consecutive_low_confidence == 0
    assert result.conversation_status == "awaiting_user"
    assert result.trace.handoff is False and result.trace.clarification is False
    assert [(item.scenario_id, item.confidence) for item in result.trace.scenarios] == [
        ("SC01", 0.2),
        ("SC33", 0.9),
        ("SC11", 0.98),
    ]
    assert result.state.history[0].text == "Urgent request and an uncertain second request"
    assert result.trace.actions == []
    assert result.state.awaiting_confirmation is False


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_handoff_response_is_truthful_about_simulated_transfer(kit, language):
    catalog = ScenarioCatalog(kit.scenarios)
    state = DialogState(
        session_id="handoff", response_language=language, conversation_status="handoff"
    )
    policy = DecisionPolicy(catalog).decide(decision(("SC37", 0.99)), state)
    reply = RoutingReplyGenerator(catalog, kit.slots).generate_result(state, policy)
    assert ("не подключён" if language == "ru" else "іске қосылмаған") in reply.text
    assert reply.actions == [] and reply.completed is False


def test_every_irreversible_action_stays_disabled_even_with_confirmation_input(kit):
    registry = ActionRegistry(kit.actions)
    calls = []

    async def handler(inputs):
        calls.append(inputs)
        return ToolResult(success=True, data={})

    irreversible = [action.name for action in kit.actions.actions if action.irreversible]
    assert irreversible
    for name in irreversible:
        with pytest.raises(ValueError, match="confirmation executor"):
            registry.register(name, handler)
        result = asyncio.run(registry.execute(name, {"confirmed": True, "confirmation": "yes"}))
        assert not result.success and result.error.code == "irreversible_action_disabled"
    assert calls == []
