from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import ConfigDict, Field, SerializeAsAny

from app.conversation.status import ConversationStatus
from app.core.contracts import Contract, Language
from app.tracing.models import TraceRecord

ContextLifecycle = Literal["inactive", "active", "suspended", "resumed", "completed"]


class InteractionMode(StrEnum):
    REACTIVE = "reactive"
    CONSULTATIVE = "consultative"
    PROACTIVE = "proactive"


class ScenarioManifest(Contract):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    interaction_mode: InteractionMode
    supported_languages: tuple[Language, ...]
    output_schema: str = Field(min_length=1, max_length=100)


class GlobalConversationContext(Contract):
    session_id: str = Field(min_length=1, max_length=128)
    turn_number: int = Field(default=0, ge=0)
    language: Language | None = None
    channel: Literal["text", "voice"] = "text"
    conversation_status: ConversationStatus = "active"


class ScenarioResult(Contract):
    status: ConversationStatus
    completed: bool
    handoff: bool


@dataclass
class PackTurn:
    context: Contract
    language: Language | None
    response_text: str
    routing: Contract
    public_state: Contract
    trace: TraceRecord
    result: ScenarioResult


class ScenarioPack(Protocol):
    manifest: ScenarioManifest
    state_schema: type[Contract]
    output_schema: type[ScenarioResult]

    @property
    def prompt(self) -> str: ...

    @property
    def knowledge(self) -> object: ...

    @property
    def tools(self) -> object: ...

    @property
    def policies(self) -> object: ...

    @property
    def completion_rules(self) -> str: ...

    def new_context(self) -> Contract: ...

    async def handle_turn(
        self, text: str, global_context: GlobalConversationContext, context: Contract
    ) -> PackTurn: ...


class ScenarioContextEntry(Contract):
    lifecycle: ContextLifecycle = "inactive"
    state: SerializeAsAny[Contract]
    result: SerializeAsAny[ScenarioResult] | None = None


class ConversationContext(Contract):
    global_context: GlobalConversationContext
    active_scenario_pack: str | None = None
    scenario_contexts: dict[str, ScenarioContextEntry] = Field(default_factory=dict)
