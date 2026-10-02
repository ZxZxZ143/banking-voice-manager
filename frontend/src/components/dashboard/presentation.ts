import type { JourneyStage, RiskLevel, Session } from "../../analytics/types";
export function count(value: number | null | undefined) {
  return value == null ? "—" : value.toLocaleString();
}
export function latency(value: number | null | undefined) {
  return value == null
    ? "—"
    : value < 1000
      ? `${Math.round(value)} ms`
      : `${(value / 1000).toFixed(2)} s`;
}
export function date(value: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}
export function activity(value: string | null, now = Date.now()) {
  if (!value || !Number.isFinite(Date.parse(value)))
    return "Activity unavailable";
  const seconds = Math.max(0, Math.floor((now - Date.parse(value)) / 1000));
  return seconds < 60
    ? `${seconds}s ago`
    : seconds < 3600
      ? `${Math.floor(seconds / 60)}m ago`
      : `${Math.floor(seconds / 3600)}h ago`;
}
export const riskLabels: Record<RiskLevel, string> = {
  unknown: "No risk data",
  low: "Low signal",
  medium: "Medium signal",
  high: "High risk signal",
  critical: "Critical signal",
};
export function stageLabel(stage: JourneyStage) {
  if (stage.scenario) return stage.scenario.replaceAll("_", " ");
  if (stage.handoff) return "Handoff";
  if (stage.clarification) return "Clarification";
  if (stage.completion) return "Completed";
  return "Session closure";
}
export function demoScope(
  sessions: Session[],
  configured = false,
): "none" | "demo" | "mixed" {
  const demo = sessions.filter(
    (s) =>
      s.provider_metadata.demo === true || s.session_id.startsWith("DEMO-"),
  ).length;
  if (demo && demo < sessions.length) return "mixed";
  return configured || demo > 0 ? "demo" : "none";
}
