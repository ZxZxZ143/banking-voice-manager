from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.conversation.status import ConversationStatus


class AgentProcessor(Protocol):
    async def process(
        self, session_id: str, text: str, *, channel: str
    ) -> BaseModel | dict[str, Any]: ...


class AgentResponse(BaseModel):
    """Minimal response envelope; no finance/risk schema imposed by the channel."""

    model_config = ConfigDict(extra="allow")
    session_id: str | None = None
    response_text: str = Field(min_length=1)
    conversation_status: ConversationStatus
    routing: Any = None
    risk: Any = None
    state: Any = None
    trace: Any = None

    @field_validator("response_text")
    @classmethod
    def nonblank_reply(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("Agent reply must not be blank")
        return text


class AgentBridge:
    def __init__(self, messages: AgentProcessor):
        self.messages = messages

    async def respond(self, session_id: str, text: str) -> AgentResponse:
        # The same MessageService.process used by POST /api/message, without HTTP loopback.
        value = await self.messages.process(session_id, text, channel="voice")
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        response = AgentResponse.model_validate(value)
        if response.session_id is not None and response.session_id != session_id:
            raise ValueError("Agent returned a different session ID")
        return response

    async def close(self, session_id: str) -> None:
        # Current MessageService owns canonical terminal events. Minimal unit fixtures
        # may omit persistence; production always composes the current service.
        if close := getattr(self.messages, "end_session", None):
            await close(session_id)
