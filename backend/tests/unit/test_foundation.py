import asyncio
import json

import pytest
from agents import AgentOutputSchema
from pydantic import ValidationError

from app.agent.errors import RouterConfigurationError
from app.agent.prompts import build_router_input
from app.agent.router import RouterAgent, build_router_agent
from app.agent.schemas import RouterAgentOutput, RouterDecision
from app.core.config import Settings
from app.data.loaders import load_starter_kit
from app.dialog.models import DialogState, DialogTurn
from app.dialog.state import append_turn
from app.dialog.store import InMemoryDialogStore
from app.evaluation.runner import EvaluationRunError, generate_predictions, write_predictions
from app.response.generator import ResponseInput, UnconfiguredResponseGenerator
from app.scenarios.catalog import ScenarioCatalog
from app.scenarios.decision_policy import DecisionPolicy, PolicySettings
from app.scenarios.engine import ScenarioEngine
from app.tracing.collector import TraceCollector
from app.tracing.models import TraceRecord
from app.triage.service import TriageService


@pytest.fixture(scope="module")
def kit():
    return load_starter_kit(Settings(_env_file=None).starter_kit_path)


@pytest.fixture
def catalog(kit):
    return ScenarioCatalog(kit.scenarios)


def decision(*ids, confidence=0.9, continuation=False):
    return RouterDecision(
        language="ru",
        scenarios=[
            {"scenario_id": value, "confidence": confidence, "reason": "Test fixture"}
            for value in ids
        ],
        is_continuation=continuation,
    )


def test_sdk_output_is_strict_and_builds_one_agent(catalog):
    schema = AgentOutputSchema(RouterAgentOutput)
    assert schema.is_strict_json_schema()
    assert schema.json_schema()["additionalProperties"] is False
    agent = build_router_agent(catalog, "test-model-no-network")
    assert not agent.tools and not agent.handoffs
    assert agent.output_type is RouterAgentOutput
    assert "SC40" in agent.instructions and "SYS_UNCLEAR" in agent.instructions
    assert "not_this_if" in agent.instructions


def test_sdk_slots_adapt_without_mutation():
    output = RouterAgentOutput(
        language="kk",
        segments=[
            {"text": "Fixture", "scenario_id": "SC01", "confidence": 0.8, "reason": "Fixture"}
        ],
        scenarios=[{"scenario_id": "SC01", "confidence": 0.8, "reason": "Fixture"}],
        alternatives=[],
        slots=[{"name": "drivers_iin", "value": ["fixture-id"]}],
        is_continuation=False,
    )
    assert output.to_decision().slots == {"drivers_iin": ["fixture-id"]}
    output.slots.append(output.slots[0])
    with pytest.raises(ValueError, match="unique"):
        output.to_decision()


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan")])
def test_router_rejects_invalid_confidence(confidence):
    with pytest.raises(ValidationError):
        decision("SC01", confidence=confidence)


def test_router_rejects_duplicate_scenarios_and_forward_dependencies():
    with pytest.raises(ValidationError):
        decision("SC01", "SC01")
    values = decision("SC01").model_dump()
    values["segments"] = [
        {
            "text": "fixture",
            "scenario_id": "SC01",
            "confidence": 0.9,
            "reason": "fixture",
            "depends_on": [0],
        }
    ]
    with pytest.raises(ValidationError, match="earlier"):
        RouterDecision.model_validate(values)


def test_policy_thresholds_and_handoff(catalog):
    policy = DecisionPolicy(catalog)
    state = DialogState(session_id="s")
    assert policy.decide(decision("SC01", confidence=0.75), state).outcome == "accept"
    assert policy.decide(decision("SC01", confidence=0.45), state).outcome == "clarify"
    first = policy.decide(decision("SC01", confidence=0.2), state)
    assert first.outcome == "clarify" and first.consecutive_low_confidence == 1
    state.consecutive_low_confidence = first.consecutive_low_confidence
    assert policy.decide(decision("SC01", confidence=0.2), state).outcome == "handoff"
    assert policy.decide(decision("SYS_UNCLEAR"), state).outcome == "clarify"
    assert policy.decide(decision("SC37"), state).outcome == "handoff"
    with pytest.raises(ValueError, match="unknown"):
        policy.decide(decision("INVALID"), state)
    with pytest.raises(ValidationError):
        PolicySettings(low_threshold=0.8, accept_threshold=0.7)


def test_policy_urgency_preserves_other_order_and_continuation(catalog):
    policy = DecisionPolicy(catalog)
    state = DialogState(session_id="s", active_scenario="SC01")
    assert policy.decide(decision("SC01", "SC11", "SC35"), state).scenario_ids == [
        "SC11",
        "SC01",
        "SC35",
    ]
    assert policy.decide(decision("SC01", continuation=True), state).outcome == "continue"
    assert policy.decide(decision("SC35", continuation=True), state).outcome == "accept"


