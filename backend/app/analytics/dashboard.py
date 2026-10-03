"""Deterministic read models, never new stored state or model-generated narratives."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from app.analytics.dashboard_models import (
    Anomaly,
    AnomalyPage,
    AnomalyWindow,
    ConversationSessionSummary,
    DashboardOverview,
    DashboardSessionDetail,
    JourneyPage,
    JourneyStage,
    MetricAverage,
    RankedCount,
    RiskAnalytics,
    SessionPage,
)
from app.analytics.models import EventQuery, EventType
from app.analytics.store import EventStore

LEVELS = ("unknown", "none", "low", "medium", "high", "critical")
RESULTS = {EventType.INSURANCE_RESULT, EventType.SALES_LEAD, EventType.FRAUD_CASE}


def ranked(counts):
    return [
        RankedCount(key=key, count=value)
        for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def pagination(items, query):
    total = len(items)
    end = min(query.offset + query.limit, total)
    return dict(
        total=total,
        limit=query.limit,
        offset=query.offset,
        next_offset=end if end < total else None,
    )


class AnalyticsService:
    def __init__(self, store: EventStore, settings):
        self.store, self.settings = store, settings

    def _events(self, query):
        # One consistent SQLite snapshot through the replaceable store boundary.
        # Only source/session constrain history here; session filters apply to full
        # summaries, preserving terminal/risk context outside the selected time range.
        return self.store.analytics_snapshot(
            EventQuery(source=query.source, session_id=query.session_id)
        )

    @staticmethod
    def session_summary(events, now):
        events = sorted(
            events, key=lambda e: (e.turn_number, e.sequence, e.created_at, str(e.event_id))
        )
        first, last = events[0], events[-1]
        starts = [e for e in events if e.event_type == "conversation_started"]
        terminals = [
            e for e in events if e.event_type in ("operator_handoff", "conversation_ended")
        ]
        assistants = list(dict.fromkeys(e.assistant_id for e in events))
        sequence = []
        for event in events:
            if not sequence or sequence[-1] != event.assistant_id:
                sequence.append(event.assistant_id)
        known = [
            e.risk_level
            for e in events
            if e.event_type == "risk_signal"
            and e.payload.analysis_status == "analyzed"
            and e.risk_level is not None
        ]
        risk = max(known, key=LEVELS.index, default="unknown")
        results = {}
        for event in events:
            if event.event_type in RESULTS:
                results[(event.assistant_id, event.event_type)] = event
        source = {e.source for e in events}
        started = starts[0].created_at if starts else None
        ended = terminals[-1].created_at if terminals else None
        latest = max(e.created_at for e in events)
        return ConversationSessionSummary(
            session_id=first.session_id,
            channel=last.channel,
            source=next(iter(source)) if len(source) == 1 else "mixed",
            started_at=started,
            ended_at=ended,
            latest_event_at=latest,
            assistant_sequence=sequence,
            latest_assistant=last.assistant_id,
            scenarios=assistants,
            primary_scenario=assistants[0],
            last_scenario=last.assistant_id,
            scenario_ids=sorted({e.scenario_id for e in events if e.scenario_id}),
            risk_level=risk,
            risk_signals=sorted(
                {
                    signal
                    for e in events
                    if e.event_type == "risk_signal"
                    for signal in e.risk_signals
                }
            ),
            handoff=any(e.event_type == "operator_handoff" for e in events),
            completed=any(e.event_type == "conversation_ended" for e in events),
            active=not terminals
            and last.conversation_status not in ("ended", "handoff")
            and now - timedelta(minutes=5) <= latest <= now,
            status=last.conversation_status,
            turn_count=max(e.turn_number for e in events),
            total_duration_ms=max(0, (ended - started).total_seconds() * 1000)
            if ended and started
            else None,
            result_types=sorted({e.event_type for e in results.values()}),
            results=list(results.values()),
            partial_history=not bool(starts),
        )

    def _sessions(self, query, events=None):
        now = query.as_of or datetime.now(UTC)
        groups = defaultdict(list)
        for event in self._events(query) if events is None else events:
            groups[event.session_id].append(event)
        sessions = [self.session_summary(events, now) for events in groups.values()]
        sessions = [
            s
            for s in sessions
            if (
                (query.channel is None or s.channel == query.channel)
                and (query.assistant_id is None or query.assistant_id in s.scenarios)
                and (query.observed_risk is None or s.risk_level == query.observed_risk)
                and (query.active is None or s.active == query.active)
                and (query.from_time is None or s.latest_event_at >= query.from_time)
                and (query.to_time is None or s.latest_event_at < query.to_time)
            )
        ]
        return sorted(sessions, key=lambda s: (-s.latest_event_at.timestamp(), s.session_id))

    def sessions(self, query):
        sessions = self._sessions(query)
        return SessionPage(
            sessions=sessions[query.offset : query.offset + query.limit],
            **pagination(sessions, query),
        )

    @staticmethod
    def journey_stages(events):
        stages = []
        for event in sorted(
            events, key=lambda e: (e.turn_number, e.sequence, e.created_at, str(e.event_id))
        ):
            if event.event_type == "conversation_turn":
                continue
            actions = []
            if event.event_type == "insurance_result":
                actions = event.payload.actions
            elif event.event_type == "sales_lead":
                actions = [event.payload.outcome, event.payload.next_action]
            elif event.event_type == "fraud_case":
                actions = [
                    event.payload.case_type,
                    event.payload.case_status,
                    event.payload.recommended_action,
                ]
            elif event.event_type == "risk_signal":
                actions = [*event.risk_signals, event.payload.recommended_action]
            stages.append(
                JourneyStage(
                    id=str(event.event_id),
                    session_id=event.session_id,
                    timestamp=event.created_at,
                    event_type=event.event_type,
                    scenario=event.assistant_id,
                    scenario_id=event.scenario_id,
                    action=actions,
                    source_event_id=str(event.event_id),
                    channel=event.channel,
                    handoff=event.event_type == "operator_handoff",
                    completion=event.event_type == "conversation_ended",
                )
            )
        return stages

    def detail(self, session_id, query):
        events = self.store.analytics_snapshot(
            EventQuery(session_id=session_id, source=query.source)
        )
        if not events:
            return None
        summary = self.session_summary(events, query.as_of or datetime.now(UTC))
        page = events[query.offset : query.offset + query.limit]
        return DashboardSessionDetail(
            summary=summary,
            timeline=page,
            journey=self.journey_stages(page),
            **pagination(events, query),
        )

    def journey(self, session_id, query):
        stages = self.journey_stages(
            self.store.analytics_snapshot(EventQuery(session_id=session_id, source=query.source))
        )
        return JourneyPage(
            stages=stages[query.offset : query.offset + query.limit], **pagination(stages, query)
        )

    @staticmethod
    def _risk(sessions):
        levels, signals, scenarios, cases = Counter(), Counter(), Counter(), Counter()
        for session in sessions:
            levels[session.risk_level] += 1
            signals.update(session.risk_signals)
            if session.risk_level in ("high", "critical"):
                scenarios.update(session.scenarios)
            for event in session.results:
                if event.event_type == "fraud_case" and event.payload.case_type != "none":
                    cases[event.payload.case_type] += 1
        return RiskAnalytics(
            levels={level: levels[level] for level in LEVELS},
            high_risk_sessions=levels["high"] + levels["critical"],
            top_signals=ranked(signals),
            high_risk_scenarios=ranked(scenarios),
            fraud_case_types=ranked(cases),
        )

    def risk(self, query):
        return self._risk(self._sessions(query))

    def scenarios(self, query):
        counts = Counter()
        for session in self._sessions(query):
            counts.update(session.scenarios)
        return ranked(counts)

    def overview(self, query):
        snapshot = self._events(query)
        sessions = self._sessions(query, snapshot)
        now = query.as_of or datetime.now(UTC)
        channels, scenarios, statuses, outcomes, sources = (
            Counter(),
            Counter(),
            Counter(),
            Counter(),
            Counter(),
        )
        insurance_completed = 0
        for session in sessions:
            channels[session.channel] += 1
            scenarios.update(session.scenarios)
            statuses[session.status] += 1
            sources[session.source] += 1
            for event in session.results:
                if event.event_type == "sales_lead":
                    outcomes[event.payload.outcome] += 1
                if event.event_type == "insurance_result" and event.payload.completed:
                    insurance_completed += 1
        handoffs = sum(s.handoff for s in sessions)
        selected_ids = {s.session_id for s in sessions}
        events = sum(e.session_id in selected_ids for e in snapshot)
        return DashboardOverview(
            total_sessions=len(sessions),
            active_sessions=sum(s.active for s in sessions),
            recent_sessions=sum(
                now - timedelta(minutes=5) <= s.latest_event_at <= now for s in sessions
            ),
            sessions_by_channel={channel: channels[channel] for channel in ("text", "voice")},
            sessions_by_scenario=ranked(scenarios),
            conversation_statuses=dict(statuses),
            handoff_count=handoffs,
            handoff_rate=handoffs / len(sessions) if sessions else 0,
            risk=self._risk(sessions),
            sales_outcomes=ranked(outcomes),
            insurance_completed=insurance_completed,
            sources=dict(sources),
            retained_events=events,
            latency={
                key: MetricAverage()
                for key in (
                    "agent_ms",
                    "tts_ms",
                    "endpointing_ms",
                    "stt_final_ms",
                    "speech_end_to_playback_submit_ms",
                    "speech_end_to_playback_complete_ms",
                )
            },
        )

    def anomalies(self, query):
        now = query.as_of or datetime.now(UTC)
        seconds = self.settings.analytics_window_seconds
        count = self.settings.analytics_baseline_windows
        current_start = now - timedelta(seconds=seconds)
        baseline_start = current_start - timedelta(seconds=seconds * count)
        window = AnomalyWindow(
            current_from=current_start,
            current_to=now,
            baseline_from=baseline_start,
            baseline_to=current_start,
            window_seconds=seconds,
            baseline_windows=count,
        )
        # Index-bounded history read. Sources always have separate baselines.
        scope = EventQuery(
            from_time=baseline_start,
            to_time=now,
            source=query.source,
            assistant_id=query.assistant_id,
            channel=query.channel,
            session_id=query.session_id,
        )
        events = self.store.analytics_snapshot(scope)
        all_starts = self.store.source_history_starts(scope)
        anomalies, ready = [], False
        for source in ("runtime", "synthetic_demo"):
            if query.source and query.source != source:
                continue
            start = all_starts.get(source)
            if start is None or start > baseline_start:
                continue
            ready = True
            counts = [Counter() for _ in range(count + 1)]
            fraud_seen = [set() for _ in counts]
            for event in events:
                if event.source != source:
                    continue
                bucket = min(
                    count, int((event.created_at - baseline_start).total_seconds() // seconds)
                )
                metrics = []
                if (
                    event.event_type == "risk_signal"
                    and event.payload.analysis_status == "analyzed"
                ):
                    metrics += [("risk_signal", signal) for signal in set(event.risk_signals)]
                    if event.risk_level in ("high", "critical"):
                        metrics.append(("risk_level", event.risk_level))
                elif event.event_type == "operator_handoff":
                    metrics.append(("operator_handoff", "operator_handoff"))
                elif event.event_type == "fraud_case" and event.payload.case_type != "none":
                    discriminator = (event.session_id, event.payload.case_type)
                    if discriminator not in fraud_seen[bucket]:
                        metrics.append(("fraud_case", event.payload.case_type))
                        fraud_seen[bucket].add(discriminator)
                counts[bucket].update(metrics)
            for (metric, key), current in counts[-1].items():
                baseline = sum(bucket[(metric, key)] for bucket in counts[:-1])
                expected = baseline / count
                # No zero-baseline "attack" alerts: establish positive observation.
                if (
                    current < self.settings.analytics_min_volume
                    or expected <= 0
                    or current < expected * self.settings.analytics_anomaly_multiplier
                ):
                    continue
                ratio = current / expected
                anomalies.append(
                    Anomaly(
                        id=str(
                            uuid5(
                                NAMESPACE_URL,
                                f"veyra:anomaly:{source}:{now.isoformat()}:{metric}:{key}",
                            )
                        ),
                        detected_at=now,
                        metric=metric,
                        key=key,
                        source=source,
                        current_count=current,
                        baseline_count=baseline,
                        baseline_expected_count=expected,
                        ratio=ratio,
                        severity="high"
                        if ratio >= 2 * self.settings.analytics_anomaly_multiplier
                        else "medium",
                        window=window,
                        explanation=(
                            "Anomalous increase relative to observed baseline; "
                            "supervisor review required. Cause is not established."
                        ),
                    )
                )
        anomalies.sort(key=lambda a: (-a.ratio, a.source, a.metric, a.key))
        return AnomalyPage(
            anomalies=anomalies[query.offset : query.offset + query.limit],
            history_status="ready" if ready else "insufficient_history",
            as_of=now,
            **pagination(anomalies, query),
        )
