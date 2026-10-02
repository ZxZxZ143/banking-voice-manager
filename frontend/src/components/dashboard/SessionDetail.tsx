import { useEffect } from "react";
import { Headphones } from "lucide-react";
import type { Session, SessionDetail } from "../../analytics/types";
import { AnalyticsClient } from "../../analytics/client";
import { useAnalytics } from "../../analytics/useAnalytics";
import { text } from "../../analytics/parse";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "../ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Alert, AlertDescription } from "../ui/alert";
import { Separator } from "../ui/separator";
import { Button } from "../ui/button";
import { DataState, DemoBadge, Empty, RiskBadge, StatusBadge } from "./shared";
import { Journey } from "./Journey";
import { count, date, latency } from "./presentation";

export function DetailContent({
  detail,
  initialTab = "summary",
}: {
  detail: SessionDetail;
  initialTab?: string;
}) {
  const session = detail.summary;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        <Badge variant="secondary">{session.channel}</Badge>
        <RiskBadge level={session.risk_level} />
        <StatusBadge
          status={session.status}
          active={session.active}
          handoff={session.handoff}
        />
        {(session.provider_metadata.demo === true ||
          session.session_id.startsWith("DEMO-")) && <DemoBadge />}
      </div>
      {session.partial_history && (
        <Alert>
          <AlertDescription>
            Partial retained history. The original session start or earlier
            events are unavailable.
          </AlertDescription>
        </Alert>
      )}
      <Tabs defaultValue={initialTab}>
        <TabsList className="w-full">
          <TabsTrigger value="summary">Summary</TabsTrigger>
          <TabsTrigger value="journey">Journey</TabsTrigger>
          <TabsTrigger value="timeline">Timeline & trace</TabsTrigger>
        </TabsList>
        <TabsContent value="summary" className="mt-5 space-y-5">
          <dl className="grid grid-cols-2 gap-4 text-sm">
            {[
              ["Started", date(session.started_at)],
              ["Last activity", date(session.latest_event_at)],
              ["Language", session.language ?? "Not supplied"],
              ["Turns", count(session.turn_count)],
              ["Clarifications", count(session.clarification_count)],
              ["Handoff", session.handoff ? "Requested" : "Not recorded"],
              [
                "Duration",
                session.total_duration_ms == null
                  ? "Not available"
                  : `${(session.total_duration_ms / 1000).toFixed(1)} s`,
              ],
              [
                "Completed",
                session.completed ? "Normal session closure" : "Not recorded",
              ],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="mt-1 font-medium">{value}</dd>
              </div>
            ))}
          </dl>
          <Separator />
          <div className="space-y-2">
            <h3 className="text-sm font-semibold">Scenario history</h3>
            <div className="flex flex-wrap gap-1">
              {session.scenarios.length ? (
                session.scenarios.map((scenario) => (
                  <Badge key={scenario} variant="secondary">
                    {scenario.replaceAll("_", " ")}
                  </Badge>
                ))
              ) : (
                <p className="text-sm text-muted-foreground">
                  No selected scenarios.
                </p>
              )}
            </div>
          </div>
          <div className="space-y-2">
            <h3 className="text-sm font-semibold">AI-generated risk signals</h3>
            <RiskBadge level={session.risk_level} />
            <ul className="space-y-1 text-sm">
              {session.risk_signals.map((signal) => (
                <li key={signal}>{signal.replaceAll("_", " ")}</li>
              ))}
            </ul>
            {!session.risk_signals.length && (
              <p className="text-xs text-muted-foreground">
                No signals supplied by Agent.
              </p>
            )}
          </div>
          {session.handoff && (
            <Alert>
              <Headphones className="size-4" />
              <AlertDescription>
                Operator attention requested. This state does not verify that a
                live transfer occurred.
              </AlertDescription>
            </Alert>
          )}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Latency summary</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="space-y-3 text-sm">
                {[
                  ["Average Agent", session.average_agent_ms],
                  ["Average TTS", session.average_tts_ms],
                  ["Latest endpointing", session.latest_latency.endpointing_ms],
                  ["Latest STT final", session.latest_latency.stt_final_ms],
                  [
                    "Speech end → audio submission",
                    session.latest_latency.speech_end_to_playback_submit_ms,
                  ],
                  [
                    "Speech end → playback complete",
                    session.latest_latency.speech_end_to_playback_complete_ms,
                  ],
                  [
                    "STT final → playback complete",
                    session.latest_latency.final_to_playback_complete_ms,
                  ],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-3">
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="shrink-0 text-xs font-semibold tabular-nums">
                      {latency(typeof value === "number" ? value : null)}
                    </dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>
          {session.channel === "phone" && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold">Provider correlation</h3>
              <dl className="space-y-2 font-mono text-xs">
                {Object.entries(session.provider_metadata)
                  .filter(([key]) =>
                    [
                      "provider",
                      "call_uuid",
                      "call_id",
                      "call_sid",
                      "stream_sid",
                    ].includes(key),
                  )
                  .map(([key, value]) => (
                    <div key={key}>
                      <dt className="text-muted-foreground">{key}</dt>
                      <dd className="mt-1 break-all">{String(value)}</dd>
                    </div>
                  ))}
              </dl>
            </div>
          )}
        </TabsContent>
        <TabsContent value="journey" className="mt-5">
          <Journey stages={detail.journey} />
        </TabsContent>
        <TabsContent value="timeline" className="mt-5 space-y-4">
          {detail.timeline.length ? (
            detail.timeline.map((event) => (
              <div key={event.id} className="space-y-2 border-l-2 pl-4">
                <div className="flex flex-wrap justify-between gap-2">
                  <Badge variant="secondary">{event.event_type}</Badge>
                  <time className="text-xs text-muted-foreground">
                    {date(event.timestamp)}
                  </time>
                </div>
                {event.text && (
                  <p className="whitespace-pre-wrap break-words text-sm">
                    {event.text}
                  </p>
                )}
                {text(event.trace.reason) && (
                  <p className="rounded-md bg-muted/50 p-3 text-xs">
                    <strong>Agent explanation: </strong>
                    {text(event.trace.reason)}
                  </p>
                )}
              </div>
            ))
          ) : (
            <Empty
              title="No retained timeline"
              description="Conversation events will appear after a turn is recorded."
            />
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
export function SessionDetailSheet({
  id,
  client,
  close,
  live,
  onSessions,
  returnFocus,
}: {
  id: string | null;
  client: AnalyticsClient;
  close(): void;
  returnFocus(): void;
  live: boolean;
  onSessions(sessions: Session[]): void;
}) {
  const resource = useAnalytics(
    `detail:${id}`,
    (signal) => (id ? client.detail(id, signal) : Promise.resolve(null)),
    id && live ? 3000 : 0,
  );
  useEffect(() => {
    if (resource.data) onSessions([resource.data.summary]);
  }, [resource.data, onSessions]);
  return (
    <Sheet
      open={Boolean(id)}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <SheetContent
        className="w-full overflow-y-auto sm:max-w-2xl"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocus();
        }}
      >
        <SheetHeader className="border-b">
          <SheetTitle>Conversation intelligence</SheetTitle>
          <SheetDescription className="break-all font-mono text-xs">
            {id}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-4 p-5">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              {live
                ? "Updates every 3s while viewing a recent phone call"
                : "Retained backend session data"}
            </p>
            <Button
              size="sm"
              variant="outline"
              onClick={resource.refresh}
              disabled={resource.loading}
            >
              Refresh
            </Button>
          </div>
          <DataState resource={resource} retry={resource.refresh}>
            {(detail) => <DetailContent detail={detail} />}
          </DataState>
        </div>
      </SheetContent>
    </Sheet>
  );
}
