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
  if (value !== "text" && value !== "voice")
    throw new Error("Analytics returned an invalid channel.");
  return value;
}
export const ranked = (value: unknown): RankedCount[] =>
  list(value).flatMap((v) => {
    const item = record(v);
    return text(item.key)
      ? [{ key: item.key as string, count: requiredNumber(item.count) }]
      : [];
  });
export function parseRisk(value: unknown): RiskAnalytics {
  const raw = object(value);
  requiredNumber(raw.high_risk_sessions);
  const levels = record(raw.levels);
  return {
    levels: Object.fromEntries(
      riskLevels.map((level) => [level, requiredNumber(levels[level])]),
    ) as RiskAnalytics["levels"],
    high_risk_sessions: requiredNumber(raw.high_risk_sessions),
    top_signals: ranked(raw.top_signals),
    high_risk_scenarios: ranked(raw.high_risk_scenarios),
    fraud_case_types: ranked(raw.fraud_case_types),
  };
}
export function parseOverview(value: unknown): Overview {
  const raw = object(value);
  const channels = record(raw.sessions_by_channel);
  return {
    total_sessions: requiredNumber(raw.total_sessions),
    sources: Object.fromEntries(
      Object.entries(record(raw.sources)).map(([k, v]) => [
        k,
        requiredNumber(v),
      ]),
    ),
    sales_outcomes: ranked(raw.sales_outcomes),
    insurance_completed: requiredNumber(raw.insurance_completed),
    active_sessions: requiredNumber(raw.active_sessions),
    recent_sessions: requiredNumber(raw.recent_sessions),
    sessions_by_channel: {
      text: requiredNumber(channels.text),
      voice: requiredNumber(channels.voice),
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
  return {
    session_id: id,
    channel: channel(raw.channel),
    started_at: text(raw.started_at),
    ended_at: text(raw.ended_at),
    latest_event_at: requiredText(raw.latest_event_at),
    language: text(raw.language),
    scenarios: strings(raw.scenarios),
    primary_scenario: text(raw.primary_scenario),
    last_scenario: text(raw.last_scenario),
    risk_level: requiredRisk(raw.risk_level),
    risk_signals: strings(raw.risk_signals),
    latest_risk: undefined,
    clarification_count: number(raw.clarification_count),
    handoff: requiredBoolean(raw.handoff),
    completed: requiredBoolean(raw.completed),
    active: requiredBoolean(raw.active),
    status: requiredText(raw.status),
    turn_count: requiredNumber(raw.turn_count),
    total_duration_ms: number(raw.total_duration_ms),
    average_agent_ms: number(raw.average_agent_ms),
    average_tts_ms: number(raw.average_tts_ms),
    latest_latency: Object.fromEntries(
      Object.entries(record(raw.latest_latency)).flatMap(([k, v]) =>
        number(v) === null ? [] : [[k, v as number]],
      ),
    ),
    source: requiredSource(raw.source, true),
    scenario_ids: strings(raw.scenario_ids),
    results: list(raw.results).map(parseEvent),
    partial_history: raw.partial_history === true,
  };
}
export const parseSessions = (value: unknown): Session[] =>
  list(value).map(parseSession);
export function parseJourney(value: unknown): JourneyStage[] {
  return list(value).map((v) => {
    const raw = object(v);
    return {
      id: requiredText(raw.id),
      event_type: requiredText(raw.event_type),
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
    ...parsePagination(raw),
    journey: parseJourney(raw.journey),
    timeline: list(raw.timeline).map(parseEvent),
  };
}
export function parseAnomalies(value: unknown): Anomaly[] {
  return list(value).map((v) => {
    const raw = object(v);
    return {
      id: requiredText(raw.id),
      source: requiredSource(raw.source),
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

function requiredNumber(value: unknown): number {
  const parsed = number(value);
  if (parsed === null)
    throw new Error("Analytics returned an invalid required count.");
  return parsed;
}
function requiredText(value: unknown): string {
  const parsed = text(value);
  if (!parsed)
    throw new Error("Analytics returned an invalid required identifier.");
  return parsed;
}
function requiredBoolean(value: unknown): boolean {
  if (typeof value !== "boolean")
    throw new Error("Analytics returned an invalid lifecycle flag.");
  return value;
}
function requiredRisk(value: unknown) {
  const parsed = riskLevels.find((level) => level === value);
  if (!parsed) throw new Error("Analytics returned an invalid risk level.");
  return parsed;
}
function requiredSource(value: unknown): "runtime" | "synthetic_demo";
function requiredSource(
  value: unknown,
  mixed: true,
): "runtime" | "synthetic_demo" | "mixed";
function requiredSource(
  value: unknown,
  mixed = false,
): "runtime" | "synthetic_demo" | "mixed" {
  if (
    value !== "runtime" &&
    value !== "synthetic_demo" &&
    !(mixed && value === "mixed")
  )
    throw new Error("Analytics returned an invalid source.");
  return value as "runtime" | "synthetic_demo" | "mixed";
}
// Stage 5A intentionally excludes transcripts, identifiers and free-form reasons.
const safePayloadFields = new Set([
  "kind",
  "actions",
  "completed",
  "handoff",
  "campaign",
  "product_category",
  "selected_product_id",
  "presented_product_ids",
  "outcome",
  "interest_level",
  "next_action",
  "case_type",
  "case_status",
  "facts",
  "recommended_action",
  "guidance_shown",
  "analysis_status",
  "assistant_initiated",
  "previous_assistant_id",
]);
function parseEvent(value: unknown) {
  const raw = object(value);
  return {
    id: requiredText(raw.event_id),
    event_type: requiredText(raw.event_type),
    timestamp: requiredText(raw.created_at),
    assistant_id: requiredText(raw.assistant_id),
    source: requiredSource(raw.source),
    payload: Object.fromEntries(
      Object.entries(record(raw.payload)).filter(([key]) =>
        safePayloadFields.has(key),
      ),
    ),
  };
}
function parsePagination(value: unknown) {
  const raw = object(value);
  return {
    total: requiredNumber(raw.total),
    limit: requiredNumber(raw.limit),
    offset: requiredNumber(raw.offset),
    next_offset:
      raw.next_offset === null ? null : requiredNumber(raw.next_offset),
  };
}
export function parseSessionPage(value: unknown) {
  const raw = object(value);
  return { ...parsePagination(raw), sessions: parseSessions(raw.sessions) };
}
export function parseJourneyPage(value: unknown) {
  const raw = object(value);
  return { ...parsePagination(raw), stages: parseJourney(raw.stages) };
}
export function parseAnomalyPage(value: unknown) {
  const raw = object(value);
  if (
    raw.history_status !== "ready" &&
    raw.history_status !== "insufficient_history"
  )
    throw new Error("Analytics returned an invalid history status.");
  return {
    ...parsePagination(raw),
    anomalies: parseAnomalies(raw.anomalies),
    history_status: raw.history_status as "ready" | "insufficient_history",
    as_of: requiredText(raw.as_of),
  };
}
