import { useEffect, useState } from "react";
import { Activity, Phone, ShieldAlert } from "lucide-react";
import { AnalyticsClient } from "../../analytics/client";
import { useAnalytics } from "../../analytics/useAnalytics";
import type {
  Anomaly,
  Filters,
  Overview,
  RiskAnalytics,
  Session,
} from "../../analytics/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../ui/card";
import { Alert, AlertDescription } from "../ui/alert";
import { Badge } from "../ui/badge";
import { Input } from "../ui/input";
import { NativeSelect, NativeSelectOption } from "../ui/native-select";
import { Button } from "../ui/button";
import {
  DataState,
  DemoBadge,
  Empty,
  MetricCard,
  OpenSession,
  RankedList,
  RiskBadge,
  StatusBadge,
  Toolbar,
} from "./shared";
import { activity, count, date, latency, riskLabels } from "./presentation";
import { riskLevels } from "../../analytics/types";
import { SessionTable } from "./SessionTable";
import { Journey } from "./Journey";

type Props = {
  client: AnalyticsClient;
  onSelect(id: string): void;
  onSessions(sessions: Session[]): void;
};
function useDemo(sessions: Session[] | undefined, notify: Props["onSessions"]) {
  useEffect(() => {
    if (sessions) notify(sessions);
  }, [sessions, notify]);
}
export function OverviewView({
  data,
  anomalies,
  sessions,
  onSelect,
}: {
  data: Overview;
  anomalies: Anomaly[];
  sessions: Session[];
  onSelect(id: string): void;
}) {
  const metrics = [
    ["Total sessions", count(data.total_sessions), "Retained conversations"],
    [
      "Active sessions",
      count(data.active_sessions),
      "Activity within 5 minutes",
    ],
    [
      "Recent sessions",
      count(data.recent_sessions),
      "Last event within 5 minutes",
    ],
    [
      "High risk signals",
      count(data.risk.high_risk_sessions),
      "High + critical sessions",
    ],
    ["Handoffs", count(data.handoff_count), "Operator attention requested"],
    [
      "Voice sessions",
      count(data.sessions_by_channel.voice),
      "Voice conversation channel",
    ],
    [
      "Text sessions",
      count(data.sessions_by_channel.text),
      "Text conversation channel",
    ],
    [
      "Clarification rate",
      data.clarification_rate == null
        ? "—"
        : `${(data.clarification_rate * 100).toFixed(1)}%`,
      "Sessions with clarification",
    ],
    [
      "Avg. Agent latency",
      latency(data.latency.agent_ms?.average_ms),
      "Backend message processing",
    ],
    [
      "Avg. TTS latency",
      latency(data.latency.tts_ms?.average_ms),
      "Audio synthesis readiness",
    ],
  ];
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        Source sessions: runtime {data.sources.runtime ?? 0} · synthetic{" "}
        {data.sources.synthetic_demo ?? 0} · mixed {data.sources.mixed ?? 0}
        {(data.sources.synthetic_demo ?? 0) + (data.sources.mixed ?? 0) > 0 && (
          <DemoBadge
            mixed={(data.sources.runtime ?? 0) + (data.sources.mixed ?? 0) > 0}
          />
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {metrics.map(([label, value, note], i) => (
          <MetricCard
            key={label}
            label={label}
            value={value}
            note={note}
            accent={i === 0}
          />
        ))}
      </div>
      {data.total_sessions === 0 && (
        <Empty
          title="No conversations yet"
          description="Start the Conversation Demo. The dashboard reads canonical backend events; it never fills empty metrics with synthetic production numbers."
        />
      )}
      {(data.evicted_events ?? 0) > 0 && (
        <Alert>
          <AlertDescription>
            {count(data.evicted_events)} older events were evicted. These
            metrics describe retained history.
          </AlertDescription>
        </Alert>
      )}
      <div className="grid gap-5 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Conversation intent</CardTitle>
            <CardDescription>Sessions by observed scenario</CardDescription>
          </CardHeader>
          <CardContent>
            <RankedList items={data.sessions_by_scenario} />
            <h3 className="mt-5 mb-3 text-sm font-semibold">Sales outcomes</h3>
            <RankedList items={data.sales_outcomes} />
            <p className="mt-3 text-xs text-muted-foreground">
              Insurance completed: {count(data.insurance_completed)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Response performance</CardTitle>
            <CardDescription>
              Measured averages · missing data stays unknown
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="space-y-3">
              {[
                ["Endpointing", "endpointing_ms"],
                ["STT final", "stt_final_ms"],
                ["Agent", "agent_ms"],
                ["TTS", "tts_ms"],
                [
                  "Speech end → audio submission",
                  "speech_end_to_playback_submit_ms",
                ],
                [
                  "Speech end → playback complete",
                  "speech_end_to_playback_complete_ms",
                ],
              ].map(([label, key]) => (
                <div
                  key={key}
                  className="flex justify-between gap-3 border-b pb-2 text-xs last:border-0"
                >
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="shrink-0 font-semibold tabular-nums">
                    {latency(data.latency[key]?.average_ms)}
                    <span className="ml-1 font-normal text-muted-foreground">
                      ({count(data.latency[key]?.samples)})
                    </span>
                  </dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <div className="flex justify-between gap-3">
              <CardTitle className="text-base">Unusual volume</CardTitle>
              <Badge variant="secondary">{anomalies.length}</Badge>
            </div>
            <CardDescription>
              Count deviations for supervisor review
            </CardDescription>
          </CardHeader>
          <CardContent>
            {anomalies.length ? (
              <ul className="space-y-4">
                {anomalies.slice(0, 3).map((a) => (
                  <li key={a.id} className="border-b pb-3 last:border-0">
                    <p className="text-sm font-medium">
                      {a.key.replaceAll("_", " ")}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {count(a.current_count)} events · expected{" "}
                      {count(a.baseline_expected_count)} ·{" "}
                      {a.ratio == null
                        ? "no baseline ratio"
                        : `${a.ratio.toFixed(1)}× baseline`}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                No abnormal increases meet the configured thresholds.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
      <div className="space-y-3">
        <div className="flex justify-between">
          <h2 className="text-base font-semibold">Recent conversations</h2>
          <span className="text-xs text-muted-foreground">
            Most recent 5 sessions
          </span>
        </div>
        <SessionTable sessions={sessions} onSelect={onSelect} />
      </div>
    </>
  );
}
export function OverviewScreen({ client, onSelect, onSessions }: Props) {
  const resource = useAnalytics(
    "overview",
    async (signal) => {
      const [overview, anomalies, sessions] = await Promise.all([
        client.overview({}, signal),
        client.anomalies({ limit: 20 }, signal),
        client.sessions({ limit: 5 }, signal),
      ]);
      return {
        overview,
        anomalies: anomalies.anomalies,
        sessions: sessions.sessions,
        history: anomalies.history_status,
      };
    },
    10000,
  );
  useDemo(resource.data?.sessions, onSessions);
  return (
    <div className="space-y-6">
      <Toolbar
        title="Supervisor overview"
        description="Conversation intelligence, risk signals and operational performance."
        resource={resource}
        refresh={resource.refresh}
      />
      <DataState resource={resource} retry={resource.refresh}>
        {(data) => (
          <OverviewView
            data={data.overview}
            anomalies={data.anomalies}
            sessions={data.sessions}
            onSelect={onSelect}
          />
        )}
      </DataState>
    </div>
  );
}
export function LiveCallCards({
  sessions,
  onSelect,
}: {
  sessions: Session[];
  onSelect(id: string): void;
}) {
  if (!sessions.length)
    return (
      <Empty
        title="No recent voice sessions"
        description="Persisted voice sessions with activity in the last 30 minutes appear here. Start browser voice in Conversation Demo."
      />
    );
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {sessions.map((session) => (
        <Card
          key={session.session_id}
          className={session.active ? "border-teal-200" : ""}
        >
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Phone className="size-4 text-teal-700" aria-hidden="true" />
                <CardTitle className="text-sm">Voice session</CardTitle>
              </div>
              <StatusBadge
                status={session.status}
                active={session.active}
                handoff={session.handoff}
              />
            </div>
            <CardDescription>
              {session.active
                ? "Recent activity · no end event"
                : "Recent voice session · closed or inactive"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <OpenSession id={session.session_id} onSelect={onSelect} />
              <RiskBadge level={session.risk_level} />
            </div>
            {(session.source === "synthetic_demo" ||
              session.source === "mixed") && (
              <DemoBadge mixed={session.source === "mixed"} />
            )}
            <p className="text-xs text-muted-foreground">
              Source: {session.source} · channel: {session.channel}
            </p>
            <div>
              <span className="text-xs text-muted-foreground">
                Last scenario
              </span>
              <p className="mt-1 font-semibold">
                {session.last_scenario?.replaceAll("_", " ") ??
                  "Awaiting scenario"}
              </p>
            </div>
            {session.risk_signals.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {session.risk_signals.map((signal) => (
                  <Badge key={signal} variant="secondary">
                    {signal.replaceAll("_", " ")}
                  </Badge>
                ))}
              </div>
            )}
            <dl className="grid grid-cols-2 gap-3 border-t pt-3 text-xs">
              <div>
                <dt className="text-muted-foreground">Started</dt>
                <dd className="mt-1">{date(session.started_at)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Last activity</dt>
                <dd className="mt-1">{activity(session.latest_event_at)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Agent latency</dt>
                <dd className="mt-1 font-semibold">
                  {latency(session.latest_latency.agent_ms)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">TTS latency</dt>
                <dd className="mt-1 font-semibold">
                  {latency(session.latest_latency.tts_ms)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Duration</dt>
                <dd className="mt-1">
                  {session.total_duration_ms == null
                    ? "Not completed / unavailable"
                    : `${(session.total_duration_ms / 1000).toFixed(1)} s`}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Conversation status</dt>
                <dd className="mt-1">{session.status.replaceAll("_", " ")}</dd>
              </div>
            </dl>
            <Button
              variant="outline"
              className="w-full"
              onClick={() => onSelect(session.session_id)}
            >
              Inspect call session
            </Button>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
export function LiveCallsScreen({ client, onSelect, onSessions }: Props) {
  const resource = useAnalytics(
    "live-calls",
    (signal) =>
      client.sessions(
        {
          channel: "voice",
          from: new Date(Date.now() - 30 * 60000).toISOString(),
          limit: 100,
        },
        signal,
      ),
    3000,
  );
  useDemo(resource.data?.sessions, onSessions);
  return (
    <div className="space-y-6">
      <Toolbar
        title="Live calls"
        description="Voice session activity from the last 30 minutes. PSTN metadata is unavailable. Active is an event-recency heuristic, not provider presence."
        resource={resource}
        refresh={resource.refresh}
      >
        <Badge variant="outline">
          <Activity className="size-3 text-teal-700" />
          Polling every 3s
        </Badge>
      </Toolbar>
      <DataState resource={resource} retry={resource.refresh}>
        {(page) => (
          <LiveCallCards sessions={page.sessions} onSelect={onSelect} />
        )}
      </DataState>
    </div>
  );
}
export function SessionsScreen({ client, onSelect, onSessions }: Props) {
  const [filters, setFilters] = useState<Filters>({ limit: 100, offset: 0 });
  const [search, setSearch] = useState("");
  const [scenario, setScenario] = useState("");
  const assistants = useAnalytics("session-assistants", (signal) =>
    client.scenarios({}, signal),
  );
  const resource = useAnalytics(
    `sessions:${JSON.stringify(filters)}`,
    (signal) => client.sessions(filters, signal),
  );
  useDemo(resource.data?.sessions, onSessions);
  return (
    <div className="space-y-6">
      <Toolbar
        title="Conversation sessions"
        description="Search retained backend conversations across the web and voice channels."
        resource={resource}
        refresh={resource.refresh}
      />
      <Card>
        <CardContent className="pt-0">
          <form
            className="grid items-end gap-3 sm:grid-cols-2 xl:grid-cols-5"
            onSubmit={(event) => {
              event.preventDefault();
              setFilters((f) => ({
                ...f,
                offset: 0,
                session_id: search.trim() || undefined,
                scenario: scenario.trim() || undefined,
              }));
            }}
          >
            <label className="space-y-2 text-xs font-medium">
              Channel
              <NativeSelect
                aria-label="Channel filter"
                value={filters.channel ?? ""}
                onChange={(e) =>
                  setFilters((f) => ({
                    ...f,
                    offset: 0,
                    channel:
                      e.target.value === "text" || e.target.value === "voice"
                        ? e.target.value
                        : undefined,
                  }))
                }
              >
                <NativeSelectOption value="">All channels</NativeSelectOption>
                <NativeSelectOption value="text">Text</NativeSelectOption>
                <NativeSelectOption value="voice">Voice</NativeSelectOption>
              </NativeSelect>
            </label>
            <label className="space-y-2 text-xs font-medium">
              Risk
              <NativeSelect
                aria-label="Risk filter"
                value={filters.risk_level ?? ""}
                onChange={(e) =>
                  setFilters((f) => ({
                    ...f,
                    offset: 0,
                    risk_level: riskLevels.find(
                      (level) => level === e.target.value,
                    ),
                  }))
                }
              >
                <NativeSelectOption value="">
                  All risk levels
                </NativeSelectOption>
                {riskLevels.map((level) => (
                  <NativeSelectOption key={level} value={level}>
                    {riskLabels[level]}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </label>
            <label className="space-y-2 text-xs font-medium">
              Activity
              <NativeSelect
                aria-label="Activity filter"
                value={
                  filters.active === true
                    ? "active"
                    : filters.from
                      ? "recent"
                      : "all"
                }
                onChange={(e) =>
                  setFilters((f) => ({
                    ...f,
                    offset: 0,
                    active: e.target.value === "active" ? true : undefined,
                    from:
                      e.target.value === "recent"
                        ? new Date(Date.now() - 30 * 60000).toISOString()
                        : undefined,
                  }))
                }
              >
                <NativeSelectOption value="all">
                  All retained
                </NativeSelectOption>
                <NativeSelectOption value="active">
                  Active (last 5m)
                </NativeSelectOption>
                <NativeSelectOption value="recent">
                  Recent (last 30m)
                </NativeSelectOption>
              </NativeSelect>
            </label>
            <label className="space-y-2 text-xs font-medium">
              Exact session ID
              <Input
                maxLength={128}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Session identifier"
              />
            </label>
            <label className="space-y-2 text-xs font-medium">
              Assistant
              <Input
                aria-label="Assistant filter"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
                disabled={assistants.loading}
                list="observed-assistants"
              />
              <datalist id="observed-assistants">
                {assistants.data?.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.count} sessions
                  </option>
                ))}
              </datalist>
              {assistants.error && (
                <span className="block text-xs text-destructive">
                  Assistant suggestions unavailable. Enter a supported assistant
                  ID.
                </span>
              )}
            </label>
            <div className="flex gap-2 sm:col-span-2 xl:col-span-5">
              <Button type="submit" size="sm">
                Apply search
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  setFilters({ limit: 100 });
                  setSearch("");
                  setScenario("");
                }}
              >
                Clear filters
              </Button>
              <span className="ml-auto self-center text-xs text-muted-foreground">
                Up to 100 sessions
              </span>
            </div>
          </form>
        </CardContent>
      </Card>
      <DataState resource={resource} retry={resource.refresh}>
        {(page) => (
          <>
            <SessionTable sessions={page.sessions} onSelect={onSelect} />
            <Pager
              page={page}
              change={(offset) => setFilters((f) => ({ ...f, offset }))}
            />
          </>
        )}
      </DataState>
    </div>
  );
}
export function RiskView({
  data,
  sessions,
  onSelect,
}: {
  data: RiskAnalytics;
  sessions: Session[];
  onSelect(id: string): void;
}) {
  return (
    <>
      <Alert>
        <ShieldAlert className="size-4" />
        <AlertDescription>
          AI-generated risk signals. Review the conversation and supporting
          evidence before taking action.
        </AlertDescription>
      </Alert>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {riskLevels.map((level) => (
          <MetricCard
            key={level}
            label={riskLabels[level]}
            value={count(data.levels[level])}
            note={
              level === "unknown"
                ? "No Agent risk data available"
                : "Highest observed level per session"
            }
          />
        ))}
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Observed risk signals</CardTitle>
            <CardDescription>
              Unique session counts per Agent-produced signal
            </CardDescription>
          </CardHeader>
          <CardContent>
            <RankedList items={data.top_signals} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Associated scenarios</CardTitle>
            <CardDescription>
              Scenarios observed in high / critical sessions
            </CardDescription>
          </CardHeader>
          <CardContent>
            <RankedList items={data.high_risk_scenarios} />
            <h3 className="mt-5 mb-3 text-sm font-semibold">
              Advisory case types
            </h3>
            <RankedList items={data.fraud_case_types} />
          </CardContent>
        </Card>
      </div>
      <div className="space-y-3">
        <h2 className="font-semibold">
          High / critical sessions{" "}
          <span className="font-normal text-muted-foreground">
            · {count(data.high_risk_sessions)} total
          </span>
        </h2>
        <p className="text-xs text-muted-foreground">
          Up to 50 high and 50 critical sessions shown.
        </p>
        <SessionTable sessions={sessions} onSelect={onSelect} />
      </div>
    </>
  );
}
export function RiskScreen({ client, onSelect, onSessions }: Props) {
  const resource = useAnalytics("risk", async (signal) => {
    const [risk, high, critical] = await Promise.all([
      client.risk({}, signal),
      client.sessions({ risk_level: "high", limit: 50 }, signal),
      client.sessions({ risk_level: "critical", limit: 50 }, signal),
    ]);
    return { risk, sessions: [...critical.sessions, ...high.sessions] };
  });
  useDemo(resource.data?.sessions, onSessions);
  return (
    <div className="space-y-6">
      <Toolbar
        title="Risk & fraud monitoring"
        description="Agent-produced signals for supervisor review. Absence of risk data stays unknown."
        resource={resource}
        refresh={resource.refresh}
      />
      <DataState resource={resource} retry={resource.refresh}>
        {(data) => (
          <RiskView
            data={data.risk}
            sessions={data.sessions}
            onSelect={onSelect}
          />
        )}
      </DataState>
    </div>
  );
}
export function AnomalyCards({ anomalies }: { anomalies: Anomaly[] }) {
  if (!anomalies.length)
    return (
      <Empty
        title="No unusual volume detected"
        description="No observed count increase currently meets the backend's configured baseline, multiplier and minimum-volume thresholds."
      />
    );
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {anomalies.map((anomaly) => (
        <Card key={anomaly.id}>
          <CardHeader>
            <div className="flex flex-wrap justify-between gap-3">
              <CardTitle className="text-base">
                {anomaly.key.replaceAll("_", " ")}
              </CardTitle>
              <Badge
                variant="outline"
                className={
                  anomaly.severity === "high"
                    ? "border-red-200 bg-red-50 text-red-800"
                    : anomaly.severity === "unknown"
                      ? "text-muted-foreground"
                      : "border-amber-200 bg-amber-50 text-amber-900"
                }
              >
                {anomaly.severity} severity
              </Badge>
            </div>
            <CardDescription>
              {anomaly.metric.replaceAll("_", " ")} · anomalous increase ·{" "}
              {anomaly.source}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="grid grid-cols-3 gap-3 rounded-lg bg-muted/50 p-3">
              {[
                ["Current", count(anomaly.current_count)],
                ["Historical total", count(anomaly.baseline_count)],
                [
                  "Ratio",
                  anomaly.ratio == null
                    ? "No baseline"
                    : `${anomaly.ratio.toFixed(1)}×`,
                ],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="mt-1 text-xl font-semibold tabular-nums">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="text-sm">{anomaly.explanation}</p>
            <div className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              <p>
                Expected per equivalent window:{" "}
                {count(anomaly.baseline_expected_count)}
              </p>
              <p>
                Current:{" "}
                {date(
                  typeof anomaly.window.current_from === "string"
                    ? anomaly.window.current_from
                    : null,
                )}{" "}
                →{" "}
                {date(
                  typeof anomaly.window.current_to === "string"
                    ? anomaly.window.current_to
                    : null,
                )}
              </p>
              <p>
                Baseline:{" "}
                {date(
                  typeof anomaly.window.baseline_from === "string"
                    ? anomaly.window.baseline_from
                    : null,
                )}{" "}
                →{" "}
                {date(
                  typeof anomaly.window.baseline_to === "string"
                    ? anomaly.window.baseline_to
                    : null,
                )}
              </p>
              {anomaly.partial_history && (
                <p className="font-medium text-amber-800">
                  Partial history: older events were evicted.
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
export function AnomaliesScreen({ client }: Pick<Props, "client">) {
  const resource = useAnalytics("anomalies", (signal) =>
    client.anomalies({ limit: 100 }, signal),
  );
  return (
    <div className="space-y-6">
      <Toolbar
        title="Volume anomalies"
        description="Explainable count deviations from historical baseline. These signals do not establish cause or intent."
        resource={resource}
        refresh={resource.refresh}
      />
      <DataState resource={resource} retry={resource.refresh}>
        {(page) => (
          <>
            <p className="text-sm text-muted-foreground">
              {page.history_status === "insufficient_history"
                ? "Insufficient baseline history. No anomaly is emitted."
                : "Observed baseline available. Sources are evaluated separately."}
            </p>
            <AnomalyCards anomalies={page.anomalies} />
          </>
        )}
      </DataState>
    </div>
  );
}
export function JourneysScreen({ client, onSelect, onSessions }: Props) {
  const [offset, setOffset] = useState(0);
  const [journeyOffset, setJourneyOffset] = useState(0);
  const sessions = useAnalytics(`journey-sessions:${offset}`, (signal) =>
    client.sessions({ limit: 100, offset }, signal),
  );
  const [selected, setSelected] = useState<string | null>(null);
  const journey = useAnalytics(
    `journey:${selected}:${journeyOffset}`,
    (signal) =>
      selected
        ? client.journey(selected, signal, { offset: journeyOffset })
        : Promise.resolve({
            stages: [],
            total: 0,
            limit: 100,
            offset: 0,
            next_offset: null,
          }),
  );
  useDemo(sessions.data?.sessions, onSessions);
  return (
    <div className="space-y-6">
      <Toolbar
        title="Customer intent journeys"
        description="An event-derived view of selected assistants and meaningful conversation transitions."
        resource={sessions}
        refresh={sessions.refresh}
      />
      <div className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Choose a conversation</CardTitle>
          </CardHeader>
          <CardContent>
            <DataState resource={sessions} retry={sessions.refresh}>
              {(page) =>
                page.sessions.length ? (
                  <div className="max-h-[65vh] space-y-2 overflow-y-auto">
                    {page.sessions.map((session) => (
                      <Button
                        key={session.session_id}
                        variant={
                          selected === session.session_id
                            ? "secondary"
                            : "ghost"
                        }
                        className="h-auto w-full items-start justify-start whitespace-normal p-3 text-left"
                        onClick={() => {
                          setSelected(session.session_id);
                          setJourneyOffset(0);
                        }}
                      >
                        <div className="min-w-0">
                          <div className="truncate font-mono text-xs">
                            {session.session_id}
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {session.channel} ·{" "}
                            {session.last_scenario?.replaceAll("_", " ") ??
                              "No scenario"}
                          </div>
                        </div>
                      </Button>
                    ))}
                  </div>
                ) : (
                  <Empty
                    title="No journeys yet"
                    description="Start a conversation to create event-derived journey stages."
                  />
                )
              }
            </DataState>
            {sessions.data && <Pager page={sessions.data} change={setOffset} />}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="text-base">Intent timeline</CardTitle>
              {selected && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onSelect(selected)}
                >
                  Session detail
                </Button>
              )}
            </div>
            <CardDescription>
              Original turn / sequence order · safe lifecycle and result events
            </CardDescription>
          </CardHeader>
          <CardContent>
            {selected ? (
              <DataState resource={journey} retry={journey.refresh}>
                {(page) => (
                  <>
                    <Journey stages={page.stages} />
                    <Pager page={page} change={setJourneyOffset} />
                  </>
                )}
              </DataState>
            ) : (
              <Empty
                title="Select a conversation"
                description="Follow its selected assistants, results, risk, handoff and completion stages."
              />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function Pager({
  page,
  change,
}: {
  page: {
    total: number;
    limit: number;
    offset: number;
    next_offset: number | null;
  };
  change(offset: number): void;
}) {
  return (
    <div className="mt-4 flex items-center justify-between gap-3 text-xs">
      <span>
        {page.total} total · offset {page.offset}
      </span>
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={page.offset === 0}
          onClick={() => change(Math.max(0, page.offset - page.limit))}
        >
          Previous page
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={page.next_offset === null}
          onClick={() => change(page.next_offset!)}
        >
          Next page
        </Button>
      </div>
    </div>
  );
}
