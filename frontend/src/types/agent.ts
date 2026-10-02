export type ConversationStatus =
  | 'active'
  | 'awaiting_user'
  | 'awaiting_confirmation'
  | 'handoff'
  | 'ended';

export type RuntimeStatus =
  | 'idle'
  | 'listening'
  | 'processing'
  | 'speaking'
  | 'handoff'
  | 'ended'
  | 'error';

export interface AgentMessageRequest {
  session_id: string;
  text: string;
  scenario_mode?: ScenarioPackId;
}

export type ScenarioPackId = 'insurance_manager' | 'product_promoter' | 'card_promoter' | 'loan_promoter';

export const scenarioPackNames: Record<ScenarioPackId, string> = {
  insurance_manager: 'Insurance Manager', product_promoter: 'Продажа депозита',
  card_promoter: 'Продажа карты', loan_promoter: 'Продажа кредита',
};
export function isScenarioPack(value: unknown): value is ScenarioPackId {
  return typeof value === 'string' && Object.hasOwn(scenarioPackNames, value);
}
export function isSalesPack(value: unknown): value is Exclude<ScenarioPackId, 'insurance_manager'> {
  return isScenarioPack(value) && value !== 'insurance_manager';
}

export interface AgentMessageResponse {
  response_text: string;
  routing?: unknown;
  state?: unknown;
  trace?: unknown;
  conversation_status: ConversationStatus;
}

export interface VoiceTranscript {
  text: string;
  language?: 'ru' | 'kk' | 'mixed';
  stt_ms?: number;
}

export interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  timestamp: number;
}
