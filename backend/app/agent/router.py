import asyncio
import re
from datetime import date
from typing import Protocol

from agents import Agent, ModelSettings, OpenAIResponsesModel, RunConfig, Runner
from agents.exceptions import (
    MaxTurnsExceeded,
    ModelBehaviorError,
    ModelRefusalError,
    ModelTimeoutError,
)
from agents.retry import ModelRetrySettings
from openai import APIError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError

from app.agent.errors import RouterConfigurationError, RouterOutputError, RouterProviderError
from app.agent.prompts import build_router_input, build_router_instructions
from app.agent.schemas import RouterAgentOutput, RouterDecision
from app.core.config import Settings
from app.data.models import SlotDataset, SlotDefinition
from app.dialog.models import DialogState
from app.scenarios.catalog import ScenarioCatalog


class Router(Protocol):
    async def route(self, text: str, state: DialogState) -> RouterDecision: ...


def build_router_agent(
    catalog: ScenarioCatalog, model: str, *, slots: SlotDataset | None = None
) -> Agent:
    """Construct exactly one SDK agent without performing any API calls."""
    if not model.strip():
        raise ValueError("An explicit OPENAI_ROUTER_MODEL is required")
    return Agent(
        name="Voice Router",
        instructions=build_router_instructions(catalog, slots),
        model=model,
        output_type=RouterAgentOutput,
        tools=[],
        handoffs=[],
    )


class RouterAgent:
    """One bounded SDK run, one structured model call, and no state mutations or repairs."""

    def __init__(
        self,
        catalog: ScenarioCatalog,
        *,
        settings: Settings | None = None,
        slots: SlotDataset | None = None,
    ) -> None:
        self.catalog = catalog
        self.settings = settings if settings is not None else Settings()
        self.slots = slots.model_copy(deep=True) if slots is not None else None
        self._slot_definitions = (
            {slot.name: slot for slot in self.slots.slots} if self.slots else {}
        )

    async def route(self, text: str, state: DialogState) -> RouterDecision:
        api_key = self.settings.openai_api_key
        model = self.settings.openai_router_model
        if not api_key or not api_key.get_secret_value().strip() or not model or not model.strip():
            raise RouterConfigurationError()
        if self.slots is None:
            raise RouterConfigurationError()

        agent = build_router_agent(self.catalog, model.strip(), slots=self.slots)
        agent.model_settings = ModelSettings(
            max_tokens=self.settings.router_max_output_tokens,
            store=False,
            retry=ModelRetrySettings(max_retries=0),
        )
        try:
            async with asyncio.timeout(self.settings.router_timeout_seconds):
                async with AsyncOpenAI(
                    api_key=api_key.get_secret_value(),
                    timeout=self.settings.router_timeout_seconds,
                    max_retries=0,
                ) as client:
                    agent.model = OpenAIResponsesModel(model=model.strip(), openai_client=client)
                    result = await Runner.run(
                        agent,
                        input=build_router_input(text, state),
                        max_turns=1,
                        run_config=RunConfig(
                            tracing_disabled=True,
                            trace_include_sensitive_data=False,
                        ),
                    )
            if not isinstance(result.final_output, RouterAgentOutput):
                raise RouterOutputError()
            decision = result.final_output.to_decision()
            self._validate_decision(decision, state)
            if decision.response_language is None:
                decision.response_language = (
                    decision.language
                    if decision.language in {"ru", "kk"}
                    else getattr(state, "response_language", None) or "ru"
                )
            return decision
        except (TimeoutError, APITimeoutError, ModelTimeoutError) as exc:
            raise RouterProviderError(timeout=True) from exc
        except APIError as exc:
            raise RouterProviderError() from exc
        except (
            ModelBehaviorError,
            ModelRefusalError,
            MaxTurnsExceeded,
            ValidationError,
            ValueError,
        ) as exc:
            raise RouterOutputError() from exc

    def _validate_decision(self, decision: RouterDecision, state: DialogState) -> None:
        selections = [item.scenario_id for item in decision.scenarios]
        alternatives = [item.scenario_id for item in decision.alternatives]
        if any(
            self.catalog.get_by_id(item) is None and self.catalog.get_system_intent(item) is None
            for item in selections + alternatives
        ):
            raise RouterOutputError()
        if len(alternatives) > 2 or len(alternatives) != len(set(alternatives)):
            raise RouterOutputError()
        if set(selections) & set(alternatives):
            raise RouterOutputError()
        if (
            any(self.catalog.get_system_intent(item) for item in selections)
            and len(selections) != 1
        ):
            raise RouterOutputError()
        if {segment.scenario_id for segment in decision.segments} != set(selections):
            raise RouterOutputError()
        if decision.is_continuation and (
            state.active_scenario is None or selections != [state.active_scenario]
        ):
            raise RouterOutputError()
        for name, value in decision.slots.items():
            definition = self._slot_definitions.get(name)
            if definition is None or not _valid_slot_value(definition, value):
                raise RouterOutputError()


def _valid_slot_value(slot: SlotDefinition, value: object) -> bool:
    """Validate source types without coercing booleans, numbers or partial identifiers."""
    if slot.type in {"string", "text", "date"}:
        if not isinstance(value, str) or not value.strip():
            return False
    if slot.type == "integer" and type(value) is not int:
        return False
    if slot.type == "boolean" and type(value) is not bool:
        return False
    if slot.type == "list" and (
        not isinstance(value, list) or not value or any(not isinstance(v, str) for v in value)
    ):
        return False
    if slot.type == "enum" and not any(
        type(value) is type(allowed) and value == allowed for allowed in slot.values or []
    ):
        return False
    if slot.type == "date":
        try:
            if date.fromisoformat(value).isoformat() != value:
                return False
        except (TypeError, ValueError):
            return False
    if slot.pattern:
        values = value if isinstance(value, list) else [value]
        return all(
            isinstance(item, str) and re.fullmatch(slot.pattern, item) is not None
            for item in values
        )
    return value is not None
