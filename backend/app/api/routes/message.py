import logging
from datetime import UTC, datetime
from time import perf_counter

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator

from app.agent.errors import (
    ROUTER_VALIDATION_REASONS,
    RouterConfigurationError,
    RouterError,
    RouterOutputError,
    RouterProviderError,
)
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
        root = exc
        seen = {id(root)}
        while root.__cause__ is not None and id(root.__cause__) not in seen:
            root = root.__cause__
            seen.add(id(root))
        layer = "router_configuration"
        if isinstance(exc, RouterProviderError):
            layer = "router_timeout" if exc.code == "router_timeout" else "router_provider"
        elif isinstance(exc, RouterOutputError):
            layer = "router_output_validation"
            traceback = exc.__traceback__
            while traceback is not None and traceback.tb_next is not None:
                traceback = traceback.tb_next
            if traceback is not None and traceback.tb_frame.f_code.co_filename.replace(
                "\\", "/"
            ).endswith("/dialog/message.py"):
                layer = "decision_policy_validation"
        reason = getattr(exc, "validation_reason", None)
        reason = reason if reason in ROUTER_VALIDATION_REASONS else "none"
        # SDK/Pydantic exception strings can include prompts, slot values, headers and keys.
        # Preserve the real cause class and safe category; never serialize the raw cause.
        fields = {
            "error_code": exc.code,
            "failure_layer": layer,
            "exception_type": type(exc).__name__,
            "root_exception_type": type(root).__name__,
            "safe_message": exc.message,
            "root_message": "details withheld; see failure_layer and validation_reason",
            "validation_reason": reason,
            "http_status": status,
            "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        }
        provider_status = getattr(root, "status_code", None)
        if isinstance(provider_status, int) and 100 <= provider_status <= 599:
            fields["provider_status"] = provider_status
        logger.warning("web agent_turn_failed %s", fields, extra=fields)
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
