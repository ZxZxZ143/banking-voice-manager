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
  channel?: 'voice';
  recognition_id?: string;
}

export type ScenarioPackId = 'insurance_manager' | 'product_promoter' | 'card_promoter' | 'loan_promoter' | 'fraud_security';

export const scenarioPackNames: Record<ScenarioPackId, string> = {
  insurance_manager: 'Insurance Manager', product_promoter: 'Продажа депозита',
  card_promoter: 'Продажа карты', loan_promoter: 'Продажа кредита',
  fraud_security: 'Fraud & Security',
};
export function isScenarioPack(value: unknown): value is ScenarioPackId {
  return typeof value === 'string' && Object.hasOwn(scenarioPackNames, value);
}
export function isSalesPack(value: unknown): value is 'product_promoter' | 'card_promoter' | 'loan_promoter' {
  return value === 'product_promoter' || value === 'card_promoter' || value === 'loan_promoter';
}

export interface AgentMessageResponse {
  response_text: string;
  routing?: unknown;
  state?: unknown;
  trace?: unknown;
  risk?: unknown;
  conversation_status: ConversationStatus;
}

export interface VoiceTranscript {
  text: string;
  language?: 'ru' | 'kk' | 'mixed';
  stt_ms?: number;
  recognition_id?: string;
}

export interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  timestamp: number;
}
