export function DemoPeriodNotice({
  enabled,
  source,
}: {
  enabled: boolean;
  source?: string;
}) {
  if (!enabled || source === "runtime") return null;
  return (
    <p className="text-xs text-muted-foreground" role="note">
      Synthetic demo · recent 11 hours · dates refreshed every 5 minutes. Real
      sessions keep their original dates. Demo latency remains unmeasured.
    </p>
  );
}