def test_confident_operator_request_is_not_lost_to_uncertain_secondary_intent(catalog):
    routing = decision("SC37", "SC01", confidence=0.98)
    routing.scenarios[1].confidence = 0.6
    result = DecisionPolicy(catalog).decide(routing, DialogState(session_id="operator"))
    assert result.outcome == "handoff"
    assert result.scenario_ids == ["SC37"]


def test_engine_only_reads_requirements(catalog):
    engine = ScenarioEngine(catalog)
    state = DialogState(session_id="s")
    assert engine.inspect_requirements("SC28", state).status == "identify"
    initial = engine.inspect_requirements("SC01", state)
    assert initial.status == "collect_slot" and initial.missing_slot == "region"
    assert state.slots == {} and state.active_scenario is None
    with pytest.raises(NotImplementedError):
        asyncio.run(engine.execute("SC28", state))


def test_dialog_store_copies_and_evicts():
    store = InMemoryDialogStore(max_sessions=1)
    original = DialogState(session_id="a", slots={"nested": ["original"]})
    store.save(original)
    original.slots["nested"].append("changed")
    copy = store.get("a")
    assert copy.slots == {"nested": ["original"]}
    copy.slots.clear()
    assert store.get("a").slots
    store.save(DialogState(session_id="b"))
    assert store.get("a") is None


def test_dialog_history_bounded_and_routing_input_contains_context():
    initial = DialogState(session_id="s")
    state = initial
    for _ in range(25):
        state = append_turn(state, DialogTurn(role="user", text="fixture"))
    assert len(state.history) == 20 and state.turn_number == 25
    assert initial.turn_number == 0
    assert len(json.loads(build_router_input("next", state))["dialog_state"]["history"]) == 20


def test_trace_collection_unmeasured_is_null_and_returns_copies():
    collector = TraceCollector(max_turns=1, max_sessions=1)
    record = TraceRecord(turn=1, transcript="fixture")
    collector.add("a", record)
    record.transcript = "changed"
    assert collector.get("a")[0].transcript == "fixture"
    assert collector.get("a")[0].latency_ms.router is None
    collector.add("a", TraceRecord(turn=2, transcript="second"))
    assert [record.turn for record in collector.get("a")] == [2]
    collector.add("b", record)
    assert collector.get("a") == []


def test_triage_does_not_invent_language_or_slots():
    result = TriageService().prepare("  Текст  ")
    assert result.text == "Текст" and result.language is None
    assert result.normalized_slots == {} and result.urgency_hints == []
    with pytest.raises(ValidationError):
        TriageService().prepare("   ")


def test_unimplemented_boundaries_fail_explicitly(catalog):
    state = DialogState(session_id="s")
    with pytest.raises(RouterConfigurationError):
        asyncio.run(
            RouterAgent(
                catalog,
                settings=Settings(_env_file=None, openai_api_key=None, openai_router_model=None),
            ).route("fixture", state)
        )
    context = ResponseInput(
        language="ru",
        scenario_id="SC01",
        dialog_state=state,
        slots={},
        tool_results=[],
        knowledge={},
    )
    with pytest.raises(NotImplementedError, match="response generation"):
        asyncio.run(UnconfiguredResponseGenerator().generate(context))


def test_evaluation_adapter_does_not_pass_labels_to_router(kit, tmp_path):
    class RecordingRouter:
        async def route(self, text, state):
            assert state.history == [] and state.slots == {} and state.active_scenario is None
            assert set(state.model_dump()).isdisjoint({"expected", "type"})
            return decision("SYS_UNCLEAR")  # Offline adapter fixture, not an accuracy evaluation.

    predictions = asyncio.run(generate_predictions(kit.dev_utterances, RecordingRouter()))
    assert len(predictions) == 104
    assert predictions["U001"] == ["SYS_UNCLEAR"]
    output = tmp_path / "predictions.json"
    write_predictions(predictions, output)
    assert json.loads(output.read_text(encoding="utf-8")) == predictions
    with pytest.raises(FileExistsError):
        write_predictions(predictions, output)


def test_evaluation_aborts_on_missing_router(kit, catalog):
    with pytest.raises(EvaluationRunError) as failure:
        asyncio.run(
            generate_predictions(
                kit.dev_utterances,
                RouterAgent(
                    catalog,
                    settings=Settings(
                        _env_file=None, openai_api_key=None, openai_router_model=None
                    ),
                ),
            )
        )
    assert isinstance(failure.value.__cause__, RouterConfigurationError)
