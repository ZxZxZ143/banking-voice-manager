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
from app.core.config import Settings
from app.packs.insurance_manager.agent.prompts import build_router_input, build_router_instructions
from app.packs.insurance_manager.agent.schemas import (
    RouterAgentOutput,
    RouterDecision,
    source_output_type,
)
from app.packs.insurance_manager.data.models import SlotDataset, SlotDefinition
from app.packs.insurance_manager.scenarios.catalog import ScenarioCatalog
from app.packs.insurance_manager.state import DialogState


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
        output_type=source_output_type(slots),
        tools=[],
        handoffs=[],
    )


class RouterAgent:
    """One structured model call, source enum normalization, no state mutations/repair calls."""

    def __init__(
        self,
        catalog: ScenarioCatalog,
        *,
        settings: Settings | None = None,
        slots: SlotDataset | None = None,
        local_phone: str | None = None,
    ) -> None:
        self.catalog = catalog
        self.local_phone = local_phone
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
        if state.conversation is not None:
            agent.instructions += (
                "\nCONVERSATIONAL DISCOVERY: Choosing new versus existing is only partial "
                "context, not a product or requested operation. Do not choose an OGPO purchase "
                "without evidence of the vehicle product. Keep SYS_UNCLEAR + partial_answer "
                "until the product or concrete existing-policy problem is known. "
                "A conversational continuation without the same active business scenario "
                "must use is_continuation=false. Never invent an outcome from context alone."
                " Extract ALL clearly provided entities even when inflected in Kazakh, "
                "normalizing grammatical endings to the base name where unambiguous. "
                "Do not omit a destination explicitly named in the utterance. "
                "Hesitation or filler alone is not meaningful progress: conversation_signal "
                "must be none unless the answer actually narrows a goal or supplies data."
                " A purely social question about this assistant's wellbeing is small talk: "
                "select SYS_OUT_OF_SCOPE, scope_kind=small_talk, conversation_signal=none. "
                "An identity enquiry is SYS_OUT_OF_SCOPE, scope_kind=identity. "
                "These rules apply even while awaiting a phone or other business field. "
                "Do not reinterpret a social/identity question as an attempted field answer "
                "or a human transfer request. Preserve the business goal for the next turn."
            )
        agent.model_settings = ModelSettings(
            temperature=self.settings.router_temperature,
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
                        input=build_router_input(text, state, local_phone=self.local_phone),
                        max_turns=1,
                        run_config=RunConfig(
                            tracing_disabled=True,
                            trace_include_sensitive_data=False,
                        ),
                    )
            if not isinstance(result.final_output, RouterAgentOutput):
                raise RouterOutputError()
            decision = result.final_output.to_decision()
            self._normalize_enums(decision)
            if (
                state.conversation is not None
                and decision.is_continuation
                and [s.scenario_id for s in decision.scenarios] != [state.active_scenario]
            ):
                # Completed or different scenarios cannot be continued. Keep the model's
                # selection as a fresh request; lifecycle owns which scenario is active.
                decision.is_continuation = False
                if decision.conversation_signal == "none" and [
                    s.scenario_id for s in decision.scenarios
                ] == ["SYS_UNCLEAR"]:
                    decision.conversation_signal = "partial_answer"
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

    def _normalize_enums(self, decision: RouterDecision) -> None:
        """Normalize exact source enum spellings; never choose or repair scenario IDs."""
        if decision.slots.get("phone") == "[локальный телефон получен]":
            # This app-owned transport marker is not an extracted identifier. The
            # processor separately validates the original literal phone locally.
            del decision.slots["phone"]
        callback_time = decision.slots.get("callback_time")
        if isinstance(callback_time, str) and callback_time.strip().casefold() in {
            "позже",
            "потом",
            "позднее",
            "кейін",
            "кейінірек",
            "later",
        }:
            # A request to call later supplies intent, but no usable time preference.
            del decision.slots["callback_time"]
        for name, value in decision.slots.items():
            if name == "phone" and isinstance(value, str):
                from app.packs.insurance_manager.data.demo_profile import normalize_phone

                try:
                    decision.slots[name] = normalize_phone(value)
                except ValueError:
                    pass  # Invalid values still fail source-schema validation.
            definition = self._slot_definitions.get(name)
            if definition is None or definition.type != "enum" or not isinstance(value, str):
                continue
            choices = {
                choice.casefold(): choice
                for choice in definition.values or []
                if isinstance(choice, str)
            }
            if value.casefold() in choices:
                decision.slots[name] = choices[value.casefold()]
            elif name == "region" and "other" in choices:
                # The source prices only named regions plus 'other', while its city
                # enum has more locations. This is domain normalization, not routing.
                city = self._slot_definitions.get("city")
                cities = {str(item).casefold() for item in city.values or []} if city else set()
                if value.casefold() in cities:
                    decision.slots[name] = choices["other"]

    def _validate_decision(self, decision: RouterDecision, state: DialogState) -> None:
        selections = [item.scenario_id for item in decision.scenarios]
        alternatives = [item.scenario_id for item in decision.alternatives]
        if any(
            self.catalog.get_by_id(item) is None and self.catalog.get_system_intent(item) is None
            for item in selections + alternatives
        ):
            raise RouterOutputError("unknown_scenario")
        if len(alternatives) > 2 or len(alternatives) != len(set(alternatives)):
            raise RouterOutputError("alternatives")
        if set(selections) & set(alternatives):
            raise RouterOutputError("alternatives")
        if (
            any(self.catalog.get_system_intent(item) for item in selections)
            and len(selections) != 1
        ):
            raise RouterOutputError("system_mix")
        if {segment.scenario_id for segment in decision.segments} != set(selections):
            raise RouterOutputError("segment_coverage")
        if decision.scope_kind != "none" and selections != ["SYS_OUT_OF_SCOPE"]:
            raise RouterOutputError("scope_contract")
        if decision.is_continuation and (
            state.active_scenario is None or selections != [state.active_scenario]
        ):
            raise RouterOutputError("continuation")
        for name, value in decision.slots.items():
            if name == "phone" and isinstance(value, str):
                from app.packs.insurance_manager.data.demo_profile import normalize_phone

                try:
                    decision.slots[name] = normalize_phone(value)
                except ValueError:
                    pass  # Invalid values still fail source-schema validation.
            definition = self._slot_definitions.get(name)
            if definition is None:
                raise RouterOutputError("unknown_slot")
            if not _valid_slot_value(definition, value):
                raise RouterOutputError("invalid_slot")


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
