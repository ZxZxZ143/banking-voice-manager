import { useState } from 'react';
import { ConversationPanel } from './components/conversation/ConversationPanel';
import { TracePanel } from './components/trace/TracePanel';
import { useHealth } from './hooks/useHealth';

export default function App() {
  const [sessionId] = useState(() => crypto.randomUUID());
  const { health, retry } = useHealth();

  return (
    <main>
      <header>
        <h1>Voice Router</h1>
        <p>Техническая основа · Saqta Insurance · учебные данные</p>
      </header>
      <section className="health" aria-label="Состояние backend">
        <div role="status" aria-live="polite">
          {health.status === 'loading' && <p>Проверяем backend…</p>}
          {health.status === 'error' && <p className="error">{health.message}</p>}
          {health.status === 'ready' && (
            <p>Backend доступен · foundation · загружено сценариев: {health.data.starter_kit.scenarios},
              действий: {health.data.starter_kit.actions},
              тестовых фраз: {health.data.starter_kit.dev_utterances}.</p>
          )}
        </div>
        <button type="button" onClick={retry} disabled={health.status === 'loading'}>
          Проверить соединение
        </button>
      </section>
      <div className="workspace">
        <ConversationPanel sessionId={sessionId} />
        <TracePanel trace={null} />
      </div>
    </main>
  );
}
