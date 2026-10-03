import type { ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Inbox,
  RefreshCw,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "../ui/alert";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Skeleton } from "../ui/skeleton";
import type { Resource } from "../../analytics/useAnalytics";
import type { RankedCount, RiskLevel } from "../../analytics/types";
import { count, riskLabels } from "./presentation";

export function RiskBadge({ level }: { level: RiskLevel }) {
  const color = {
    unknown: "border-slate-200 bg-slate-50 text-slate-600",
    none: "border-slate-200 bg-slate-50 text-slate-600",
    low: "border-emerald-200 bg-emerald-50 text-emerald-800",
    medium: "border-amber-200 bg-amber-50 text-amber-900",
    high: "border-red-200 bg-red-50 text-red-800",
    critical: "border-rose-300 bg-rose-100 text-rose-900",
  }[level];
  return (
    <Badge variant="outline" className={color}>
      {riskLabels[level]}
    </Badge>
  );
}
export function DemoBadge({ mixed = false }: { mixed?: boolean }) {
  return (
    <Badge
      variant="outline"
      className="border-amber-300 bg-amber-50 text-amber-900"
    >
      {mixed ? "DEMO + REAL DATA" : "DEMO DATA"}
    </Badge>
  );
}
export function StatusBadge({
  status,
  active = false,
  handoff = false,
}: {
  status: string;
  active?: boolean;
  handoff?: boolean;
}) {
  return (
    <Badge
      variant="outline"
      className={
        handoff
          ? "border-violet-200 bg-violet-50 text-violet-800"
          : active
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "text-muted-foreground"
      }
    >
      {active && <Activity className="size-3" aria-hidden="true" />}
      {handoff ? "Handoff" : status.replaceAll("_", " ")}
    </Badge>
  );
}
export function Empty({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-8 text-center">
      <Inbox className="size-7 text-muted-foreground" aria-hidden="true" />
      <h3 className="font-semibold">{title}</h3>
      <p className="max-w-md text-sm text-muted-foreground">{description}</p>
    </div>
  );
}
export function Loading() {
  return (
    <div
      role="status"
      aria-label="Loading analytics"
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      {Array.from({ length: 4 }, (_, index) => (
        <Card key={index}>
          <CardContent className="space-y-3 pt-6">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-8 w-16" />
            <Skeleton className="h-3 w-32" />
          </CardContent>
        </Card>
      ))}
      <Skeleton className="h-64 sm:col-span-2 lg:col-span-4" />
      <span className="sr-only">Loading analytics</span>
    </div>
  );
}
export function DataState<T>({
  resource,
  retry,
  children,
}: {
  resource: Resource<T>;
  retry(): void;
  children(data: T): ReactNode;
}) {
  return (
    <div className="space-y-5" aria-busy={resource.loading}>
      {resource.error && (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>
            Analytics unavailable
            {resource.data ? " · showing previous data" : ""}
          </AlertTitle>
          <AlertDescription>
            <p>{resource.error}</p>
            <Button size="sm" variant="outline" onClick={retry}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {!resource.data && resource.loading && <Loading />}
      {resource.data && children(resource.data)}
    </div>
  );
}
export function Toolbar({
  title,
  description,
  resource,
  refresh,
  children,
}: {
  title: string;
  description: string;
  resource: Resource<unknown>;
  refresh(): void;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          {description}
        </p>
      </div>
      <div className="flex items-center gap-3">
        {children}
        {resource.updatedAt && (
          <span className="text-xs text-muted-foreground">
            Updated{" "}
            {new Date(resource.updatedAt).toLocaleTimeString(undefined, {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={refresh}
          disabled={resource.loading}
        >
          <RefreshCw
            className={`size-3.5 ${resource.loading ? "animate-spin" : ""}`}
            aria-hidden="true"
          />
          Refresh
        </Button>
      </div>
    </div>
  );
}
export function MetricCard({
  label,
  value,
  note,
  accent = false,
}: {
  label: string;
  value: string;
  note: string;
  accent?: boolean;
}) {
  return (
    <Card className={accent ? "border-teal-200 bg-teal-50/40" : ""}>
      <CardHeader className="pb-0">
        <CardTitle className="text-xs font-medium text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold tracking-tight tabular-nums">
          {value}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{note}</p>
      </CardContent>
    </Card>
  );
}
export function RankedList({
  items,
  empty = "No observed data",
}: {
  items: RankedCount[];
  empty?: string;
}) {
  const max = Math.max(1, ...items.map((item) => item.count ?? 0));
  return items.length ? (
    <ol className="space-y-4">
      {items.slice(0, 8).map((item) => (
        <li key={item.key} className="space-y-1.5">
          <div className="flex justify-between gap-4 text-sm">
            <span className="break-words">{item.key.replaceAll("_", " ")}</span>
            <strong className="tabular-nums">{count(item.count)}</strong>
          </div>
          <div
            className="h-1.5 overflow-hidden rounded-full bg-muted"
            aria-hidden="true"
          >
            <div
              className="h-full rounded-full bg-teal-600"
              style={{ width: `${((item.count ?? 0) / max) * 100}%` }}
            />
          </div>
        </li>
      ))}
    </ol>
  ) : (
    <p className="text-sm text-muted-foreground">{empty}</p>
  );
}
export function OpenSession({
  id,
  onSelect,
}: {
  id: string;
  onSelect(id: string): void;
}) {
  return (
    <Button
      variant="ghost"
      size="sm"
      className="max-w-52 justify-start px-0 font-mono text-xs text-primary"
      onClick={(event) => {
        event.stopPropagation();
        onSelect(id);
      }}
      aria-label={`Open session ${id}`}
    >
      <span className="truncate">{id}</span>
      <ArrowUpRight className="size-3.5 shrink-0" aria-hidden="true" />
    </Button>
  );
}
