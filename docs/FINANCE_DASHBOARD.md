# Veyra Finance Supervisor Dashboard

Implemented on `feature/finance-dashboard`, based on `feature/data-intelligence`.
This frontend consumes the existing seven analytics endpoints; it adds no backend
analytics algorithms, financial decisions, telephony behavior or model changes.

## Run locally

Use one backend worker, following the existing backend setup. In the ignored
repository root `.env`, set `ANALYTICS_ENABLED=true`, a nonempty
`ANALYTICS_API_TOKEN`, and optionally `ANALYTICS_DEMO_ENABLED=true` for explicitly
synthetic fixtures. Never commit that file or print the token.
`ANALYTICS_PROXY_TARGET` defaults to `http://127.0.0.1:8000` and may point only to a
loopback HTTP origin. Existing conversation `/api` and `/health` proxies still use
port 8000. Restart the backend and Vite after changing analytics configuration.

```powershell
# Repository root; after installing the existing backend dependencies
./.venv/Scripts/python.exe -m app.main
# Separate terminal
cd frontend
npm ci
npm run dev
```

Vite reads only server-side `ANALYTICS_*` settings from the root `.env` (process
environment takes precedence). The browser sends same-origin GET requests to
`/analytics-api/*`; the Node proxy rewrites them to `/api/v1/analytics/*` and
injects the bearer token. The client has no token configuration or Authorization
header. Only the demo-enabled Boolean is compiled into browser code.
The guard restricts methods, routes, path segments, loopback Host and request
Origin; missing token fails closed. Responses are not cached. Proxy timeouts are
15 seconds; client timeout is 12 seconds, including JSON parsing.

This is a **local/demo access boundary**, not production supervisor authorization.
Keep Vite on loopback; do not expose it through a tunnel or `--host 0.0.0.0`.
For production, serve the built UI behind a same-origin BFF/reverse proxy with
operator authentication/authorization, TLS and no public direct analytics proxy.
Store the backend bearer token only in that server's secret configuration. Static
hosting alone cannot inject it safely. Backend authentication remains required.

## UI and implementation

- `src/App.tsx`: responsive supervisor shell; seven navigation sections and one
  retained ConversationRuntime/BrowserTtsService instance.
- `src/components/ui/`: twelve official shadcn primitives (Card, Button, Badge,
  Table, Sheet, Tabs, Skeleton, Alert, Input, Separator, NativeSelect, Textarea).
  `components.json`, Tailwind v4/Vite plugin, `@/*` alias and semantic CSS variables
  configure the system. No charting library or global state package.
- `src/analytics/`: typed seven-method API client, defensive parsing, cancellable
  non-overlapping polling and React resource hook. Optional fields remain unknown.
- `src/components/dashboard/`: screen bodies, session table/detail, ordered journey,
  shared states and the wrapper around existing conversation/voice/trace components.
- `server/analyticsProxy.ts`: server-only proxy/guard; never imported by `src/`.

Overview displays backend metrics, separate latency measurements, scenario counts,
anomalies and five recent sessions. It refreshes every 10 seconds. Live Calls
polls phone sessions from the last 30 minutes every 3 seconds, capped at 100;
its selected detail also polls every 3 seconds. Active is the backend event-recency
heuristic, not proof of an open provider call. Other views refresh manually.
Polling pauses network work while hidden, aborts on unmount/filter changes and
ignores superseded results. Errors retain previous data with an explicit stale label.

Sessions filters channel, risk, activity, exact session ID and scenario, capped at
100. Risk displays Agent-produced levels/signals and associated scenarios; high
and critical lists are each capped at 50. Risk signals are not fraud verdicts.
Anomalies show current count, historical total, expected count per equivalent
window, ratio, severity, bounds and explanation. Journeys show actual backend
stages in order, including clarification, handoff and session closure. A handoff
does not prove a real operator transfer; normal completion and closure stay distinct.
Session detail shows safe provider correlation fields, retained summary, journey,
and selected timeline text/Agent explanation; raw transport metadata is not rendered.

DEMO-enabled configuration displays `DEMO DATA` immediately, including when empty.
Returned DEMO identities/provider flags also enable the badge. Observing real
sessions alongside fixtures changes it to `DEMO + REAL DATA`; individual fixture
rows/cards are marked. Counts always come from the API; the frontend supplies no
fake numbers. Missing risk is “No risk data”, never low risk. Only web and phone
are product channels.

Conversation Demo keeps the existing text, microphone, Agent, browser TTS and
Supervisor Trace components. Its mounted state survives navigation. Leaving the
section pauses voice capture using the existing toggle without resetting the
session; re-enable voice input to resume. Legacy CSS is scoped to that section.

## Checks and limits

```powershell
cd frontend
npm test
npm run test:dashboard
npm run typecheck
npm run build
npm run format:dashboard
# Repository root
./.venv/Scripts/python.exe -m pytest backend/tests -q
```

34 new tests cover client parsing/routes/errors/timeout/abort, proxy authorization
and path guards, polling cancellation/overlap, rendering and safe labels. The
existing 37 runtime/events/voice/TTS/trace/integration tests remain included.
Browser QA uses an isolated backend with synthetic fixtures and external providers
disabled, checks all sections, exact-ID filtering, detail selection, journey order,
keyboard close, conversation session continuity and desktop/small-width layouts.
This does not reverify live microphone permissions, paid Agent calls or PSTN audio.

Verified: 71 frontend tests (34 new + 37 existing), 540 backend tests, TypeScript
noEmit, Vite build, dashboard Prettier check, backend Ruff lint/format, diff check
and synthetic analytics smoke. Built JS is 124.43 kB gzip; CSS 10.76 kB gzip.
A real local-proxy HTTP check verified origin/method/path rejection, no-store and
no authentication response headers. A local bundle scan checked configured
provider/supervisor credential values without printing them; none were present.

Data remains bounded, process-local and lost on backend restart. List caps and
partial-history notices are visible; no pagination/export, persistent analytics,
operator RBAC, push feed, live transfer, journey editor or financial routing is
implemented here. Production deployment/authentication are deferred. Analytics
configuration must be enabled separately; unconfigured installations show an
explicit setup error instead of fabricated fallback data.
