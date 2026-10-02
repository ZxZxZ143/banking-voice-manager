import logging
from datetime import UTC, datetime
from time import perf_counter

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator

from app.agent.errors import RouterConfigurationError, RouterError
from app.core.contracts import Contract, Language
from app.dialog.message import MessageResult, SessionClosedError
from app.dialog.store import SessionCapacityError
from app.events.models import ConversationEvent
from app.events.response import response_events

router = APIRouter(prefix="/api", tags=["message"])
logger = logging.getLogger(__name__)


class WebTransportMetadata(Contract):
    language: Language | None = None
    stt_after_commit_ms: float | None = Field(default=None, ge=0, le=150000, allow_inf_nan=False)


class MessageRequest(Contract):
    session_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=10000)
    transport: WebTransportMetadata | None = None

    @field_validator("session_id", "text")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank")
        return value


@router.post("/message", response_model=MessageResult)
async def message(payload: MessageRequest, request: Request):
    store = request.app.state.event_store
    if any(event.channel != "web" for event in store.get_by_session(payload.session_id)):
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "channel_conflict",
                    "message": "Session belongs to another channel",
                }
            },
        )
    started_at = datetime.now(UTC).isoformat()
    started = perf_counter()
    try:
        result = await request.app.state.services.messages.process(payload.session_id, payload.text)
        agent_ms = (perf_counter() - started) * 1000
        value = result.model_dump(mode="json")
        turn = value.get("trace", {}).get("turn", 1)
        metadata = {"source": "api/message", "turn": turn}
        try:
            if turn == 1 and not store.get_by_session(payload.session_id):
                store.append(
                    ConversationEvent(
                        session_id=payload.session_id,
                        channel="web",
                        event_type="session.started",
                        timestamp=started_at,
                        metadata=metadata,
                    )
                )
            client_latency = (
                {"client_stt_final_ms": payload.transport.stt_after_commit_ms}
                if payload.transport and payload.transport.stt_after_commit_ms is not None
                else None
            )
            store.append(
                ConversationEvent(
                    session_id=payload.session_id,
                    channel="web",
                    event_type="transcript.final",
                    timestamp=started_at,
                    text=payload.text,
                    language=payload.transport.language if payload.transport else None,
                    latency=client_latency,
                    metadata=metadata,
                )
            )
            for event in response_events(payload.session_id, "web", value):
                event = event.model_copy(update={"metadata": metadata})
                store.append(event)
                if event.event_type == "agent.response":
                    store.update_latency(event.id, {"agent_ms": agent_ms})
            if value["conversation_status"] in ("ended", "handoff"):
                store.append(
                    ConversationEvent(
                        session_id=payload.session_id,
                        channel="web",
                        event_type="conversation.ended",
                        conversation_status=value["conversation_status"],
                        metadata=metadata,
                    )
                )
        except Exception as error:
            logger.warning("web event_recording_failed exception_type=%s", type(error).__name__)
        return result
    except RouterError as exc:
        status = 503 if isinstance(exc, RouterConfigurationError) else 502
        if exc.code == "router_timeout":
            status = 504
        return JSONResponse(
            status_code=status, content={"error": {"code": exc.code, "message": exc.message}}
        )
    except SessionClosedError as exc:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "session_closed", "message": str(exc)}},
        )
    except SessionCapacityError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "session_capacity", "message": str(exc)}},
        )
