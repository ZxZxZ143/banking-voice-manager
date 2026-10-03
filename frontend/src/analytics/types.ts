export type Channel = "text" | "voice";
export const riskLevels = [
  "unknown",
  "none",
  "low",
  "medium",
  "high",
  "critical",
] as const;
export type RiskLevel = (typeof riskLevels)[number];
export interface Metric {
  average_ms: number | null;
  samples: number | null;
}
export interface RankedCount {
  key: string;
  count: number | null;
}
export interface RiskAnalytics {
  levels: Record<RiskLevel, number | null>;
  high_risk_sessions: number | null;
  top_signals: RankedCount[];
  high_risk_scenarios: RankedCount[];
  fraud_case_types: RankedCount[];
}
export interface Overview {
  sources: Record<string, number>;
  sales_outcomes: RankedCount[];
  insurance_completed: number;
  total_sessions: number;
  active_sessions: number | null;
  recent_sessions: number | null;
  sessions_by_channel: Record<Channel, number | null>;
  sessions_by_scenario: RankedCount[];
  conversation_statuses: Record<string, number | null>;
  clarification_count: number | null;
  clarification_rate: number | null;
  handoff_count: number | null;
  handoff_rate: number | null;
  risk: RiskAnalytics;
  latency: Record<string, Metric>;
  retained_events: number | null;
  capacity: number | null;
  evicted_events: number | null;
}
export interface Session {
  session_id: string;
  channel: Channel;
  started_at: string | null;
  ended_at: string | null;
  latest_event_at: string | null;
  language: string | null;
  scenarios: string[];
  primary_scenario: string | null;
  last_scenario: string | null;
  risk_level: RiskLevel;
  risk_signals: string[];
  latest_risk: unknown;
  clarification_count: number | null;
  handoff: boolean;
  completed: boolean;
  active: boolean;
  status: string;
  turn_count: number | null;
  total_duration_ms: number | null;
  average_agent_ms: number | null;
  average_tts_ms: number | null;
  latest_latency: Record<string, number>;
  source: "runtime" | "synthetic_demo" | "mixed";
  scenario_ids: string[];
  results: TimelineEvent[];
  partial_history: boolean;
}
export interface JourneyStage {
  id: string;
  session_id: string;
  timestamp: string | null;
  event_type: string;
  scenario: string | null;
  action: unknown;
  source_event_id: string | null;
  channel: Channel;
  clarification: boolean;
  handoff: boolean;
  completion: boolean;
}
export interface TimelineEvent {
  id: string;
  event_type: string;
  timestamp: string | null;
  assistant_id: string;
  source: "runtime" | "synthetic_demo";
  payload: Record<string, unknown>;
}
export interface SessionDetail {
  summary: Session;
  timeline: TimelineEvent[];
  journey: JourneyStage[];
  total: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}
export interface Anomaly {
  id: string;
  detected_at: string | null;
  source: "runtime" | "synthetic_demo";
  metric: string;
  key: string;
  current_count: number | null;
  baseline_count: number | null;
  baseline_expected_count: number | null;
  ratio: number | null;
  severity: "low" | "medium" | "high" | "unknown";
  window: Record<string, unknown>;
  explanation: string;
  partial_history: boolean;
}
export interface Filters {
  channel?: Channel;
  scenario?: string;
  risk_level?: RiskLevel;
  session_id?: string;
  active?: boolean;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
  source?: "runtime" | "synthetic_demo";
  as_of?: string;
}

export interface Pagination {
  total: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}
export interface SessionPage extends Pagination {
  sessions: Session[];
}
export interface JourneyPage extends Pagination {
  stages: JourneyStage[];
}
export interface AnomalyPage extends Pagination {
  anomalies: Anomaly[];
  history_status: "ready" | "insufficient_history";
  as_of: string;
}
