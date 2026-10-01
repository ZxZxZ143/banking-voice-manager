"""Bounded structured transport for new packs and the conditional platform selector."""

import asyncio
import json

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
from app.core.contracts import Contract


class StructuredAgent:
    def __init__(self, settings, name: str, instructions: str, output_schema: type[Contract]):
        self.settings = settings
        self.name = name
        self.instructions = instructions
        self.output_schema = output_schema

    async def run(self, payload: dict) -> Contract:
        key, model = self.settings.openai_api_key, self.settings.openai_router_model
        if not key or not key.get_secret_value().strip() or not model or not model.strip():
            raise RouterConfigurationError()
        agent = Agent(
            name=self.name,
            instructions=self.instructions,
            model=model,
            output_type=self.output_schema,
            tools=[],
            handoffs=[],
            model_settings=ModelSettings(
                temperature=self.settings.router_temperature,
                max_tokens=self.settings.router_max_output_tokens,
                store=False,
                retry=ModelRetrySettings(max_retries=0),
            ),
        )
        try:
            async with asyncio.timeout(self.settings.router_timeout_seconds):
                async with AsyncOpenAI(
                    api_key=key.get_secret_value(),
                    max_retries=0,
                    timeout=self.settings.router_timeout_seconds,
                ) as client:
                    agent.model = OpenAIResponsesModel(model=model.strip(), openai_client=client)
                    result = await Runner.run(
                        agent,
                        input=json.dumps(payload, ensure_ascii=False),
                        max_turns=1,
                        run_config=RunConfig(
                            tracing_disabled=True, trace_include_sensitive_data=False
                        ),
                    )
            if type(result.final_output) is not self.output_schema:
                raise RouterOutputError()
            return result.final_output
        except (TimeoutError, APITimeoutError, ModelTimeoutError) as exc:
            raise RouterProviderError(timeout=True) from exc
        except APIError as exc:
            raise RouterProviderError() from exc
        except (
            ValidationError,
            ValueError,
            ModelBehaviorError,
            ModelRefusalError,
            MaxTurnsExceeded,
        ) as exc:
            raise RouterOutputError() from exc
