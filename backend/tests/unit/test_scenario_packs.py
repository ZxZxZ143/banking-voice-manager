"""Architecture checks also use a private fixture to test the generic boundary."""

import ast
import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import Field, ValidationError

from app.agent.prompts import build_router_input
from app.agent.schemas import RouterDecision
from app.conversation.service import MessageService
from app.conversation.store import ConversationStore
from app.core.config import Settings
from app.core.contracts import Contract
from app.core.services import build_services
from app.dialog.models import DialogState, DialogTurn
from app.main import create_app
from app.packs.contracts import (
    ConversationContext,
    GlobalConversationContext,
    InteractionMode,
    PackTurn,
    ScenarioManifest,
    ScenarioResult,
)
from app.packs.insurance_manager.pack import INSURANCE_MANIFEST, InsuranceResult
from app.packs.insurance_manager.state import InsuranceScenarioContext
from app.packs.lifecycle import ScenarioLifecycle
from app.packs.registry import UnknownScenarioPackError
from app.tracing.collector import TraceCollector
from app.tracing.models import TraceRecord


class FixtureContext(Contract):
    fixture_history: list[str] = Field(default_factory=list)


class FixturePack:
    manifest = ScenarioManifest(
        id="fixture_only",
        name="Private test fixture",
        interaction_mode=InteractionMode.REACTIVE,
        supported_languages=("ru",),
        output_schema="ScenarioResult",
    )
    state_schema = FixtureContext
    output_schema = ScenarioResult
    prompt = "fixture prompt"
    knowledge = {"fixture": "private"}
    tools = ()
    policies = ()
    completion_rules = "Fixture turns remain active"

    def new_context(self):
        return FixtureContext()

    async def handle_turn(self, text, global_context, context):
        assert type(context) is FixtureContext
        assert not hasattr(global_context, "slots")
        context.fixture_history.append(text)
        global_context.session_id = "attempted-snapshot-mutation"
        return PackTurn(
            context=context,
            language="ru",
            response_text="Private fixture reply",
            routing=Contract(),
            public_state=context.model_copy(deep=True),
            trace=TraceRecord(turn=global_context.turn_number + 1, transcript=text),
            result=ScenarioResult(status="active", completed=False, handoff=False),
        )


class FixtureRouter:
    def __init__(self, scenario_id="SC04", *, slots=None):
        self.scenario_id = scenario_id
        self.slots = slots or {}
        self.inputs = []

    async def route(self, text, state):
        self.inputs.append(state.model_copy(deep=True))
        return RouterDecision(
            language="ru",
            slots=self.slots,
            scenarios=[
                dict(scenario_id=self.scenario_id, confidence=0.95, reason="Offline fixture")
            ],
        )


def services(router=None):
    return build_services(Settings(_env_file=None), router_override=router or FixtureRouter())


def test_production_registry_manifest_and_owned_capabilities():
    built = services()
    assert [pack.manifest.id for pack in built.registry.list()] == [
        "insurance_manager",
        "product_promoter",
        "card_promoter",
        "loan_promoter",
        "fraud_security",
    ]
    pack = built.registry.get()
    assert built.registry.exists("insurance_manager")
    assert pack.manifest == INSURANCE_MANIFEST
    assert pack.manifest.interaction_mode == InteractionMode.CONSULTATIVE
    assert pack.manifest.supported_languages == ("ru", "kk", "mixed")
    assert pack.state_schema is InsuranceScenarioContext
    assert pack.output_schema is InsuranceResult
    assert len(pack.tools.get_all()) == 31
    assert pack.knowledge is built.knowledge
    assert pack.policies is built.policy
    with pytest.raises(ValueError, match="already registered"):
        built.registry.register(pack)
    with pytest.raises(UnknownScenarioPackError):
        built.registry.get("missing_pack")
    assert not built.registry.exists("fixture_only")


def test_completion_prompt_fingerprint_documents_context_and_identifier_contract():
    assert hashlib.sha256(services().insurance.prompt.encode()).hexdigest() == (
        "c25932163e3a634f0e4d8d42f878d1855899626dd20dc48cd76a551f5c93d05e"
    )


