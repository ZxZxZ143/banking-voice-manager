"""Offline boundary tests. Scripted SDK outputs are not model-accuracy measurements."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from agents import AgentOutputSchema
from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError, ModelRefusalError
from openai import APIError, AsyncOpenAI
from pydantic import ValidationError

from app.agent.errors import RouterConfigurationError, RouterOutputError, RouterProviderError
from app.agent.prompts import build_router_input, build_router_instructions
from app.agent.router import RouterAgent
from app.agent.schemas import RouterAgentOutput
from app.core.config import Settings
from app.data.loaders import load_starter_kit
from app.dialog.models import DialogState, DialogTurn
from app.scenarios.catalog import ScenarioCatalog


@pytest.fixture(scope="module")
def kit():
    return load_starter_kit(Settings(_env_file=None).starter_kit_path)


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        openai_api_key="offline-test-key-never-sent",
        openai_router_model="offline-test-model",
    )


@pytest.fixture
def sdk(monkeypatch):
    class OfflineClient:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

    clients = []

    def make_client(**kwargs):
        client = OfflineClient(**kwargs)
        clients.append(client)
        return client

    runner = AsyncMock()
    monkeypatch.setattr("app.agent.router.AsyncOpenAI", make_client)
    monkeypatch.setattr("app.agent.router.Runner.run", runner)
    return SimpleNamespace(run=runner, clients=clients)


def output(*ids, language="ru", response_language="ru", slots=None, continuation=False):
    return RouterAgentOutput(
        language=language,
        response_language=response_language,
        scenarios=[
            {"scenario_id": item, "confidence": 0.92, "reason": "Offline fixture"} for item in ids
        ],
        segments=[
            {
                "text": f"offline segment {index}",
                "scenario_id": item,
                "confidence": 0.92,
                "reason": "Offline fixture",
            }
            for index, item in enumerate(ids)
        ],
        alternatives=[],
        slots=[{"name": name, "value": value} for name, value in (slots or {}).items()],
        is_continuation=continuation,
    )


@pytest.mark.parametrize(
    "ids,language,response_language",
    [
        (("SC01",), "ru", "ru"),
        (("SC33",), "kk", "kk"),
        (("SC27", "SC04"), "mixed", "kk"),
        (("SYS_UNCLEAR",), "ru", "ru"),
        (("SYS_OUT_OF_SCOPE",), "kk", "kk"),
        (("SYS_GOODBYE",), "mixed", "ru"),
    ],
)
def test_one_structured_call_no_retries_or_sdk_memory(
    kit, settings, sdk, ids, language, response_language
):
    sdk.run.return_value = SimpleNamespace(
        final_output=output(*ids, language=language, response_language=response_language)
    )
    state = DialogState(
        session_id="same-session", history=[DialogTurn(role="user", text="earlier")]
    )
    before = state.model_dump()
    result = asyncio.run(
        RouterAgent(ScenarioCatalog(kit.scenarios), settings=settings, slots=kit.slots).route(
            "current utterance", state
        )
    )
    assert [item.scenario_id for item in result.scenarios] == list(ids)
    assert result.language == language and result.response_language == response_language
    assert state.model_dump() == before
    sdk.run.assert_awaited_once()
    agent = sdk.run.call_args.args[0]
    args = sdk.run.call_args.kwargs
    assert not agent.tools and not agent.handoffs
    assert agent.output_type is RouterAgentOutput
    assert agent.model_settings.retry.max_retries == 0
    assert agent.model_settings.max_tokens == settings.router_max_output_tokens
    assert agent.model_settings.store is False
    assert args["max_turns"] == 1
    assert args["run_config"].tracing_disabled
    assert args["run_config"].trace_include_sensitive_data is False
    assert "session" not in args and "previous_response_id" not in args
    payload = json.loads(args["input"])
    assert payload["utterance"] == "current utterance"
    assert payload["dialog_state"] == before
    assert payload["dialog_state"]["history"] == [{"role": "user", "text": "earlier"}]
    assert "offline-test-key" not in args["input"] + agent.instructions
    assert len(sdk.clients) == 1 and sdk.clients[0].closed
    assert sdk.clients[0].options["max_retries"] == 0


def test_catalog_and_prompt_preserve_authoritative_boundaries(kit):
    catalog = ScenarioCatalog(kit.scenarios)
    compact = catalog.get_compact_router_catalog()
    assert len(compact["scenarios"]) == 40 and len(compact["system_intents"]) == 3
    assert compact["reference_date"] == "2026-10-01"
    for entry, source in zip(compact["scenarios"], kit.scenarios.scenarios, strict=True):
        assert entry["description"] == source.description
        assert entry["not_this_if"] == [rule.model_dump() for rule in source.not_this_if]
        assert entry["priority"] == source.priority
        assert entry["examples"] == {"ru": source.examples.ru[:2], "kk": source.examples.kk[:2]}
        assert "actions" not in entry and "responses" not in entry
    prompt = build_router_instructions(catalog, kit.slots)
    assert "independently actionable" in prompt
    assert "not indiscriminately across independent clauses" in prompt
    assert "untrusted DATA" in prompt
    assert "client_id" in prompt and "current utterance" in prompt
    assert '"name":"phone"' in prompt and '"type":"boolean"' in prompt
    assert "U001" not in prompt and "expected" not in prompt


def test_sdk_schema_has_closed_objects_and_required_fields():
    schema = AgentOutputSchema(RouterAgentOutput)
    assert schema.is_strict_json_schema()

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)

    check(schema.json_schema())
    properties = schema.json_schema()["properties"]
    assert properties["scenarios"]["minItems"] == 1
    assert properties["segments"]["minItems"] == 1
    assert properties["alternatives"]["maxItems"] == 2


@pytest.mark.parametrize("field", ["scenarios", "segments"])
def test_sdk_schema_rejects_empty_system_selection_before_domain_adapter(field):
    payload = output("SYS_UNCLEAR").model_dump()
    payload[field] = []
    with pytest.raises(ValidationError):
        RouterAgentOutput.model_validate(payload)


def test_source_enum_spelling_and_known_city_region_bucket(kit, settings, sdk):
    sdk.run.return_value = SimpleNamespace(
        final_output=output("SC01", slots={"region": "Karaganda", "city": "astana"})
    )
    result = asyncio.run(
        RouterAgent(ScenarioCatalog(kit.scenarios), settings=settings, slots=kit.slots).route(
            "Synthetic location slots", DialogState(session_id="s")
        )
    )
    assert result.slots == {"region": "other", "city": "Astana"}


def test_clarification_question_survives_closed_schema_adapter():
    answer = output("SYS_UNCLEAR", language="kk", response_language="kk")
    answer.clarification_question = "Полис алу немесе төлем туралы білгіңіз келе ме?"
    decision = answer.to_decision()
    assert decision.clarification_question == answer.clarification_question
    assert decision.response_language == "kk"


def test_general_prompt_regressions_do_not_embed_dev_utterances(kit):
    prompt = build_router_instructions(ScenarioCatalog(kit.scenarios), kit.slots)
    for principle in (
        "does not erase them",
        "not alternatives",
        "money owed BY the insurer",
        "fresh state's response_language=ru is only a default",
        "Never fill absent numeric amounts with zero",
        "clarification_options",
        "clarification_question=null",
    ):
        assert principle in prompt
    assert "dev_utterances" not in prompt


def test_fresh_input_does_not_present_storage_language_defaults_as_preferences():
    state = DialogState(session_id="fresh")
    context = json.loads(build_router_input("Сәлеметсіз бе", state))["dialog_state"]
    assert "language" not in context and "response_language" not in context
    assert state.language is None and state.response_language == "ru"
    state.turn_number = 1
    state.language = "kk"
    state.response_language = "kk"
    context = json.loads(build_router_input("123", state))["dialog_state"]
    assert context["language"] == "kk" and context["response_language"] == "kk"


def test_slot_answer_continues_active_scenario_without_changing_state(kit, settings, sdk):
    sdk.run.return_value = SimpleNamespace(
        final_output=output("SC04", slots={"new_driver_iin": "900101300111"}, continuation=True)
    )
    state = DialogState(
        session_id="s",
        active_scenario="SC04",
        slots={"policy_number": "SQ-OGPO-123456"},
        history=[DialogTurn(role="assistant", text="ИИН нового водителя?")],
    )
    result = asyncio.run(
        RouterAgent(ScenarioCatalog(kit.scenarios), settings=settings, slots=kit.slots).route(
            "900101300111", state
        )
    )
    assert result.is_continuation
    assert result.slots == {"new_driver_iin": "900101300111"}
    assert state.slots == {"policy_number": "SQ-OGPO-123456"}


@pytest.mark.parametrize(
    "slots",
    [
        {"phone": "+77015551234", "incident_date": "2026-10-01", "injured": False},
        {"franchise": 50000, "car_year": 2020, "city": "Astana"},
        {"drivers_iin": ["900101300111", "920402400222"]},
        {"contact_field": "email", "new_value": "new@example.test"},
    ],
)
def test_source_slot_types_are_accepted(kit, settings, sdk, slots):
    sdk.run.return_value = SimpleNamespace(final_output=output("SC01", slots=slots))
    result = asyncio.run(
        RouterAgent(ScenarioCatalog(kit.scenarios), settings=settings, slots=kit.slots).route(
            "Offline fixture", DialogState(session_id="s")
        )
    )
    assert result.slots == slots


@pytest.mark.parametrize(
    "slots",
    [
        {"client_id": "C001"},
        {"conversation_status": "ended"},
        {"phone": "123"},
        {"iin": 900101300111},
        {"drivers_iin": ["son"]},
        {"drivers_iin": []},
        {"car_year": True},
        {"car_year": "2020"},
        {"injured": "false"},
        {"city": "unknown"},
        {"franchise": False},
        {"incident_date": "2026-02-31"},
        {"incident_date": "20261001"},
        {"phone": None},
        {"email": "not-an-email"},
    ],
)
def test_invalid_or_application_owned_slots_rejected_without_retry(kit, settings, sdk, slots):
    sdk.run.return_value = SimpleNamespace(final_output=output("SC01", slots=slots))
    with pytest.raises(RouterOutputError):
        asyncio.run(
            RouterAgent(ScenarioCatalog(kit.scenarios), settings=settings, slots=kit.slots).route(
                "Offline fixture", DialogState(session_id="s")
            )
        )
    sdk.run.assert_awaited_once()
    assert sdk.clients[0].closed


@pytest.mark.parametrize("invalid", ["unknown", "mix", "segments", "alternative", "continuation"])
def test_invalid_decisions_rejected(kit, settings, sdk, invalid):
    answer = output("SC01")
    if invalid == "unknown":
        answer = output("SC99")
    elif invalid == "mix":
        answer = output("SC01", "SYS_GOODBYE")
    elif invalid == "segments":
        answer.segments[0].scenario_id = "SC02"
    elif invalid == "alternative":
        answer.alternatives = [{"scenario_id": "SC99", "confidence": 0.1}]
    elif invalid == "continuation":
        answer.is_continuation = True
    sdk.run.return_value = SimpleNamespace(final_output=answer)
    with pytest.raises(RouterOutputError):
        asyncio.run(
            RouterAgent(ScenarioCatalog(kit.scenarios), settings=settings, slots=kit.slots).route(
                "Offline fixture", DialogState(session_id="s")
            )
        )
    sdk.run.assert_awaited_once()


@pytest.mark.parametrize(
    ("invalid", "reason"),
    [
        ("unknown", "unknown_scenario"),
        ("alternative_duplicate", "alternatives"),
        ("alternative_overlap", "alternatives"),
        ("system_mix", "system_mix"),
        ("segments", "segment_coverage"),
        ("continuation", "continuation"),
        ("unknown_slot", "unknown_slot"),
        ("invalid_slot", "invalid_slot"),
    ],
)
def test_invalid_output_exposes_only_fixed_validation_reason(kit, settings, sdk, invalid, reason):
    answer = output("SC01")
    if invalid == "unknown":
        answer = output("SC99")
    elif invalid == "alternative_duplicate":
        answer.alternatives = [{"scenario_id": "SC02", "confidence": 0.1}] * 2
    elif invalid == "alternative_overlap":
        answer.alternatives = [{"scenario_id": "SC01", "confidence": 0.1}]
    elif invalid == "system_mix":
        answer = output("SC01", "SYS_GOODBYE")
    elif invalid == "segments":
        answer = output("SC01", "SC02")
        answer.segments = answer.segments[:1]
    elif invalid == "continuation":
        answer.is_continuation = True
    elif invalid == "unknown_slot":
        answer = output("SC01", slots={"private_slot_name": "private_slot_value"})
    elif invalid == "invalid_slot":
        answer = output("SC01", slots={"phone": "private_slot_value"})
    sdk.run.return_value = SimpleNamespace(final_output=answer)
    with pytest.raises(RouterOutputError) as failure:
        asyncio.run(
            RouterAgent(ScenarioCatalog(kit.scenarios), settings=settings, slots=kit.slots).route(
                "Offline fixture", DialogState(session_id="s")
            )
        )
    assert failure.value.validation_reason == reason
    assert failure.value.code == "router_invalid_output"
    assert failure.value.message == RouterOutputError().message
    assert "private_slot" not in str(failure.value)
    sdk.run.assert_awaited_once()


@pytest.mark.parametrize("missing", ["key", "model", "slots"])
def test_unconfigured_route_fails_before_constructing_client(kit, settings, sdk, missing):
    if missing == "key":
        settings.openai_api_key = None
    elif missing == "model":
        settings.openai_router_model = None
    router = RouterAgent(
        ScenarioCatalog(kit.scenarios),
        settings=settings,
        slots=None if missing == "slots" else kit.slots,
    )
    with pytest.raises(RouterConfigurationError) as failure:
        asyncio.run(router.route("Offline fixture", DialogState(session_id="s")))
    assert failure.value.code == "router_not_configured"
    assert sdk.clients == []
    sdk.run.assert_not_awaited()


@pytest.mark.parametrize(
    "error,exception,code",
    [
        (TimeoutError("secret body"), RouterProviderError, "router_timeout"),
        (APIError("secret body", Mock(), body=None), RouterProviderError, "router_provider_error"),
        (ModelBehaviorError("secret body"), RouterOutputError, "router_invalid_output"),
        (ModelRefusalError("secret body"), RouterOutputError, "router_invalid_output"),
        (MaxTurnsExceeded("secret body"), RouterOutputError, "router_invalid_output"),
    ],
)
def test_provider_failure_is_safe_bounded_and_closes_client(
    kit, settings, sdk, error, exception, code
):
    sdk.run.side_effect = error
    with pytest.raises(exception) as failure:
        asyncio.run(
            RouterAgent(ScenarioCatalog(kit.scenarios), settings=settings, slots=kit.slots).route(
                "Offline fixture", DialogState(session_id="s")
            )
        )
    assert failure.value.code == code
    assert "secret body" not in str(failure.value)
    assert sdk.clients[0].closed
    sdk.run.assert_awaited_once()


def test_real_timeout_cancels_the_only_call_and_closes_client(kit, settings, sdk):
    async def stalled(*args, **kwargs):
        await asyncio.sleep(30)

    sdk.run.side_effect = stalled
    settings = settings.model_copy(update={"router_timeout_seconds": 0.02})
    with pytest.raises(RouterProviderError) as failure:
        asyncio.run(
            RouterAgent(ScenarioCatalog(kit.scenarios), settings=settings, slots=kit.slots).route(
                "Offline fixture", DialogState(session_id="s")
            )
        )
    assert failure.value.code == "router_timeout"
    assert sdk.clients[0].closed
    sdk.run.assert_awaited_once()


@pytest.mark.parametrize("provider_status", [200, 500])
def test_actual_sdk_runner_and_responses_transport_make_one_http_request(
    kit, settings, monkeypatch, provider_status
):
    """Exercise installed Runner, strict JSON parsing and provider retries without network."""
    requests = []
    clients = []

    def transport(request):
        requests.append(json.loads(request.content))
        if provider_status != 200:
            return httpx2.Response(500, json={"error": {"message": "offline provider failure"}})
        return httpx2.Response(
            200,
            json={
                "id": "resp_offline_test",
                "object": "response",
                "created_at": 0,
                "model": "offline-test-model",
                "status": "completed",
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "output": [
                    {
                        "id": "msg_offline_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": output("SC27", "SC04").model_dump_json(),
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
        )

    def client(**kwargs):
        instance = AsyncOpenAI(
            **kwargs,
            base_url="https://offline-router.invalid/v1",
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
        )
        clients.append(instance)
        return instance

    monkeypatch.setattr("app.agent.router.AsyncOpenAI", client)
    router = RouterAgent(ScenarioCatalog(kit.scenarios), settings=settings, slots=kit.slots)
    if provider_status == 200:
        decision = asyncio.run(router.route("offline fixture", DialogState(session_id="s")))
        assert [item.scenario_id for item in decision.scenarios] == ["SC27", "SC04"]
    else:
        with pytest.raises(RouterProviderError):
            asyncio.run(router.route("offline fixture", DialogState(session_id="s")))
    assert len(requests) == 1
    assert requests[0]["text"]["format"]["type"] == "json_schema"
    assert requests[0]["text"]["format"]["strict"] is True
    assert requests[0]["store"] is False
    assert requests[0]["max_output_tokens"] == settings.router_max_output_tokens
    assert not requests[0].get("tools")
    assert len(clients) == 1 and clients[0].is_closed()
