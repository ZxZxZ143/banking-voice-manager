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
