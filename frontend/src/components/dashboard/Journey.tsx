import {
  Check,
  CornerDownRight,
  Headphones,
  HelpCircle,
  Route,
} from "lucide-react";
import type { JourneyStage } from "../../analytics/types";
import { Badge } from "../ui/badge";
import { Empty } from "./shared";
import { date, stageLabel } from "./presentation";
function actionLabel(action: unknown): string | null {
  if (typeof action === "string") return action;
  if (Array.isArray(action))
    return action.filter((a) => typeof a === "string").join(" · ") || null;
  return null;
}
export function Journey({ stages }: { stages: JourneyStage[] }) {
  if (!stages.length)
    return (
      <Empty
        title="No journey stages yet"
        description="Selected scenarios and explicit lifecycle events will appear in their original event order."
      />
    );
  return (
    <ol className="space-y-0" aria-label="Customer intent journey">
      {stages.map((stage, index) => {
        const Icon = stage.handoff
          ? Headphones
          : stage.clarification
            ? HelpCircle
            : stage.completion
              ? Check
              : Route;
        return (
          <li key={stage.id} className="relative flex gap-4 pb-7 last:pb-0">
            {index < stages.length - 1 && (
              <span
                className="absolute left-4 top-9 bottom-0 w-px bg-border"
                aria-hidden="true"
              />
            )}
            <div
              className={`relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full border ${stage.handoff ? "border-violet-200 bg-violet-50 text-violet-700" : "border-teal-200 bg-teal-50 text-teal-700"}`}
            >
              <Icon className="size-4" aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">{stageLabel(stage)}</h3>
                <time className="text-xs text-muted-foreground">
                  {date(stage.timestamp)}
                </time>
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {stage.clarification && (
                  <Badge variant="secondary">Clarification</Badge>
                )}
                {stage.handoff && <Badge variant="secondary">Handoff</Badge>}
                {stage.completion && (
                  <Badge variant="secondary">Completed</Badge>
                )}
              </div>
              {actionLabel(stage.action) && (
                <p className="mt-2 flex gap-1 text-xs text-muted-foreground">
                  <CornerDownRight className="size-3" aria-hidden="true" />
                  {actionLabel(stage.action)}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