def test_global_schema_rejects_business_fields():
    forbidden = {"slots", "client_id", "active_scenario", "history", "pending_scenarios"}
    assert forbidden.isdisjoint(GlobalConversationContext.model_fields)
    for field in forbidden:
        with pytest.raises(ValidationError):
            GlobalConversationContext(session_id="session", **{field: {}})


def test_legacy_projection_and_router_input_round_trip():
    original = DialogState(
        session_id="round-trip",
        turn_number=3,
        language="mixed",
        response_language="kk",
        conversation_status="awaiting_user",
        active_scenario="SC04",
        slots={"destination": "Turkey", "travelers_ages": [29]},
        pending_scenarios=["SC27"],
        scenario_stack=["SC01"],
        history=[DialogTurn(role="user", text="Синтетический предыдущий вопрос")],
    )
    global_context = GlobalConversationContext(
        session_id=original.session_id,
        turn_number=original.turn_number,
        language=original.language,
        conversation_status=original.conversation_status,
    )
    local = InsuranceScenarioContext.from_dialog(original)
    projected = local.to_dialog(global_context)
    assert projected.model_dump() == original.model_dump()
    assert build_router_input("Следующий ход", projected) == build_router_input(
        "Следующий ход", original
    )
    assert set(local.model_dump()).isdisjoint({"session_id", "turn_number", "language"})


def test_activate_suspend_resume_complete_and_fresh_context():
    registry = services().registry
    registry.register(FixturePack())
    lifecycle = ScenarioLifecycle(registry)
    conversation = ConversationContext(global_context=GlobalConversationContext(session_id="life"))
    assert conversation.active_scenario_pack is None
    insurance = lifecycle.activate(conversation, "insurance_manager")
    insurance.state.slots = {"phone": "+77010000001", "travelers_ages": [29]}
    fixture = lifecycle.activate(conversation, "fixture_only")
    assert insurance.lifecycle == "suspended" and fixture.lifecycle == "active"
    assert fixture.state.model_dump() == {"fixture_history": []}
    fixture.state.fixture_history.append("fixture-private")
    assert lifecycle.activate(conversation, "insurance_manager") is insurance
    assert insurance.lifecycle == "resumed" and fixture.lifecycle == "suspended"
    assert insurance.state.slots["travelers_ages"] == [29]
    before = conversation.model_dump()
    with pytest.raises(UnknownScenarioPackError):
        lifecycle.activate(conversation, "unknown")
    assert conversation.model_dump() == before
    lifecycle.complete(conversation)
    assert insurance.lifecycle == "completed"
    fresh = lifecycle.activate(conversation, "insurance_manager")
    assert fresh is not insurance and fresh.lifecycle == "active" and fresh.state.slots == {}


def test_shared_core_passes_only_selected_context_and_preserves_resume():
    built = services()
    router = built.router
    fixture = FixturePack()
    built.registry.register(fixture)
    store = ConversationStore()
    conversation = ConversationContext(
        global_context=GlobalConversationContext(session_id="firewall")
    )
    lifecycle = ScenarioLifecycle(built.registry)
    entry = lifecycle.activate(conversation, "insurance_manager")
    entry.state.slots = {"destination": "Turkey", "travelers_ages": [29]}
    entry.state.history = [DialogTurn(role="user", text="Insurance-private background")]
    entry.state.active_scenario = "SC04"
    store.save_conversation(conversation)
    core = MessageService(built.registry, store, TraceCollector())
    result = asyncio.run(core.process("firewall", "fixture-private", "fixture_only"))
    assert result.state.model_dump() == {"fixture_history": ["fixture-private"]}
    assert result.scenario_pack_id == "fixture_only"
    stored = store.get_conversation("firewall")
    assert stored.global_context.session_id == "firewall"
    assert stored.global_context.turn_number == 1
    assert stored.scenario_contexts["insurance_manager"].state.slots == entry.state.slots
    assert router.inputs == []
    resumed = asyncio.run(core.process("firewall", "Продолжаем", "insurance_manager"))
    assert resumed.trace.context_lifecycle == "resumed"
    payload = json.loads(build_router_input("Продолжаем", router.inputs[-1]))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "Insurance-private background" in serialized
    assert "fixture-private" not in serialized and "fixture prompt" not in serialized
    assert resumed.state.slots["destination"] == "Turkey"
    assert resumed.trace.turn_number == 2
    saved = store.get_conversation("firewall")
    assert saved.scenario_contexts["fixture_only"].state.fixture_history == ["fixture-private"]
    assert fixture.knowledge == {"fixture": "private"} and fixture.tools == ()
    assert isinstance(saved.scenario_contexts["insurance_manager"].result, InsuranceResult)


