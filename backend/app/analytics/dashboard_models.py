"""Safe persisted read models consumed by the supervisor dashboard."""

from typing import Literal

from pydantic import AwareDatetime, Field

from app.analytics.models import AssistantId, Channel, ConversationEvent, EventQuery, Source
from app.conversation.status import ConversationStatus
from app.core.contracts import Contract
from app.risk.models import RiskSignal

ObservedRisk = Literal["unknown", "none", "low", "medium", "high", "critical"]


class DashboardQuery(EventQuery):
    observed_risk: ObservedRisk | None = None
    active: bool | None = None
    as_of: AwareDatetime | None = None


class RankedCount(Contract):
    key: str
    count: int = Field(ge=0)


class MetricAverage(Contract):
    average_ms: float | None = None
    samples: int = 0


class ConversationSessionSummary(Contract):
    session_id: str
    channel: Channel
    source: Source | Literal["mixed"]
    started_at: AwareDatetime | None
    ended_at: AwareDatetime | None
    latest_event_at: AwareDatetime
    assistant_sequence: list[AssistantId]
    latest_assistant: AssistantId
    scenarios: list[AssistantId]
    primary_scenario: AssistantId
    last_scenario: AssistantId
    scenario_ids: list[str]
    risk_level: ObservedRisk
    risk_signals: list[RiskSignal]
    handoff: bool
    completed: bool
    active: bool
    status: ConversationStatus
    turn_count: int
    total_duration_ms: float | None
    result_types: list[Literal["insurance_result", "sales_lead", "fraud_case"]]
    results: list[ConversationEvent]
    partial_history: bool
    # Not stored in Stage 5A. Explicit nulls avoid inventing unavailable metrics.
    language: None = None
    clarification_count: None = None
    average_agent_ms: None = None
    average_tts_ms: None = None
    latest_latency: dict[str, float] = Field(default_factory=dict)


class SessionPage(Contract):
    sessions: list[ConversationSessionSummary]
    total: int
    limit: int
    offset: int
    next_offset: int | None


class JourneyStage(Contract):
    id: str
    session_id: str
    timestamp: AwareDatetime
    event_type: str
    scenario: AssistantId
    scenario_id: str | None
    action: list[str]
    source_event_id: str
    channel: Channel
    clarification: Literal[False] = False
    handoff: bool
    completion: bool


class JourneyPage(Contract):
    stages: list[JourneyStage]
    total: int
    limit: int
    offset: int
    next_offset: int | None


class DashboardSessionDetail(Contract):
    summary: ConversationSessionSummary
    timeline: list[ConversationEvent]
    journey: list[JourneyStage]
    total: int
    limit: int
    offset: int
    next_offset: int | None


class RiskAnalytics(Contract):
    levels: dict[ObservedRisk, int]
    high_risk_sessions: int
    top_signals: list[RankedCount]
    high_risk_scenarios: list[RankedCount]
    fraud_case_types: list[RankedCount]


class DashboardOverview(Contract):
    total_sessions: int
    active_sessions: int
    recent_sessions: int
    sessions_by_channel: dict[Channel, int]
    sessions_by_scenario: list[RankedCount]
    conversation_statuses: dict[ConversationStatus, int]
    handoff_count: int
    handoff_rate: float
    risk: RiskAnalytics
    sales_outcomes: list[RankedCount]
    insurance_completed: int
    sources: dict[Source | Literal["mixed"], int]
    retained_events: int
    latency: dict[str, MetricAverage]
    clarification_count: None = None
    clarification_rate: None = None
    capacity: None = None
    evicted_events: None = None


class AnomalyWindow(Contract):
    current_from: AwareDatetime
    current_to: AwareDatetime
    baseline_from: AwareDatetime
    baseline_to: AwareDatetime
    window_seconds: int
    baseline_windows: int


class Anomaly(Contract):
    id: str
    detected_at: AwareDatetime
    metric: Literal["risk_signal", "risk_level", "fraud_case", "operator_handoff"]
    key: str
    source: Source
    current_count: int
    baseline_count: int
    baseline_expected_count: float
    ratio: float
    severity: Literal["medium", "high"]
    window: AnomalyWindow
    explanation: str
    partial_history: Literal[False] = False


class AnomalyPage(Contract):
    anomalies: list[Anomaly]
    history_status: Literal["ready", "insufficient_history"]
    as_of: AwareDatetime
    total: int
    limit: int
    offset: int
    next_offset: int | None
