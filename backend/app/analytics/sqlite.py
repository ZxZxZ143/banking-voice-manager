import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import UUID

from app.analytics.models import (
    AnalyticsSummary,
    ConversationEvent,
    EventPage,
    EventQuery,
    Period,
    RiskCounts,
    SalesCounts,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    created_at TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL CHECK (turn_number >= 1),
    sequence INTEGER NOT NULL,
    channel TEXT NOT NULL,
    assistant_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    conversation_status TEXT NOT NULL,
    scenario_id TEXT,
    risk_level TEXT,
    risk_signals_json TEXT NOT NULL,
    result_status TEXT,
    source TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id, turn_number, sequence, created_at);
CREATE INDEX IF NOT EXISTS events_assistant ON events(assistant_id, created_at);
CREATE INDEX IF NOT EXISTS events_type ON events(event_type, created_at);
CREATE INDEX IF NOT EXISTS events_risk ON events(risk_level, created_at);
CREATE INDEX IF NOT EXISTS events_source ON events(source);
PRAGMA user_version = 1;
"""


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class SQLiteEventStore:
    """Short file-backed transactions, WAL readers and bounded lock waits.

    Connections are private to each operation/thread and always closed. Schema v1
    needs no ORM; a future schema change must explicitly migrate user_version.
    """

    def __init__(self, path: Path, *, timeout: float = 0.1):
        self.path = Path(path)
        self.timeout = timeout
        self._ready = False
        self._initialization = Lock()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=self.timeout)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._initialization:
            if self._ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise ValueError("Unsupported analytics schema version")
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(SCHEMA)
            self._ready = True

    def probe(self) -> None:
        self.initialize()
        with self._connection() as db:
            db.execute("SELECT event_id FROM events LIMIT 1").fetchone()

    def append(self, event: ConversationEvent) -> int:
        return self.append_many([event])

    def append_many(self, events: list[ConversationEvent]) -> int:
        self.initialize()
        with self._connection() as db:
            before = db.total_changes
            for original in events:
                # Revalidate copies: even callers using model_construct/copy cannot
                # bypass the allowlisted schema at the persistence boundary.
                event = ConversationEvent.model_validate(
                    original.model_dump(mode="json", warnings=False)
                )
                db.execute(
                    """INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(idempotency_key) DO NOTHING""",
                    (
                        str(event.event_id),
                        event.schema_version,
                        timestamp(event.created_at),
                        event.session_id,
                        event.turn_number,
                        event.sequence,
                        event.channel,
                        event.assistant_id,
                        event.event_type,
                        event.conversation_status,
                        event.scenario_id,
                        event.risk_level,
                        json.dumps(event.risk_signals),
                        event.result_status,
                        event.source,
                        event.payload.model_dump_json(),
                        event.idempotency_key,
                    ),
                )
            return db.total_changes - before

    @staticmethod
    def _event(row: sqlite3.Row) -> ConversationEvent:
        values = dict(row)
        values.pop("idempotency_key")
        values["payload"] = json.loads(values.pop("payload_json"))
        values["risk_signals"] = json.loads(values.pop("risk_signals_json"))
        return ConversationEvent.model_validate(values)

    def get_event(self, event_id: UUID) -> ConversationEvent | None:
        self.initialize()
        with self._connection() as db:
            row = db.execute("SELECT * FROM events WHERE event_id = ?", (str(event_id),)).fetchone()
            return self._event(row) if row else None

    @staticmethod
    def _where(query: EventQuery):
        conditions, values = [], []
        for column in (
            "session_id",
            "assistant_id",
            "event_type",
            "risk_level",
            "channel",
            "source",
        ):
            value = getattr(query, column)
            if value is not None:
                conditions.append(f"{column} = ?")
                values.append(value)
        if query.from_time:
            conditions.append("created_at >= ?")
            values.append(timestamp(query.from_time))
        if query.to_time:
            conditions.append("created_at < ?")
            values.append(timestamp(query.to_time))
        return " AND ".join(conditions) or "1=1", values

    def query_events(self, query: EventQuery) -> EventPage:
        self.initialize()
        where, values = self._where(query)
        order = (
            "turn_number, sequence, created_at, event_id"
            if query.session_id
            else "created_at DESC, session_id, turn_number, sequence, event_id"
        )
        with self._connection() as db:
            # Count/page use one read snapshot even while another turn appends.
            db.execute("BEGIN")
            total = db.execute(f"SELECT count(*) FROM events WHERE {where}", values).fetchone()[0]
            rows = db.execute(
                f"SELECT * FROM events WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                [*values, query.limit, query.offset],
            ).fetchall()
        end = query.offset + len(rows)
        return EventPage(
            events=[self._event(row) for row in rows],
            total=total,
            limit=query.limit,
            offset=query.offset,
            next_offset=end if end < total else None,
        )

    def get_session_events(self, session_id: str, *, limit=100, offset=0) -> EventPage:
        return self.query_events(EventQuery(session_id=session_id, limit=limit, offset=offset))

    def get_recent_events(self, limit: int = 100) -> EventPage:
        return self.query_events(EventQuery(limit=limit))

    def analytics_snapshot(self, query: EventQuery) -> list[ConversationEvent]:
        """Internal aggregate input, one snapshot. Never exposed as an unbounded API."""
        self.initialize()
        where, values = self._where(query)
        with self._connection() as db:
            rows = db.execute(
                f"SELECT * FROM events WHERE {where} "
                "ORDER BY session_id, turn_number, sequence, created_at, event_id",
                values,
            ).fetchall()
        return [self._event(row) for row in rows]

    def source_history_starts(self, query: EventQuery) -> dict[str, datetime]:
        self.initialize()
        scope = query.model_copy(update={"from_time": None, "to_time": None})
        where, values = self._where(scope)
        with self._connection() as db:
            rows = db.execute(
                f"SELECT source, min(created_at) FROM events WHERE {where} GROUP BY source",
                values,
            ).fetchall()
        return {row[0]: datetime.fromisoformat(row[1]) for row in rows}

    def summary(self, query: EventQuery) -> AnalyticsSummary:
        self.initialize()
        where, values = self._where(query)
        with self._connection() as db:
            db.execute("BEGIN")
            counts = dict(
                db.execute(
                    f"SELECT event_type, count(*) FROM events WHERE {where} GROUP BY event_type",
                    values,
                ).fetchall()
            )
            conversations = db.execute(
                f"SELECT count(DISTINCT session_id) FROM events WHERE {where}", values
            ).fetchone()[0]
            risk_levels = dict(
                db.execute(
                    f"""SELECT risk_level, count(*) FROM events WHERE {where}
                    AND event_type='risk_signal' AND risk_level IS NOT NULL GROUP BY risk_level""",
                    values,
                ).fetchall()
            )
            signals = dict(
                db.execute(
                    f"""SELECT signal.value, count(*) FROM events,
                    json_each(risk_signals_json) signal
                    WHERE {where} AND event_type='risk_signal' GROUP BY signal.value
                    ORDER BY count(*) DESC, signal.value""",
                    values,
                ).fetchall()
            )
            # Result events are evolving snapshots. Count the latest snapshot per
            # session/assistant within the requested period, avoiding inflated leads.
            cte = f"""WITH ranked AS (
                SELECT *, row_number() OVER (
                    PARTITION BY session_id, assistant_id, event_type
                    ORDER BY turn_number DESC, sequence DESC, created_at DESC, event_id
                ) AS rank FROM events WHERE {where}
                AND event_type IN ('insurance_result','sales_lead','fraud_case')
            ) """
            by_assistant = dict(
                db.execute(
                    cte + "SELECT assistant_id, count(*) FROM ranked "
                    "WHERE rank=1 GROUP BY assistant_id",
                    values,
                ).fetchall()
            )
            outcomes = dict(
                db.execute(
                    cte
                    + """SELECT json_extract(payload_json,'$.outcome'), count(*) FROM ranked
                    WHERE rank=1 AND event_type='sales_lead' GROUP BY 1""",
                    values,
                ).fetchall()
            )
            cases = dict(
                db.execute(
                    cte
                    + """SELECT json_extract(payload_json,'$.case_type'), count(*) FROM ranked
                    WHERE rank=1 AND event_type='fraud_case'
                    AND json_extract(payload_json,'$.case_type') != 'none' GROUP BY 1""",
                    values,
                ).fetchall()
            )
        return AnalyticsSummary(
            period=Period(from_time=query.from_time, to_time=query.to_time),
            conversations=conversations,
            handoffs=counts.get("operator_handoff", 0),
            event_counts=counts,
            results_by_assistant=by_assistant,
            risk=RiskCounts(
                total=sum(v for k, v in risk_levels.items() if k != "none"),
                high=risk_levels.get("high", 0),
                critical=risk_levels.get("critical", 0),
                levels=risk_levels,
                signals=signals,
            ),
            sales=SalesCounts(
                leads=sum(outcomes.values()),
                interested=outcomes.get("interested", 0),
                declined=outcomes.get("declined", 0),
                outcomes=outcomes,
            ),
            fraud_cases=sum(cases.values()),
            fraud_case_types=cases,
        )

    def reset_synthetic(self) -> int:
        """Explicit seed CLI use only; no deletion API is exposed."""
        self.initialize()
        with self._connection() as db:
            return db.execute("DELETE FROM events WHERE source = 'synthetic_demo'").rowcount
