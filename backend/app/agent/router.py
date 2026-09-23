from typing import Protocol

from agents import Agent

from app.agent.prompts import build_router_instructions
from app.agent.schemas import RouterAgentOutput, RouterDecision
from app.dialog.models import DialogState
from app.scenarios.catalog import ScenarioCatalog


class Router(Protocol):
    async def route(self, text: str, state: DialogState) -> RouterDecision: ...


def build_router_agent(catalog: ScenarioCatalog, model: str) -> Agent:
    """Construct exactly one SDK agent without performing any API calls."""
    if not model.strip():
        raise ValueError("An explicit OPENAI_ROUTER_MODEL is required")
    return Agent(
        name="Voice Router",
        instructions=build_router_instructions(catalog),
        model=model,
        output_type=RouterAgentOutput,
        tools=[],
        handoffs=[],
    )


class RouterAgent:
    """Runner orchestration belongs to Router v1; this foundation never fabricates decisions."""

    def __init__(self, catalog: ScenarioCatalog) -> None:
        self.catalog = catalog

    async def route(self, text: str, state: DialogState) -> RouterDecision:
        raise NotImplementedError(
            "Router execution is not implemented. Connect a bounded Agents SDK Runner in Router v1."
        )
