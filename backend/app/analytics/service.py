"""Deterministic retained-event analytics, journey and count-based anomaly signals."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from app.analytics.models import (
    AnalyticsOverview,
    Anomaly,
    ConversationSessionSummary,
    JourneyEvent,
    MetricAverage,
    RankedCount,
    RiskAnalytics,
    SessionDetail,
)
from app.events.normalize import (
    METRICS,
    RISK_LEVELS,
    instant,
    risk_details,
    scenario_keys,
    turn_latencies,
)


def ranked(counts) -> list[RankedCount]:
    return [
        RankedCount(key=key, count=count)
        for key, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def averages(samples) -> dict[str, MetricAverage]:
    result = {}
    for metric in METRICS:
        values = [sample[metric] for sample in samples if metric in sample]
        result[metric] = MetricAverage(
            average_ms=sum(values) / len(values) if values else None, samples=len(values)
        )
    return result


class AnalyticsService:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings

    def get_journey(self, session_id: str) -> list[JourneyEvent]:
        journey = []
        for event in self.store.get_by_session(session_id):
            if event.event_type not in (
                "scenario.selected",
                "clarification.requested",
                "handoff.requested",
                "conversation.ended",
            ):
                continue
            for scenario in scenario_keys(event) or [None]:
                stage = JourneyEvent(
                    id=str(uuid5(NAMESPACE_URL, event.id + ":" + str(scenario))),
                    session_id=session_id,
                    timestamp=event.timestamp,
                    scenario=scenario,
                    action=event.action,
                    source_event_id=event.id,
                    channel=event.channel,
                    clarification=event.event_type == "clarification.requested",
                    handoff=event.event_type == "handoff.requested",
                    completion=event.event_type == "conversation.ended"
                    and ((event.metadata or {}).get("phone_status") or event.conversation_status)
                    == "ended",
                )
                if (
                    journey
                    and event.event_type == "scenario.selected"
                    and journey[-1].scenario == scenario
                    and journey[-1].action == stage.action
                    and not (
                        journey[-1].clarification or journey[-1].handoff or journey[-1].completion
                    )
                ):
                    continue
                journey.append(stage)
        return journey

    def summary(self, events, now: datetime) -> ConversationSessionSummary:
        first = events[0]
        starts = [e.timestamp for e in events if e.event_type == "session.started"]
        ends = [e for e in events if e.event_type == "conversation.ended"]
        selected = [
            key for e in events if e.event_type == "scenario.selected" for key in scenario_keys(e)
        ]
        responses = [e for e in events if e.event_type == "agent.response"]
        risks = [risk_details(e.risk) for e in responses]
        level = max((r[0] for r in risks), key=RISK_LEVELS.index, default="unknown")
        samples = turn_latencies(events)
        latency = averages(samples)
        latest_at = max((e.timestamp for e in events), key=instant)
        status = next(
            (e.conversation_status for e in reversed(events) if e.conversation_status),
            "active" if starts else "unknown",
        )
        if ends:
            status = (
                (ends[-1].metadata or {}).get("phone_status")
                or ends[-1].conversation_status
                or "closed"
            )
        ended_at = ends[-1].timestamp if ends else None
        started_at = min(starts, key=instant) if starts else None
        duration = (
            (instant(ended_at) - instant(started_at)).total_seconds() * 1000
            if ended_at and started_at
            else None
        )
        metadata = {
            key: value
            for e in events
            for key, value in (e.metadata or {}).items()
            if key in ("provider", "call_uuid", "call_id", "call_sid", "stream_sid", "demo")
        }
        completed = bool(ends and status == "ended")
        return ConversationSessionSummary(
            session_id=first.session_id,
            channel=first.channel,
            started_at=started_at,
            ended_at=ended_at,
            latest_event_at=latest_at,
            language=next((e.language for e in reversed(events) if e.language), None),
            scenarios=list(dict.fromkeys(selected)),
            primary_scenario=ranked(Counter(selected))[0].key if selected else None,
            last_scenario=selected[-1] if selected else None,
            risk_level=level,
            risk_signals=sorted({signal for _, signals in risks for signal in signals}),
            latest_risk=responses[-1].risk if responses else None,
            clarification_count=sum(e.event_type == "clarification.requested" for e in events),
            handoff=any(e.event_type == "handoff.requested" or e.handoff is True for e in events),
            completed=completed,
            active=bool(
                starts
                and not ends
                and status not in ("ended", "handoff")
                and now - timedelta(minutes=5) <= instant(latest_at) <= now
            ),
            status=status,
            turn_count=len(responses),
            total_duration_ms=duration if duration is not None and duration >= 0 else None,
            average_agent_ms=latency["agent_ms"].average_ms,
            average_tts_ms=latency["tts_ms"].average_ms,
            latest_latency=samples[-1] if samples else {},
            provider_metadata=metadata,
            partial_history=not bool(starts),
        )

    def sessions(
        self,
        *,
        channel=None,
        scenario=None,
        risk_level=None,
        from_time=None,
        to_time=None,
        session_id=None,
        active=None,
        limit=None,
        now=None,
    ):
        now = now or datetime.now(UTC)
        groups = defaultdict(list)
        # Filter session membership by matching event time, then derive from all retained history.
        eligible = {e.session_id for e in self.store.list(from_time=from_time, to_time=to_time)}
        for event in self.store.list():
            if event.session_id in eligible:
                groups[event.session_id].append(event)
        results = [self.summary(events, now) for events in groups.values()]
        results = [
            s
            for s in results
            if (channel is None or s.channel == channel)
            and (scenario is None or scenario in s.scenarios)
            and (risk_level is None or s.risk_level == risk_level)
            and (session_id is None or s.session_id == session_id)
            and (active is None or s.active == active)
        ]
        results.sort(key=lambda s: (-instant(s.latest_event_at).timestamp(), s.session_id))
        return results[:limit]

    def detail(self, session_id):
        sessions = self.sessions(session_id=session_id)
        if not sessions:
            return None
        return SessionDetail(
            summary=sessions[0],
            timeline=self.store.get_by_session(session_id),
            journey=self.get_journey(session_id),
        )

    def risk(self, sessions):
        return RiskAnalytics(
            levels={level: sum(s.risk_level == level for s in sessions) for level in RISK_LEVELS},
            high_risk_sessions=sum(s.risk_level in ("high", "critical") for s in sessions),
            top_signals=ranked(Counter(signal for s in sessions for signal in s.risk_signals)),
            high_risk_scenarios=ranked(
                Counter(
                    key
                    for s in sessions
                    if s.risk_level in ("high", "critical")
                    for key in s.scenarios
                )
            ),
        )

    def overview(self, **filters):
        sessions = self.sessions(**filters)
        now = datetime.now(UTC)
        samples = [
            sample
            for s in sessions
            for sample in turn_latencies(self.store.get_by_session(s.session_id))
        ]
        count = len(sessions)
        return AnalyticsOverview(
            total_sessions=count,
            active_sessions=sum(s.active for s in sessions),
            recent_sessions=sum(
                now - timedelta(minutes=5) <= instant(s.latest_event_at) <= now for s in sessions
            ),
            sessions_by_channel={
                c: sum(s.channel == c for s in sessions) for c in ("web", "phone")
            },
            sessions_by_scenario=ranked(Counter(key for s in sessions for key in s.scenarios)),
            conversation_statuses=dict(sorted(Counter(s.status for s in sessions).items())),
            clarification_count=sum(s.clarification_count for s in sessions),
            clarification_rate=sum(s.clarification_count > 0 for s in sessions) / count
            if count
            else 0,
            handoff_count=sum(s.handoff for s in sessions),
            handoff_rate=sum(s.handoff for s in sessions) / count if count else 0,
            risk=self.risk(sessions),
            latency=averages(samples),
            retained_events=len(self.store.list()),
            capacity=self.store.max_events,
            evicted_events=self.store.evicted_events,
        )

    def anomalies(self, *, now=None, channel=None, scenario=None, risk_level=None, limit=None):
        now = now or datetime.now(UTC)
        seconds = self.settings.analytics_window_seconds
        windows = self.settings.analytics_baseline_windows
        current_start, baseline_start = (
            now - timedelta(seconds=seconds),
            now - timedelta(seconds=seconds * (windows + 1)),
        )
        counts = [Counter(), Counter()]
        for event in self.store.list(channel=channel, risk_level=risk_level):
            at = instant(event.timestamp)
            bucket = (
                0
                if current_start <= at <= now
                else 1
                if baseline_start <= at < current_start
                else None
            )
            if bucket is None:
                continue
            if event.event_type == "scenario.selected":
                for key in scenario_keys(event):
                    if scenario is None or scenario == key:
                        counts[bucket][("scenario", key)] += 1
            if event.event_type == "agent.response" and (
                scenario is None or scenario in scenario_keys(event)
            ):
                for key in risk_details(event.risk)[1]:
                    counts[bucket][("risk_signal", key)] += 1
        result = []
        for (metric, key), current in sorted(counts[0].items()):
            baseline = counts[1][(metric, key)]
            expected = baseline / windows
            ratio = current / expected if expected else None
            if current < self.settings.analytics_min_volume or (
                ratio is not None and ratio < self.settings.analytics_anomaly_multiplier
            ):
                continue
            severity = (
                "high"
                if ratio is not None and ratio >= 6
                else "medium"
                if ratio is None or ratio >= 4
                else "low"
            )
            result.append(
                Anomaly(
                    id=str(uuid5(NAMESPACE_URL, f"{metric}:{key}:{current_start.isoformat()}")),
                    detected_at=now.isoformat(),
                    metric=metric,
                    key=key,
                    current_count=current,
                    baseline_count=baseline,
                    baseline_expected_count=expected,
                    ratio=ratio,
                    severity=severity,
                    window={
                        "current_from": current_start.isoformat(),
                        "current_to": now.isoformat(),
                        "baseline_from": baseline_start.isoformat(),
                        "baseline_to": current_start.isoformat(),
                        "seconds": seconds,
                        "baseline_windows": windows,
                    },
                    explanation=(
                        f"Observed abnormal increase: {current} events in the current window; "
                        f"historical mean {expected:g} per equivalent window. "
                        "This count signal does not establish cause or intent."
                    ),
                    partial_history=self.store.evicted_events > 0,
                )
            )
        result.sort(key=lambda a: (-a.current_count, a.metric, a.key))
        return result[:limit]
