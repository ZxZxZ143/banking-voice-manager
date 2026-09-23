import { useEffect, useState } from 'react';
import { getHealth } from '../api/client';
import type { HealthResponse } from '../types/contracts';

type HealthState =
  | { status: 'loading' }
  | { status: 'ready'; data: HealthResponse }
  | { status: 'error'; message: string };

export function useHealth() {
  const [health, setHealth] = useState<HealthState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setHealth({ status: 'loading' });
    getHealth(controller.signal).then(
      (data) => setHealth({ status: 'ready', data }),
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setHealth({
            status: 'error',
            message: error instanceof Error ? error.message : 'Не удалось проверить backend.',
          });
        }
      },
    );
    return () => controller.abort();
  }, [attempt]);

  return { health, retry: () => setAttempt((value) => value + 1) };
}
