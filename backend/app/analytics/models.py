"""Typed dashboard contracts derived from retained canonical events."""

from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from app.core.channels import Channel
from app.events.models import ConversationEvent

RiskLevel = Literal["unknown", "low", "medium", "high", "critical"]


class MetricAverage(BaseModel):
    average_ms: float | None = None
    samples: int = 0


class RankedCount(BaseModel):
    key: str
    count: int


class ConversationSessionSummary(BaseModel):
    session_id: str
    channel: Channel
    started_at: str | None
    ended_at: str | None = None
    latest_event_at: str
    language: str | None = None
    scenarios: list[str] = Field(default_factory=list)
    primary_scenario: str | None = None
    last_scenario: str | None = None
    risk_level: RiskLevel = "unknown"
    risk_signals: list[str] = Field(default_factory=list)
    latest_risk: JsonValue | None = None
    clarification_count: int = 0
    handoff: bool = False
    completed: bool = False
    active: bool = False
    status: str = "unknown"
    turn_count: int = 0
    total_duration_ms: float | None = None
    average_agent_ms: float | None = None
    average_tts_ms: float | None = None
    latest_latency: dict[str, float] = Field(default_factory=dict)
    provider_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    partial_history: bool = False


class JourneyEvent(BaseModel):
    id: str
    session_id: str
    timestamp: str
    scenario: str | None = None
    action: JsonValue | None = None
    source_event_id: str
    channel: Channel
    clarification: bool = False
    handoff: bool = False
    completion: bool = False


class SessionDetail(BaseModel):
    summary: ConversationSessionSummary
    timeline: list[ConversationEvent]
    journey: list[JourneyEvent]


class RiskAnalytics(BaseModel):
    levels: dict[RiskLevel, int]
    high_risk_sessions: int
    top_signals: list[RankedCount]
    high_risk_scenarios: list[RankedCount]


class AnalyticsOverview(BaseModel):
    total_sessions: int
    active_sessions: int
    recent_sessions: int
    sessions_by_channel: dict[Channel, int]
    sessions_by_scenario: list[RankedCount]
    conversation_statuses: dict[str, int]
    clarification_count: int
    clarification_rate: float
    handoff_count: int
    handoff_rate: float
    risk: RiskAnalytics
    latency: dict[str, MetricAverage]
    retained_events: int
    capacity: int
    evicted_events: int


class Anomaly(BaseModel):
    id: str
    detected_at: str
    metric: Literal["scenario", "risk_signal"]
    key: str
    current_count: int
    baseline_count: int
    baseline_expected_count: float
    ratio: float | None
    severity: Literal["low", "medium", "high"]
    window: dict[str, str | int]
    explanation: str
    partial_history: bool
