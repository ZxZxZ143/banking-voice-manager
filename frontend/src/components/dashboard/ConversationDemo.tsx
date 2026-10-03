import { RiskPanel } from "../../components/security/SecurityPanels";
import { useSyncExternalStore } from "react";
import { ConversationPanel } from "../conversation/ConversationPanel";
import { TracePanel } from "../trace/TracePanel";
import { createTraceViewModel } from "../trace/traceViewModel";
import { TtsDebugPanel } from "../voice/TtsDebugPanel";
import type { ConversationRuntime } from "../../runtime/ConversationRuntime";
import type { BrowserTtsService } from "../../services/tts/BrowserTtsService";
import { Badge } from "../ui/badge";
export function ConversationDemo({
  runtime,
  tts,
  mockMode,
}: {
  runtime: ConversationRuntime;
  tts: BrowserTtsService;
  mockMode: boolean;
}) {
  const snapshot = useSyncExternalStore(runtime.subscribe, runtime.getSnapshot);
  const traceView = createTraceViewModel(snapshot);
  return (
    <div className="conversation-demo">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1>Conversation Demo</h1>
          <p className="muted">
            Web Assistant · Russian / Kazakh · original routing sandbox
          </p>
        </div>
        <Badge variant="outline">
          {mockMode ? "MOCK AGENT" : "HTTP AGENT"} · Browser TTS
        </Badge>
      </div>
      <div className="workspace">
        <ConversationPanel
          runtime={runtime}
          snapshot={snapshot}
          view={traceView}
        />
        <aside className="workspace-sidebar">
          <RiskPanel risk={snapshot.lastResponse?.risk} />
          <TracePanel view={traceView} />
        </aside>
      </div>
      <details className="developer-tools tts-tools">
        <summary>Инструменты разработчика · проверка голоса</summary>
        <TtsDebugPanel tts={tts} runtimeStatus={snapshot.runtimeStatus} />
      </details>
    </div>
  );
}
