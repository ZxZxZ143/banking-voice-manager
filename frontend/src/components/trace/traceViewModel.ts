import type { ConversationStatus } from '../../types/agent';
import type { ConversationSnapshot } from '../../runtime/ConversationRuntime';

type Data = Record<string, unknown>;

export interface ScenarioView {
  id: string;
  name: string | null;
  confidence: string | null;
}

export interface TraceViewModel {
  hasData: boolean;
  mock: boolean;
  turn: number | null;
  transcript: string | null;
  language: string | null;
  scenarios: ScenarioView[];
  alternatives: ScenarioView[];
  reason: string | null;
  slots: { key: string; value: string }[];
  actions: string[];
  clarification: string | null;
  handoff: { queue: string | null; summary: string | null; reason: string | null } | null;
  activeScenario: ScenarioView | null;
  scenarioStack: ScenarioView[];
  pendingScenarios: ScenarioView[];
  latency: { label: string; value: string; source: 'agent' | 'browser' }[];
  conversationStatus: ConversationStatus | null;
}

function record(value: unknown): Data | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Data : null;
}

function string(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function metric(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

export function formatConfidence(value: unknown): string | null {
  const confidence = metric(value);
  return confidence !== null && confidence <= 1 ? `${Math.round(confidence * 100)}%` : null;
}

export function formatLatency(value: unknown): string | null {
  const ms = metric(value);
  if (ms === null) return null;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${Number((ms / 1000).toFixed(2))} s`;
}

function scenario(value: unknown): ScenarioView | null {
  if (typeof value === 'string') return value.trim() ? { id: value, name: null, confidence: null } : null;
  const data = record(value);
  const id = string(data?.scenario_id);
  if (!id) return null;
  return { id, name: string(data?.name), confidence: formatConfidence(data?.confidence) };
}

function scenarios(value: unknown): ScenarioView[] {
  return Array.isArray(value) ? value.flatMap((item) => {
    const parsed = scenario(item);
    return parsed ? [parsed] : [];
  }) : [];
}

function displayValue(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

function actions(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const data = record(item);
    const name = string(item) ?? string(data?.name) ?? string(data?.action);
    if (!name) return [];
    const status = string(data?.status);
    return [status ? `${name}: ${status}` : name];
  });
}

function message(value: unknown): string | null {
  const data = record(value);
  return string(value) ?? string(data?.question) ?? string(data?.text) ?? string(data?.message);
}

function handoff(value: unknown): TraceViewModel['handoff'] {
  const data = record(value);
  const result = {
    queue: string(data?.operator_queue) ?? string(data?.queue),
    summary: string(data?.context_summary) ?? string(data?.summary),
    reason: string(value) ?? string(data?.reason),
  };
  return result.queue || result.summary || result.reason ? result : null;
}

const latencyStages = [
  ['stt', 'STT'], ['triage', 'Triage'], ['router', 'Router'], ['policy', 'Policy'],
  ['tools', 'Tools'], ['response', 'Response'], ['tts_first_audio', 'TTS first audio'],
  ['total', 'Total'],
] as const;

export function createTraceViewModel(snapshot: ConversationSnapshot): TraceViewModel {
  const trace = record(snapshot.latestTrace);
  const routing = record(snapshot.lastResponse?.routing);
  const state = record(snapshot.latestState);
  const latencyData = record(trace?.latency_ms);
  const latency: TraceViewModel['latency'] = [];
  for (const [key, label] of latencyStages) {
    const agentValue = formatLatency(latencyData?.[key]);
    if (agentValue) {
      latency.push({ label, value: agentValue, source: 'agent' });
      continue;
    }
    const browserValue = key === 'stt' ? formatLatency(snapshot.sttLatencyMs)
      : key === 'tts_first_audio' ? formatLatency(snapshot.ttsFirstAudioMs) : null;
    if (browserValue) latency.push({ label, value: browserValue, source: 'browser' });
  }
  const slots = record(trace?.slots) ?? record(routing?.slots);
  const handoffInfo = handoff(trace?.handoff ?? state?.handoff);

  return {
    hasData: trace !== null || routing !== null || state !== null || latency.length > 0,
    mock: trace?.mode === 'mock',
    turn: Number.isInteger(trace?.turn) && typeof trace?.turn === 'number' && trace.turn >= 0 ? trace.turn : null,
    transcript: string(trace?.transcript),
    language: string(trace?.language) ?? string(routing?.language),
    scenarios: scenarios(trace?.scenarios ?? routing?.scenarios),
    alternatives: scenarios(trace?.alternatives ?? routing?.alternatives),
    reason: string(trace?.reason) ?? string(routing?.reason),
    slots: slots ? Object.entries(slots).map(([key, value]) => ({ key, value: displayValue(value) })) : [],
    actions: actions(trace?.actions ?? routing?.actions),
    clarification: message(trace?.clarification ?? routing?.clarification ?? state?.clarification),
    handoff: handoffInfo,
    activeScenario: scenario(state?.active_scenario),
    scenarioStack: scenarios(state?.scenario_stack),
    pendingScenarios: scenarios(state?.pending_scenarios),
    latency,
    conversationStatus: snapshot.conversationStatus,
  };
}
