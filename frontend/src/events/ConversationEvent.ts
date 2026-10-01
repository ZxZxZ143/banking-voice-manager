import type { Channel } from '../channels/channel';
import type { AgentMessageResponse, ConversationStatus } from '../types/agent';

export type ConversationEventType =
  | 'session.started'
  | 'transcript.final'
  | 'agent.response'
  | 'scenario.selected'
  | 'clarification.requested'
  | 'handoff.requested'
  | 'conversation.ended';

/** Optional Agent payloads remain opaque until Agent Core publishes their contracts. */
export interface ConversationEvent {
  id: string;
  session_id: string;
  /** UTC ISO 8601; retrieval order is append order, including equal timestamps. */
  timestamp: string;
  event_type: ConversationEventType;
  channel: Channel;
  language?: string;
  text?: string;
  scenario?: unknown;
  action?: unknown;
  confidence?: number;
  conversation_status?: ConversationStatus;
  clarification?: boolean | string;
  handoff?: boolean;
  risk?: AgentMessageResponse['risk'];
  routing?: AgentMessageResponse['routing'];
  state?: AgentMessageResponse['state'];
  trace?: AgentMessageResponse['trace'];
  latency?: unknown;
  metadata?: Record<string, unknown>;
}

export function createConversationEvent(
  input: Omit<ConversationEvent, 'id' | 'timestamp'>,
  identity: { id: string; timestamp: string } = {
    id: crypto.randomUUID(), timestamp: new Date().toISOString(),
  },
): ConversationEvent {
  return { ...input, ...identity };
}
