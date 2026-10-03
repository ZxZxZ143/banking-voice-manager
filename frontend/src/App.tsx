import { useCallback, useMemo, useRef, useState } from "react";
import {
  Activity,
  AudioWaveform,
  ChevronRight,
  CircleHelp,
  Headphones,
  LayoutDashboard,
  Phone,
  Route,
  ShieldAlert,
  TriangleAlert,
} from "lucide-react";
import { AnalyticsClient } from "./analytics/client";
import type { Filters, Session } from "./analytics/types";
import { ConversationRuntime } from "./runtime/ConversationRuntime";
import { HttpAgentClient, MockAgentClient } from "./services/agentClient";
import { BrowserTtsService } from "./services/tts/BrowserTtsService";
import { useHealth } from "./hooks/useHealth";
import { Button } from "./components/ui/button";
import { Separator } from "./components/ui/separator";
import { Badge } from "./components/ui/badge";
import { ConversationDemo } from "./components/dashboard/ConversationDemo";
import {
  AnomaliesScreen,
  JourneysScreen,
  LiveCallsScreen,
  OverviewScreen,
  RiskScreen,
  SessionsScreen,
} from "./components/dashboard/views";
import {
  NativeSelect,
  NativeSelectOption,
} from "./components/ui/native-select";
import { DemoBadge } from "./components/dashboard/shared";
import { SessionDetailSheet } from "./components/dashboard/SessionDetail";

const navigation = [
  { key: "overview", title: "Overview", icon: LayoutDashboard },
  { key: "live", title: "Live Calls", icon: Phone },
  { key: "sessions", title: "Sessions", icon: Headphones },
  { key: "risk", title: "Risk & Fraud", icon: ShieldAlert },
  { key: "anomalies", title: "Anomalies", icon: TriangleAlert },
  { key: "journeys", title: "Journeys", icon: Route },
  { key: "conversation", title: "Conversation Demo", icon: AudioWaveform },
] as const;
type Section = (typeof navigation)[number]["key"];
const mockMode =
  import.meta.env.DEV && import.meta.env.VITE_USE_MOCK_AGENT === "true";

