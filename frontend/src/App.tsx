import { useState, useSyncExternalStore } from 'react';
import { ConversationPanel } from './components/conversation/ConversationPanel';
import { TracePanel } from './components/trace/TracePanel';
import { useHealth } from './hooks/useHealth';
import { ConversationRuntime } from './runtime/ConversationRuntime';
import { HttpAgentClient, MockAgentClient } from './services/agentClient';
import { NoopTtsService } from './services/tts';

const mockMode = import.meta.env.DEV && import.meta.env.VITE_USE_MOCK_AGENT === 'true';

export default function App() {
  const [runtime] = useState(() => new ConversationRuntime(
    mockMode ? new MockAgentClient() : new HttpAgentClient(),
    new NoopTtsService(),
  ));
  const snapshot = useSyncExternalStore(runtime.subscribe, runtime.getSnapshot);
  const { health, retry } = useHealth();

  return (
    <main>
      <header>
        <h1>Voice Router</h1>
        <p>Saqta Insurance · интеграционный стенд</p>
        <p className="muted">Agent: {mockMode ? 'MOCK (без маршрутизации)' : 'HTTP /api/message'} · TTS: без звука</p>
      </header>
      <section className="health" aria-label="Состояние backend">
        <div role="status" aria-live="polite">
          {health.status === 'loading' && <p>Проверяем backend…</p>}
          {health.status === 'error' && <p className="error">{health.message}</p>}
          {health.status === 'ready' && <p>Backend доступен · сценариев: {health.data.starter_kit.scenarios}</p>}
        </div>
        <button type="button" onClick={retry} disabled={health.status === 'loading'}>
          Проверить соединение
        </button>
      </section>
      <div className="workspace">
        <ConversationPanel runtime={runtime} snapshot={snapshot} />
        <TracePanel trace={snapshot.latestTrace} />
      </div>
    </main>
  );
}