@pytest.mark.parametrize("mode", [None, "insurance_manager"])
def test_api_default_and_explicit_pack_preserve_stage1_contract(mode):
    router = FixtureRouter("SC37")
    with TestClient(create_app(Settings(_env_file=None), router_override=router)) as client:
        payload = {"session_id": "compat", "text": "Оператор"}
        if mode is not None:
            payload["scenario_mode"] = mode
        response = client.post("/api/message", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "session_id",
            "response_text",
            "routing",
            "state",
            "trace",
            "conversation_status",
        }
        assert body["response_text"] == "Конечно, передаю диалог оператору."
        assert body["conversation_status"] == "handoff"
        assert body["trace"]["scenario_pack_id"] == "insurance_manager"
        assert body["trace"]["interaction_mode"] == "consultative"
        assert body["trace"]["context_lifecycle"] == "completed"
        stored = client.app.state.services.dialogs.get_conversation("compat")
        result = stored.scenario_contexts["insurance_manager"].result
        assert isinstance(result, InsuranceResult) and result.handoff
        assert client.post("/api/message", json=payload).status_code == 409


def test_unknown_pack_rejected_without_router_call_or_state_commit():
    router = FixtureRouter()
    with TestClient(create_app(Settings(_env_file=None), router_override=router)) as client:
        response = client.post(
            "/api/message",
            json={"session_id": "unknown", "text": "Вопрос", "scenario_mode": "fixture_only"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unknown_scenario_pack"
        assert router.inputs == []
        assert client.app.state.services.dialogs.get_conversation("unknown") is None


def test_failed_pack_switch_does_not_commit_mutated_context_or_global_state():
    class BrokenFixturePack(FixturePack):
        async def handle_turn(self, text, global_context, context):
            context.fixture_history.append("uncommitted mutation")
            global_context.language = "kk"
            raise RuntimeError("Offline fixture failure")

    built = services()
    built.registry.register(BrokenFixturePack())
    store = ConversationStore()
    conversation = ConversationContext(
        global_context=GlobalConversationContext(session_id="rollback")
    )
    ScenarioLifecycle(built.registry).activate(conversation, "insurance_manager")
    store.save_conversation(conversation)
    before = store.get_conversation("rollback").model_dump()
    core = MessageService(built.registry, store, TraceCollector())
    with pytest.raises(RuntimeError, match="Offline fixture failure"):
        asyncio.run(core.process("rollback", "Fixture turn", "fixture_only"))
    assert store.get_conversation("rollback").model_dump() == before
    assert core.traces.get("rollback") == []


def test_result_keeps_completed_flow_data_without_completing_conversation():
    router = FixtureRouter("SC33", slots={"city": "Astana"})
    built = services(router)
    result = asyncio.run(built.messages.process("flow", "Где офис?"))
    assert isinstance(result.scenario_result, InsuranceResult)
    assert result.scenario_result.scenario_id == "SC33"
    assert result.scenario_result.completed and not result.scenario_result.handoff
    stored = built.dialogs.get_conversation("flow")
    assert stored.global_context.conversation_status == "active"
    assert stored.scenario_contexts["insurance_manager"].lifecycle == "active"
    assert stored.scenario_contexts["insurance_manager"].result.actions == ["get_offices"]
    assert stored.scenario_contexts["insurance_manager"].result.collected_data == {"city": "Astana"}


def test_shared_orchestration_does_not_import_insurance_implementation():
    root = Path(__file__).parents[2] / "app"
    paths = [*(root / "conversation").glob("*.py"), *(root / "packs").glob("*.py")]
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert "insurance_manager" not in (node.module or ""), path
