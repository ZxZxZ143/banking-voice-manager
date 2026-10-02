import {
  riskLevels,
  type Anomaly,
  type Channel,
  type JourneyStage,
  type Overview,
  type RankedCount,
  type RiskAnalytics,
  type Session,
  type SessionDetail,
} from "./types";

export const record = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
export const text = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value : null;
export const number = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : null;
const strings = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
const list = (value: unknown): unknown[] => {
  if (value == null) return [];
  if (!Array.isArray(value))
    throw new Error("Analytics returned an invalid list.");
  return value;
};
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Analytics returned an invalid response.");
  return record(value);
}
function channel(value: unknown): Channel {
  if (value !== "web" && value !== "phone")
    throw new Error("Analytics returned an invalid channel.");
  return value;
}
export const ranked = (value: unknown): RankedCount[] =>
  list(value).flatMap((v) => {
    const item = record(v);
    return text(item.key)
      ? [{ key: item.key as string, count: number(item.count) }]
      : [];
  });
export function parseRisk(value: unknown): RiskAnalytics {
  const raw = record(value);
  const levels = record(raw.levels);
  return {
    levels: Object.fromEntries(
      riskLevels.map((level) => [level, number(levels[level])]),
    ) as RiskAnalytics["levels"],
    high_risk_sessions: number(raw.high_risk_sessions),
    top_signals: ranked(raw.top_signals),
    high_risk_scenarios: ranked(raw.high_risk_scenarios),
  };
}
export function parseOverview(value: unknown): Overview {
  const raw = object(value);
  const channels = record(raw.sessions_by_channel);
  return {
    total_sessions: number(raw.total_sessions),
    active_sessions: number(raw.active_sessions),
    recent_sessions: number(raw.recent_sessions),
    sessions_by_channel: {
      web: number(channels.web),
      phone: number(channels.phone),
    },
    sessions_by_scenario: ranked(raw.sessions_by_scenario),
    conversation_statuses: Object.fromEntries(
      Object.entries(record(raw.conversation_statuses)).map(([k, v]) => [
        k,
        number(v),
      ]),
    ),
    clarification_count: number(raw.clarification_count),
    clarification_rate: number(raw.clarification_rate),
    handoff_count: number(raw.handoff_count),
    handoff_rate: number(raw.handoff_rate),
    risk: parseRisk(raw.risk),
    latency: Object.fromEntries(
      Object.entries(record(raw.latency)).map(([key, v]) => {
        const metric = record(v);
        return [
          key,
          {
            average_ms: number(metric.average_ms),
            samples: number(metric.samples),
          },
        ];
      }),
    ),
    retained_events: number(raw.retained_events),
    capacity: number(raw.capacity),
    evicted_events: number(raw.evicted_events),
  };
}
export function parseSession(value: unknown): Session {
  const raw = object(value);
  const id = text(raw.session_id);
  if (!id)
    throw new Error("Analytics returned a session without an identifier.");
  const metadata = record(raw.provider_metadata);
  const allowed = [
    "provider",
    "call_uuid",
    "call_id",
    "call_sid",
    "stream_sid",
    "demo",
  ];
  return {
    session_id: id,
    channel: channel(raw.channel),
    started_at: text(raw.started_at),
    ended_at: text(raw.ended_at),
    latest_event_at: text(raw.latest_event_at),
    language: text(raw.language),
    scenarios: strings(raw.scenarios),
    primary_scenario: text(raw.primary_scenario),
    last_scenario: text(raw.last_scenario),
    risk_level:
      riskLevels.find((level) => level === raw.risk_level) ?? "unknown",
    risk_signals: strings(raw.risk_signals),
    latest_risk: raw.latest_risk,
    clarification_count: number(raw.clarification_count),
    handoff: raw.handoff === true,
    completed: raw.completed === true,
    active: raw.active === true,
    status: text(raw.status) ?? "unknown",
    turn_count: number(raw.turn_count),
    total_duration_ms: number(raw.total_duration_ms),
    average_agent_ms: number(raw.average_agent_ms),
    average_tts_ms: number(raw.average_tts_ms),
    latest_latency: Object.fromEntries(
      Object.entries(record(raw.latest_latency)).flatMap(([k, v]) =>
        number(v) === null ? [] : [[k, v as number]],
      ),
    ),
    provider_metadata: Object.fromEntries(
      Object.entries(metadata).filter(([key]) => allowed.includes(key)),
    ),
    partial_history: raw.partial_history === true,
  };
}
export const parseSessions = (value: unknown): Session[] =>
  list(value).map(parseSession);
export function parseJourney(value: unknown): JourneyStage[] {
  return list(value).map((v, index) => {
    const raw = object(v);
    return {
      id: text(raw.id) ?? `stage-${index}`,
      session_id: text(raw.session_id) ?? "",
      timestamp: text(raw.timestamp),
      scenario: text(raw.scenario),
      action: raw.action,
      source_event_id: text(raw.source_event_id),
      channel: channel(raw.channel),
      clarification: raw.clarification === true,
      handoff: raw.handoff === true,
      completion: raw.completion === true,
    };
  });
}
export function parseDetail(value: unknown): SessionDetail {
  const raw = object(value);
  return {
    summary: parseSession(raw.summary),
    journey: parseJourney(raw.journey),
    timeline: list(raw.timeline).map((v, index) => {
      const event = record(v);
      return {
        id: text(event.id) ?? `event-${index}`,
        event_type: text(event.event_type) ?? "unknown",
        timestamp: text(event.timestamp),
        text: text(event.text),
        trace: record(event.trace),
      };
    }),
  };
}
export function parseAnomalies(value: unknown): Anomaly[] {
  return list(value).map((v, index) => {
    const raw = object(v);
    return {
      id: text(raw.id) ?? `anomaly-${index}`,
      detected_at: text(raw.detected_at),
      metric: text(raw.metric) ?? "unknown",
      key: text(raw.key) ?? "Unknown signal",
      current_count: number(raw.current_count),
      baseline_count: number(raw.baseline_count),
      baseline_expected_count: number(raw.baseline_expected_count),
      ratio: number(raw.ratio),
      severity:
        raw.severity === "high"
          ? "high"
          : raw.severity === "medium"
            ? "medium"
            : raw.severity === "low"
              ? "low"
              : "unknown",
      window: record(raw.window),
      explanation:
        text(raw.explanation) ??
        "Unusual observed volume. Review the underlying events.",
      partial_history: raw.partial_history === true,
    };
  });
}
