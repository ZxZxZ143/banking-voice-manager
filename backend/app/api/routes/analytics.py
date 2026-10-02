"""Opt-in supervisor polling API; never accepts client business events."""

from datetime import datetime
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request

from app.analytics.models import (
    AnalyticsOverview,
    Anomaly,
    ConversationSessionSummary,
    JourneyEvent,
    RankedCount,
    RiskAnalytics,
    RiskLevel,
    SessionDetail,
)
from app.core.channels import Channel

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


def service(request: Request, authorization: Annotated[str | None, Header()] = None):
    settings = request.app.state.settings
    token = settings.analytics_api_token
    if not settings.analytics_enabled or not token or not token.get_secret_value().strip():
        raise HTTPException(503, "Supervisor analytics is not configured")
    if (
        not authorization
        or len(authorization) > 8192
        or not compare_digest(
            authorization.encode(), ("Bearer " + token.get_secret_value()).encode()
        )
    ):
        raise HTTPException(403, "Supervisor authorization required")
    return request.app.state.analytics


def filters(
    channel: Channel | None = None,
    scenario: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    risk_level: RiskLevel | None = None,
    from_time: Annotated[datetime | None, Query(alias="from")] = None,
    to_time: Annotated[datetime | None, Query(alias="to")] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
):
    if any(value is not None and value.tzinfo is None for value in (from_time, to_time)) or (
        from_time and to_time and from_time > to_time
    ):
        raise HTTPException(422, "Use timezone-aware timestamps and an ordered time range")
    return dict(
        channel=channel,
        scenario=scenario,
        risk_level=risk_level,
        from_time=from_time,
        to_time=to_time,
        session_id=session_id,
    )


@router.get("/overview", response_model=AnalyticsOverview)
def overview(analytics=Depends(service), query=Depends(filters)):
    return analytics.overview(**query)


@router.get("/sessions", response_model=list[ConversationSessionSummary])
def sessions(
    analytics=Depends(service),
    query=Depends(filters),
    active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    return analytics.sessions(**query, active=active, limit=limit)


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def session(
    session_id: Annotated[str, Path(min_length=1, max_length=128)], analytics=Depends(service)
):
    detail = analytics.detail(session_id)
    if detail is None:
        raise HTTPException(404, "Session not retained")
    return detail


@router.get("/sessions/{session_id}/journey", response_model=list[JourneyEvent])
def journey(
    session_id: Annotated[str, Path(min_length=1, max_length=128)], analytics=Depends(service)
):
    if analytics.detail(session_id) is None:
        raise HTTPException(404, "Session not retained")
    return analytics.get_journey(session_id)


@router.get("/scenarios", response_model=list[RankedCount])
def scenarios(analytics=Depends(service), query=Depends(filters)):
    return analytics.overview(**query).sessions_by_scenario


@router.get("/risk", response_model=RiskAnalytics)
def risk(analytics=Depends(service), query=Depends(filters)):
    return analytics.risk(analytics.sessions(**query))


@router.get("/anomalies", response_model=list[Anomaly])
def anomalies(
    analytics=Depends(service),
    channel: Channel | None = None,
    scenario: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    risk_level: RiskLevel | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    return analytics.anomalies(
        channel=channel, scenario=scenario, risk_level=risk_level, limit=limit
    )
