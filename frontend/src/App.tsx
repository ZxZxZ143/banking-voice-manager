import { useState, useSyncExternalStore } from 'react';
import { ConversationPanel } from './components/conversation/ConversationPanel';
import { TracePanel } from './components/trace/TracePanel';
import { createTraceViewModel } from './components/trace/traceViewModel';
import { TtsDebugPanel } from './components/voice/TtsDebugPanel';
import { useHealth } from './hooks/useHealth';
import { ConversationRuntime } from './runtime/ConversationRuntime';
import { HttpAgentClient, MockAgentClient } from './services/agentClient';
import { BrowserTtsService } from './services/tts/BrowserTtsService';

const mockMode = import.meta.env.DEV && import.meta.env.VITE_USE_MOCK_AGENT === 'true';

export default function App() {
  const [tts] = useState(() => new BrowserTtsService());
  const [runtime] = useState(() => new ConversationRuntime(
    mockMode ? new MockAgentClient() : new HttpAgentClient(),
    tts,
  ));
  const snapshot = useSyncExternalStore(runtime.subscribe, runtime.getSnapshot);
  const traceView = createTraceViewModel(snapshot);
  const { health, retry } = useHealth();

  return (
    <main>
      <header>
        <h1>Voice Router</h1>
        <p>Saqta Insurance · интеграционный стенд</p>
        <p className="muted">Agent: {mockMode ? 'MOCK (без маршрутизации)' : 'HTTP /api/message'} · TTS: голос браузера</p>
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
        <ConversationPanel runtime={runtime} snapshot={snapshot} view={traceView} />
        <TracePanel view={traceView} />
      </div>
      <details className="developer-tools tts-tools">
        <summary>Инструменты разработчика · проверка голоса</summary>
        <TtsDebugPanel tts={tts} runtimeStatus={snapshot.runtimeStatus} />
      </details>
    </main>
  );
}
