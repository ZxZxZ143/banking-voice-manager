import type { AgentMessageRequest, AgentMessageResponse, ConversationStatus } from '../types/agent';

export interface AgentClient {
  sendMessage(request: AgentMessageRequest): Promise<AgentMessageResponse>;
}

const statuses: ConversationStatus[] = [
  'active', 'awaiting_user', 'awaiting_confirmation', 'handoff', 'ended',
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseResponse(value: unknown): AgentMessageResponse {
  if (
    !isRecord(value)
    || typeof value.response_text !== 'string'
    || !value.response_text.trim()
    || !statuses.includes(value.conversation_status as ConversationStatus)
  ) {
    throw new AgentApiError('Malformed /api/message response: expected response_text and conversation_status.', false);
  }
  return value as unknown as AgentMessageResponse;
}

export class AgentApiError extends Error {
  constructor(message: string, readonly recoverable: boolean) {
    super(message);
    this.name = 'AgentApiError';
  }
}

export class HttpAgentClient implements AgentClient {
  constructor(
    private readonly baseUrl: string = import.meta.env.VITE_API_BASE_URL ?? '',
    // Agent Core allows 45 seconds; leave time for the response and network overhead.
    private readonly timeoutMs = 60_000,
  ) {}

  async sendMessage(request: AgentMessageRequest): Promise<AgentMessageResponse> {
    let response: Response;
    const signal = AbortSignal.timeout(this.timeoutMs);
    try {
      response = await fetch(`${this.baseUrl.replace(/\/$/, '')}/api/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        signal,
      });
    } catch (cause) {
      if (signal.aborted || (cause instanceof Error && cause.name === 'TimeoutError')) {
        throw new AgentApiError(`Agent API request timed out after ${this.timeoutMs} ms.`, true);
      }
      throw new AgentApiError('Agent API unavailable. Check VITE_API_BASE_URL and the backend connection.', true);
    }

    let body: unknown;
    try {
      body = await response.json();
    } catch {
      if (signal.aborted) throw new AgentApiError(`Agent API request timed out after ${this.timeoutMs} ms.`, true);
      if (response.ok) throw new AgentApiError('Malformed /api/message response: invalid JSON.', false);
      body = null;
    }
    if (!response.ok) {
      const detail = isRecord(body) && isRecord(body.error) && typeof body.error.message === 'string'
        ? body.error.message
        : isRecord(body) && typeof body.detail === 'string'
          ? body.detail
          : response.statusText || 'Unknown backend error';
      throw new AgentApiError(`Agent API HTTP ${response.status}: ${detail}`, [408, 429, 500, 502, 503, 504].includes(response.status));
    }
    return parseResponse(body);
  }
}

/** Explicit development fixture; never selected as a fallback after HTTP failure. */
export class MockAgentClient implements AgentClient {
  async sendMessage(request: AgentMessageRequest): Promise<AgentMessageResponse> {
    return {
      response_text: '[MOCK] Сообщение получено. Агент пока не подключён.',
      conversation_status: 'awaiting_user',
      state: { active_scenario: 'DEMO-SC01' },
      trace: {
        mode: 'mock',
        transcript: request.text,
        scenarios: [{ scenario_id: 'DEMO-SC01', name: 'Демо сценарий', confidence: 0.92 }],
        alternatives: [{ scenario_id: 'DEMO-SC02', name: 'Демо альтернатива', confidence: 0.31 }],
        reason: 'Демонстрационная трассировка. Реальная маршрутизация не выполнялась.',
        latency_ms: { router: 287, response: 170, total: 457 },
      },
    };
  }
}
