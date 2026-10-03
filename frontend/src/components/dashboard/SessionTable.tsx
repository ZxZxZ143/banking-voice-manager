import type { Session } from "../../analytics/types";
import { Card, CardContent } from "../ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../ui/table";
import { Badge } from "../ui/badge";
import { count, date, latency } from "./presentation";
import {
  DemoBadge,
  Empty,
  OpenSession,
  RiskBadge,
  StatusBadge,
} from "./shared";
export function SessionTable({
  sessions,
  onSelect,
}: {
  sessions: Session[];
  onSelect(id: string): void;
}) {
  if (!sessions.length)
    return (
      <Empty
        title="No sessions found"
        description="Try different filters, start a conversation, or explicitly enable the backend DEMO fixtures."
      />
    );
  return (
    <Card>
      <CardContent className="px-0">
        <Table>
          <TableHeader>
            <TableRow>
              {[
                "Session / time",
                "Channel",
                "Last scenario",
                "Risk",
                "Status",
                "Turns",
                "Agent / TTS",
              ].map((title) => (
                <TableHead key={title}>{title}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sessions.map((session) => (
              <TableRow
                key={session.session_id}
                className="cursor-pointer align-top"
                onClick={() => onSelect(session.session_id)}
              >
                <TableCell>
                  <OpenSession id={session.session_id} onSelect={onSelect} />
                  <div className="text-xs text-muted-foreground">
                    {date(session.latest_event_at)}
                  </div>
                  {(session.source === "synthetic_demo" ||
                    session.source === "mixed") && (
                    <div className="mt-1">
                      <DemoBadge mixed={session.source === "mixed"} />
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">
                    {session.channel === "voice" ? "Voice" : "Text"}
                  </Badge>
                </TableCell>
                <TableCell className="max-w-56 whitespace-normal font-medium">
                  {session.last_scenario?.replaceAll("_", " ") ??
                    "Not selected"}
                </TableCell>
                <TableCell>
                  <RiskBadge level={session.risk_level} />
                </TableCell>
                <TableCell>
                  <StatusBadge
                    status={session.status}
                    active={session.active}
                    handoff={session.handoff}
                  />
                </TableCell>
                <TableCell className="tabular-nums">
                  {count(session.turn_count)}
                </TableCell>
                <TableCell className="text-xs tabular-nums">
                  <span>{latency(session.average_agent_ms)}</span>
                  <span className="text-muted-foreground">
                    {" "}
                    / {latency(session.average_tts_ms)}
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
