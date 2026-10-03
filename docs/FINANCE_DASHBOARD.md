# Finance Supervisor Dashboard

The teammate's Veyra dashboard layout, seven navigation sections, shadcn components,
responsive styling, session sheet, journeys and polling are integrated with the current
Stage 5A SQLite backend. Historical phone/in-memory analytics and bearer-token proxy code
were not imported. Current main's conversation, assistant, Fraud/Risk, STT and TTS code
remains authoritative. Integration evidence: `STAGE5B_DASHBOARD_INTEGRATION_VALIDATION.md`.

## Start and populate

From repository root in PowerShell, with the existing ignored `.env`:

```powershell
docker compose up --build -d
Get-Content -Raw scripts/seed_analytics_demo.py | docker compose exec -T backend python - --with-anomaly
```

Open `http://127.0.0.1:5173`. No third analytics service is required. Local development:
start the backend, then `cd frontend`, `npm ci`, `npm run dev`. Both Vite and Nginx use
the existing same-origin `/api` and `/health` proxy. Compose exposes only loopback ports.
There is no individual supervisor authentication; this is a local demo boundary. No
analytics token, credentials or private phone is bundled in `VITE_*` settings.

The original seed remains 120 sessions / 640 events at fixed 2026-10-03 08:00–09:59 UTC.
`--with-anomaly` extends that same seed with 24 synthetic sessions / 48 events: six hourly
OTP-signal baseline observations and eighteen current-window observations. All are
`source=synthetic_demo`. `--as-of` accepts an aware ISO timestamp for repeatable fixtures;
without it, the extension uses current UTC. Repeating the same explicit `--as-of` is
idempotent. Repeating without it adds a fresh pattern; use `--reset --with-anomaly` when
replacing synthetic fixtures. Reset deletes only synthetic events, preserving runtime.
Seed timestamps and the dashboard clock matter: historical patterns eventually leave
the rolling window. An expired pattern correctly stops producing an alert.

## Screens and actual data

| Section | Persistent data and limits |
|---|---|
| Overview | Full filtered session aggregates, status/channel/assistant/risk/handoff counts; sales outcomes and Insurance completion; source totals |
| Live Calls | Up to 100 recent **voice sessions**, last 30 minutes; active means nonterminal activity within five minutes. No PSTN call or provider-presence claim |
| Sessions | Exact session ID, assistant, channel, risk and recency filters; pages of 100 with explicit total/next/previous |
| Session sheet | Full summary/latest typed results, paged safe event timeline and journey; source and approved scenario IDs |
| Risk & Fraud | Highest analyzed risk per session, unique-session signal counts, associated assistants and latest safe case types; advisory language |
| Anomalies | Backend count deviations with current/baseline/ratio/window/source and explicit insufficient-history state |
| Journeys | Paged meaningful lifecycle, assistant, result, risk, handoff and ended events in original turn/sequence order |
| Conversation Demo | Current main's live runtime, five assistant choices, local synthetic profile, business results, Risk panel, trace, voice and TTS diagnostics |

The source selector applies to every analytics read and detail/journey request. Runtime and
synthetic rows have explicit sources; mixed aggregate source totals and demo badges remain
visible. Sources are never inferred from session IDs. No raw transcript, OTP/PIN/CVV,
private identifier, customer amount/preference, provider metadata or free-text risk reason
is required or restored. Language, clarification and latency metrics excluded by Stage 5A
remain null/unavailable. The safe event timeline displays enum/boolean/catalog payloads.

The main runtime and TTS instances remain mounted while navigation changes. Leaving the
Conversation Demo stops capture; it retains session/history and selected-assistant behavior.
Legacy conversation CSS is scoped inside `.conversation-demo`. The teammate stylesheet is
retained locally in `src/lib/shadcn-tailwind.css` with its MIT license; the unused generator
CLI was removed to avoid its vulnerable dependency tree. UI components themselves remain.

## Contract and polling

Use `ANALYTICS_API_CONTRACT.md` and backend OpenAPI at `http://127.0.0.1:8000/openapi.json`.
One analytics client in `frontend/src/analytics/` uses `/api/analytics`. It rejects malformed
required counts, source/channel/risk enums and identities, tolerates additive fields, and
discards unsafe timeline/payload additions. No `/api/v1/analytics` or `/analytics-api`
route tree/proxy is maintained.

Overview polls every ten seconds; Live Calls and a live session sheet poll every three
seconds. Other screens expose refresh. Requests cancel on replacement/unmount, do not
overlap, pause scheduled polling while hidden, and retain labelled stale data on temporary
failures. HTTP 503 storage failures show an actionable error and retry, never healthy zeros.
All public lists have bounded limits (default 100, max 500). Overview/risk use backend
aggregates over full retained history, independently of page size. Offset pages can shift
during new writes. The local aggregate implementation materializes safe retained events;
it is measured at demo scale, not claimed to support production volumes.

## Anomaly policy

`ANALYTICS_WINDOW_SECONDS=3600`, `ANALYTICS_BASELINE_WINDOWS=6`,
`ANALYTICS_MIN_VOLUME=5`, `ANALYTICS_ANOMALY_MULTIPLIER=3` are validated backend settings.
For each source separately, compare `[as_of-window, as_of)` to the six preceding equal
windows. Count analyzed risk signals/high-critical events, handoffs, and distinct
session/case-type snapshots per window. The baseline average is total/N. Require history
beginning on/before the baseline start, a positive baseline, minimum current volume and
current >= average × multiplier. Zero baselines and cold starts emit no anomaly. High
severity means ratio >= twice the multiplier; otherwise medium. These are volume signals
for review, with no confirmed-attack claim or model-generated narrative.

`as_of` freezes the clock for deterministic restart comparisons; it does not truncate session
history. Anomaly IDs are deterministic for source/metric/key/as_of. Changing the rolling
clock changes windows and IDs. Storage gaps can weaken history; absence of an alert is
not evidence of safety. No second store or analytics LLM exists.

## Verification commands

```powershell
./.venv/Scripts/python.exe -m pytest backend/tests -q
./.venv/Scripts/ruff.exe check backend
./.venv/Scripts/ruff.exe format --check backend
cd frontend
npm test
npm run build
npm run format:dashboard
```

From repository root after seeding Docker:

```powershell
./.venv/Scripts/python.exe scripts/stage5b_dashboard_smoke.py create --manifest work/stage5b-manifest.json
docker compose restart backend
./.venv/Scripts/python.exe scripts/stage5b_dashboard_smoke.py verify --manifest work/stage5b-manifest.json
./.venv/Scripts/python.exe scripts/stage5b_dashboard_smoke.py benchmark --manifest work/stage5b-manifest.json
```

`create` makes one live Insurance conversation and checks new runtime analytics plus the
WS protocol boundary; it needs the configured model/key. `verify` is read-only and checks
all event IDs plus fixed-clock aggregates/anomalies. Evidence stays in ignored `work/`.
The protocol-boundary check is not a live STT transcription or audible TTS test.
