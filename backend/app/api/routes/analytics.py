"""Bounded read-only integration contract, using the existing same-origin proxy."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import AwareDatetime, ValidationError

from app.analytics.models import (
    AnalyticsSummary,
    AssistantId,
    Channel,
    EventPage,
    EventQuery,
    EventType,
    SessionEvents,
    Source,
)
from app.core.contracts import Contract, ErrorDetail
from app.risk.models import RiskLevel


class AnalyticsErrorResponse(Contract):
    detail: ErrorDetail


router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
    responses={
        503: {"model": AnalyticsErrorResponse, "description": "Analytics storage unavailable"}
    },
)


def filters(
    from_time: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to_time: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    assistant_id: AssistantId | None = None,
    event_type: EventType | None = None,
    risk_level: RiskLevel | None = None,
    channel: Channel | None = None,
    source: Source | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
) -> EventQuery:
    try:
        return EventQuery(
            from_time=from_time,
            to_time=to_time,
            assistant_id=assistant_id,
            event_type=event_type,
            risk_level=risk_level,
            channel=channel,
            source=source,
            limit=limit,
            offset=offset,
        )
    except ValidationError:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ["query", "from"],
                    "msg": "from must be before to",
                    "input": str(from_time),
                },
            ]
        ) from None


def read(request: Request, operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except Exception:
        # Log fixed codes only: SQL exceptions can include host paths or payloads.
        request.app.state.services.events.failure("storage_unavailable")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "analytics_storage_unavailable",
                "message": "Analytics storage unavailable",
            },
        ) from None


@router.get("/events", response_model=EventPage)
def events(request: Request, query: Annotated[EventQuery, Depends(filters)]):
    return read(request, request.app.state.services.events.store.query_events, query)


@router.get("/summary", response_model=AnalyticsSummary)
def summary(request: Request, query: Annotated[EventQuery, Depends(filters)]):
    return read(request, request.app.state.services.events.store.summary, query)


@router.get("/sessions/{session_id}", response_model=SessionEvents)
def session_events(
    request: Request,
    session_id: Annotated[str, Path(min_length=1, max_length=128)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
):
    store = request.app.state.services.events.store
    page = read(request, store.get_session_events, session_id, limit=limit, offset=offset)
    first = page.events[0] if page.events and offset == 0 else None
    if first is None and page.total:
        first = read(request, store.get_session_events, session_id, limit=1).events[0]
    return SessionEvents(
        **page.model_dump(), session_id=session_id, channel=first.channel if first else None
    )