export default function App() {
  const [section, setSection] = useState<Section>("overview");
  const detailOpener = useRef<HTMLElement | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [source, setSource] = useState<Filters["source"]>();
  const client = useMemo(
    () => new AnalyticsClient(undefined, 12000, source),
    [source],
  );
  const [tts] = useState(() => new BrowserTtsService());
  const [runtime] = useState(
    () =>
      new ConversationRuntime(
        mockMode ? new MockAgentClient() : new HttpAgentClient(),
        tts,
      ),
  );
  const { health, retry } = useHealth();
  const onSessions = useCallback((_sessions: Session[]) => {}, []);
  function navigate(next: Section) {
    if (section === "conversation" && next !== "conversation")
      void runtime.setVoiceInputEnabled(false);
    setSelected(null);
    setSection(next);
  }
  const props = {
    client,
    onSelect: (id: string) => {
      detailOpener.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      setSelected(id);
    },
    onSessions,
  };
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
      <a
        href="#main-content"
        className="sr-only z-50 rounded bg-white p-3 text-primary focus:not-sr-only focus:absolute"
      >
        Skip to content
      </a>
      <aside className="flex flex-col bg-slate-950 text-slate-200 lg:sticky lg:top-0 lg:h-screen">
        <div className="flex items-center gap-3 px-6 py-6">
          <div className="flex size-9 items-center justify-center rounded-lg bg-teal-300 text-slate-950">
            <AudioWaveform className="size-6" aria-hidden="true" />
          </div>
          <div>
            <div className="text-xl font-semibold tracking-tight text-white">
              Veyra<span className="text-teal-300">.</span>
            </div>
            <p className="text-[10px] font-medium uppercase tracking-[0.13em] text-slate-400">
              Supervisor console
            </p>
          </div>
        </div>
        <div className="px-6 pb-5 text-xs leading-relaxed text-slate-400">
          Financial Voice
          <br />
          Intelligence Platform
        </div>
        <nav
          aria-label="Supervisor navigation"
          className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible"
        >
          {navigation.map((item) => (
            <Button
              key={item.key}
              variant="ghost"
              className={`h-10 shrink-0 justify-start px-3 text-sm ${section === item.key ? "bg-teal-300/10 text-teal-200 hover:bg-teal-300/15 hover:text-teal-100" : "text-slate-400 hover:bg-slate-800 hover:text-white"}`}
              onClick={() => navigate(item.key)}
              aria-current={section === item.key ? "page" : undefined}
            >
              <item.icon className="mr-1 size-4" aria-hidden="true" />
              {item.title}
              {section === item.key && (
                <ChevronRight
                  className="ml-auto hidden size-3 lg:block"
                  aria-hidden="true"
                />
              )}
            </Button>
          ))}
        </nav>
        <div className="mt-auto hidden p-4 lg:block">
          <Separator className="mb-4 bg-slate-800" />
          <div className="flex items-center gap-2 text-xs">
            <span
              className={`size-2 rounded-full ${health.status === "ready" ? "bg-teal-300" : "bg-amber-300"}`}
              aria-hidden="true"
            />
            {health.status === "ready"
              ? "Backend connected"
              : health.status === "loading"
                ? "Checking backend"
                : "Backend unavailable"}
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
            Canonical backend events
            <br />
            Text + browser voice channels
          </p>
        </div>
      </aside>
      <div className="min-w-0">
        <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b bg-white px-5 py-3 lg:px-7">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>Workspace</span>
            <ChevronRight className="size-3" aria-hidden="true" />
            <span className="font-medium text-foreground">
              Finance supervision
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <NativeSelect
              aria-label="Source filter"
              value={source ?? ""}
              onChange={(event) => {
                setSource(
                  event.target.value === "runtime" ||
                    event.target.value === "synthetic_demo"
                    ? event.target.value
                    : undefined,
                );
                setSelected(null);
              }}
            >
              <NativeSelectOption value="">
                All sources · runtime + synthetic
              </NativeSelectOption>
              <NativeSelectOption value="runtime">
                Runtime only
              </NativeSelectOption>
              <NativeSelectOption value="synthetic_demo">
                Synthetic demo only
              </NativeSelectOption>
            </NativeSelect>
            {source === "synthetic_demo" && <DemoBadge />}
            <Badge variant="outline">Backend event data</Badge>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={retry}
              aria-label="Check backend connection"
            >
              <Activity className="size-4" />
            </Button>
            <div
              className="flex size-8 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold"
              aria-label="Supervisor workspace"
            >
              S
            </div>
          </div>
        </header>
        <main id="main-content" className="min-w-0 space-y-6 p-5 lg:p-7">
          <div key={source ?? "all"} className="space-y-6">
            {section === "overview" && <OverviewScreen {...props} />}
            {section === "live" && <LiveCallsScreen {...props} />}
            {section === "sessions" && <SessionsScreen {...props} />}
            {section === "risk" && <RiskScreen {...props} />}
            {section === "anomalies" && <AnomaliesScreen client={client} />}
            {section === "journeys" && <JourneysScreen {...props} />}
          </div>
          <div hidden={section !== "conversation"}>
            <ConversationDemo runtime={runtime} tts={tts} mockMode={mockMode} />
          </div>
          <footer className="flex flex-wrap items-center justify-between gap-3 border-t pt-4 text-[11px] text-muted-foreground">
            <span>Veyra · financial voice intelligence</span>
            <span className="flex items-center gap-1">
              <CircleHelp className="size-3" aria-hidden="true" />
              Signals support supervisor review
            </span>
          </footer>
        </main>
      </div>
      <SessionDetailSheet
        key={source ?? "all"}
        id={selected}
        client={client}
        close={() => setSelected(null)}
        returnFocus={() => detailOpener.current?.focus()}
        live={section === "live"}
        onSessions={onSessions}
      />
    </div>
  );
}
