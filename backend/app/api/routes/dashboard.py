"""Additive persisted dashboard contract; legacy event endpoints stay intact."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import AwareDatetime, ValidationError

from app.analytics.dashboard_models import (
    AnomalyPage,
    DashboardOverview,
    DashboardQuery,
    DashboardSessionDetail,
    JourneyPage,
    ObservedRisk,
    RankedCount,
    RiskAnalytics,
    SessionPage,
)
from app.analytics.models import AssistantId, Channel, Source
from app.api.routes.analytics import AnalyticsErrorResponse, read

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
    risk_level: ObservedRisk | None = None,
    channel: Channel | None = None,
    source: Source | None = None,
    query_session_id: Annotated[
        str | None, Query(alias="session_id", min_length=1, max_length=128)
    ] = None,
    active: bool | None = None,
    as_of: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
) -> DashboardQuery:
    try:
        return DashboardQuery(
            from_time=from_time,
            to_time=to_time,
            assistant_id=assistant_id,
            observed_risk=risk_level,
            channel=channel,
            source=source,
            session_id=query_session_id,
            active=active,
            as_of=as_of,
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
                }
            ]
        ) from None


QueryDependency = Annotated[DashboardQuery, Depends(filters)]
SessionId = Annotated[str, Path(min_length=1, max_length=128)]


def session_filters(
    source: Source | None = None,
    as_of: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
) -> DashboardQuery:
    return DashboardQuery(source=source, as_of=as_of, limit=limit, offset=offset)


SessionQuery = Annotated[DashboardQuery, Depends(session_filters)]


@router.get("/overview", response_model=DashboardOverview)
def overview(request: Request, query: QueryDependency):
    return read(request, request.app.state.services.analytics.overview, query)


@router.get("/sessions", response_model=SessionPage)
def sessions(request: Request, query: QueryDependency):
    return read(request, request.app.state.services.analytics.sessions, query)


@router.get(
    "/sessions/{session_id}/detail",
    response_model=DashboardSessionDetail,
    responses={404: {"model": AnalyticsErrorResponse}},
)
def detail(request: Request, session_id: SessionId, query: SessionQuery):
    result = read(request, request.app.state.services.analytics.detail, session_id, query)
    if result is None:
        raise HTTPException(
            404,
            detail={
                "code": "analytics_session_not_found",
                "message": "Analytics session not found",
            },
        )
    return result


@router.get("/sessions/{session_id}/journey", response_model=JourneyPage)
def journey(request: Request, session_id: SessionId, query: SessionQuery):
    return read(request, request.app.state.services.analytics.journey, session_id, query)


@router.get("/risk", response_model=RiskAnalytics)
def risk(request: Request, query: QueryDependency):
    return read(request, request.app.state.services.analytics.risk, query)


@router.get("/scenarios", response_model=list[RankedCount])
def scenarios(request: Request, query: QueryDependency):
    return read(request, request.app.state.services.analytics.scenarios, query)


@router.get("/anomalies", response_model=AnomalyPage)
def anomalies(request: Request, query: QueryDependency):
    if query.from_time or query.to_time or query.active is not None or query.observed_risk:
        raise HTTPException(
            422,
            detail={
                "code": "analytics_invalid_anomaly_filter",
                "message": "Anomalies use as_of and equal rolling windows",
            },
        )
    return read(request, request.app.state.services.analytics.anomalies, query)
