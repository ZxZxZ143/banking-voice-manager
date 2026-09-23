import type { HealthResponse, TextTurnRequest } from '../types/contracts';

const timeoutMs = 10_000;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      signal: init?.signal
        ? AbortSignal.any([init.signal, AbortSignal.timeout(timeoutMs)])
        : AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    if (init?.signal?.aborted) throw error;
    throw new Error('Backend недоступен или не ответил за 10 секунд. Запустите его на 127.0.0.1:8000.');
  }

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (isObject(body) && isObject(body.error) && typeof body.error.message === 'string') {
      const code = typeof body.error.code === 'string' ? body.error.code : 'api_error';
      throw new Error(`${response.status} · ${code}: ${body.error.message}`);
    }
    throw new Error(`Backend вернул HTTP ${response.status}. Проверьте запрос и журнал backend.`);
  }
  return body;
}

export async function getHealth(signal: AbortSignal): Promise<HealthResponse> {
  const body = await request('/health', { signal });
  if (
    !isObject(body) || body.status !== 'ok' || body.service !== 'voice-router'
    || body.mode !== 'foundation' || !isObject(body.starter_kit)
    || !['scenarios', 'system_intents', 'actions', 'dev_utterances'].every(
      (key) => isObject(body.starter_kit)
        && typeof body.starter_kit[key] === 'number'
        && Number.isInteger(body.starter_kit[key])
        && body.starter_kit[key] >= 0,
    )
  ) {
    throw new Error('Backend вернул неожиданный формат /health. Проверьте совместимость API.');
  }
  return body as unknown as HealthResponse;
}

/** The foundation endpoint returns 501; no assistant response contract exists yet. */
export async function submitTextTurn(turn: TextTurnRequest): Promise<void> {
  await request('/api/v1/turns/text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(turn),
  });
  throw new Error('API вернул успешный ответ, но обработка результата ещё не подключена в интерфейсе.');
}
