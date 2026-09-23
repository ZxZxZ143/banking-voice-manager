/** Keep aligned with backend/app/tracing/models.py. */
export type Language = 'ru' | 'kk' | 'mixed';
export type JsonValue = string | number | boolean | null | JsonValue[] | {
  [key: string]: JsonValue;
};

export interface ScenarioSelection {
  scenario_id: string;
  confidence: number;
  reason: string;
}

export interface ScenarioAlternative {
  scenario_id: string;
  confidence: number;
}

export interface TraceRecord {
  turn: number;
  transcript: string;
  language: Language | null;
  scenarios: ScenarioSelection[];
  alternatives: ScenarioAlternative[];
  reason: string;
  slots: Record<string, JsonValue>;
  actions: string[];
  latency_ms: {
    stt: number | null;
    triage: number | null;
    router: number | null;
    tools: number | null;
    response: number | null;
    tts_first_audio: number | null;
    total: number | null;
  };
}

export interface HealthResponse {
  status: 'ok';
  service: 'voice-router';
  mode: 'foundation';
  starter_kit: {
    scenarios: number;
    system_intents: number;
    actions: number;
    dev_utterances: number;
  };
}

export interface TextTurnRequest {
  session_id: string;
  text: string;
}
