import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.data.loaders import load_starter_kit
from app.tools.actions import ToolResult
from app.tools.errors import ToolError
from app.tools.registry import ActionRegistry

STARTER_KIT = Path(__file__).resolve().parents[3] / "data" / "starter_kit"


@pytest.fixture
def registry():
    return ActionRegistry(load_starter_kit(STARTER_KIT).actions)


def test_definitions_available_without_claiming_implementation(registry):
    assert len(registry.get_all()) == 31
    assert registry.get_by_name("find_client").inputs == ["phone|iin"]
    assert registry.get_by_name("cancel_policy").irreversible is True
    assert registry.get_by_name("unknown") is None
    registry.get_by_name("cancel_policy").irreversible = False
    assert registry.get_by_name("cancel_policy").irreversible is True
    failure = asyncio.run(registry.execute("get_policy", {"policy_number": "SQ-OGPO-104501"}))
    assert failure.error.code == "not_implemented"
    assert asyncio.run(registry.execute("unknown", {})).error.code == "unknown_action"


def test_failure_payload_matches_starter_kit_and_result_invariants():
    failure = ToolResult.failure("not_found", "No matching record")
    assert failure.to_payload() == {"error": {"code": "not_found", "message": "No matching record"}}
    with pytest.raises(ValidationError):
        ToolResult(success=True, data={}, error=ToolError(code="bad", message="failed"))
    with pytest.raises(ValidationError):
        ToolResult(success=False, data={})
    with pytest.raises(ValidationError):
        ToolResult(success=True)


def test_irreversible_actions_cannot_be_registered_or_executed(registry):
    called = False

    async def handler(inputs):
        nonlocal called
        called = True
        return ToolResult(success=True, data={})

    with pytest.raises(ValueError, match="confirmation executor"):
        registry.register("cancel_policy", handler)
    result = asyncio.run(registry.execute("cancel_policy", {"confirmed": True}))
    assert result.error.code == "irreversible_action_disabled"
    assert called is False


def test_handler_registration_and_required_alternative_inputs(registry):
    calls = []

    async def handler(inputs):
        calls.append(inputs)
        inputs["context"].append("handler changed its copy")
        return ToolResult(success=True, data={"client_id": "C001"})

    registry.register("find_client", handler)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("find_client", handler)
    with pytest.raises(ValueError, match="Unknown action"):
        registry.register("does_not_exist", handler)
    result = asyncio.run(registry.execute("find_client", {}))
    assert result.error.code == "invalid_input"
    assert calls == []
    inputs = {"iin": "850314300121", "context": []}
    result = asyncio.run(registry.execute("find_client", inputs))
    assert result.to_payload() == {"client_id": "C001"}
    assert inputs["context"] == []
    assert len(calls) == 1
