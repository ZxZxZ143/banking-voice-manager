# Finance Supervisor Dashboard

The teammate's Veyra dashboard layout, seven navigation sections, shadcn components,
responsive styling, session sheet, journeys and polling are integrated with the current
Stage 5A SQLite backend. Historical phone/in-memory analytics and bearer-token proxy code
were not imported. Current main's conversation, assistant, Fraud/Risk, STT and TTS code
remains authoritative. Integration evidence: `STAGE5B_DASHBOARD_INTEGRATION_VALIDATION.md`.

## Start and populate

Set `ANALYTICS_DEMO_DATA_ENABLED=true` in the existing ignored `.env`, then from
repository root in PowerShell:

```powershell
docker compose up --build -d
```

Open `http://127.0.0.1:5173`. No third analytics service is required. Local development:
start the backend, then `cd frontend`, `npm ci`, `npm run dev`. Both Vite and Nginx use
the existing same-origin `/api` and `/health` proxy. Compose exposes only loopback ports.
There is no individual supervisor authentication; this is a local demo boundary. No
analytics token, credentials or private phone is bundled in `VITE_*` settings.

No seed command is needed. The hosting Dockerfile defaults this setting to `true`;
ordinary backend/local configuration defaults to `false`. This flag affects only
analytics data: routing, STT and TTS still use their configured providers.

### Canonical dataset and rolling dates

`backend/app/analytics/fixtures/demo-v1.json` is the versioned source of truth, packaged
with the backend. It preserves the original 120 sessions / 640 events from
2026-10-03 08:00–09:59 UTC, plus 24 sessions / 48 events for anomalies: six hourly
OTP-signal baseline observations and eighteen recent observations. Total: **144 sessions,
688 events**, all `source=synthetic_demo`, no measured performance samples.

The canonical reference clock is `2026-10-03T18:00:00Z`. At startup, and before the first
analytics read in each new five-minute UTC bucket, the loader shifts every fixture
timestamp by `floor(now / 300 seconds) * 300 seconds - reference_as_of`. IDs, order and
time intervals stay stable. Core sessions are approximately 8–10 hours old; anomaly
baselines are about 2–7 hours old and the spike is about 10–16 minutes old. All fit in the last
11 hours. The dashboard displays this period when automatic data is enabled and the
source includes demo data. Ordinary views need no manual historical date or `as_of`.
Custom narrower filters may correctly return fewer or zero sessions. Terminal core
sessions stay terminal; the anomaly fixtures are too old to appear active. Synthetic
latency remains unknown/null. Runtime timestamps and the anomaly evaluation clock
are never rewritten; `source=runtime` excludes fixtures.

This is request-driven refresh, not a timer: an idle process does no work and its first
analytics read refreshes stale fixtures. Polling in the same bucket does no dataset DB
work. Repeated starts, clock advances and refreshes reuse the same event/session IDs.
Anomaly response IDs still depend on `as_of` under the existing API contract; these
response IDs are not additional stored events. Baselines remain separated by source.
The actual `as_of` still determines window boundaries: the oldest baseline observation
can fall just outside the six-window baseline between bucket boundaries. Counts/ratios
are calculated from that actual window; they are not frozen or fabricated for display.

### Installation, repair and failure behavior

`DemoDataLoader` runs in application lifespan before requests, using the exact store
shared by EventRecorder and AnalyticsService. SQLite database schema v2 adds
`demo_datasets` (version, SHA-256 fixture fingerprint, time anchor) and
`demo_dataset_events` (explicit ownership). Event schema v1 and API payloads are unchanged.
Each initialization checks the marker, complete membership and actual event rows;
an intact current dataset causes no event writes. Missing/changed rows are repaired.
Version replacement, timestamp shift, membership and marker updates share one SQLite
transaction, so failure leaves the previous set intact. Runtime records and unrelated
synthetic datasets are preserved, including during version changes. Identity/ownership
conflicts fail explicitly. Old unowned CLI rows are adopted only by exact canonical
event IDs; arbitrary older anomaly patterns are not globally deleted.

To publish a revised dataset, edit the canonical JSON and increment its `version`,
preserving IDs for continuing sessions. Removed owned rows disappear on the next
startup. The fingerprint also detects accidental edits without a version bump.
Only one fixture version is packaged/loaded at a time; do not run old and new app
versions concurrently against the same writable SQLite database.
Older application builds accepting only DB v1 cannot open the upgraded database;
on durable storage, use a v2-compatible build for rollback.

Logs contain fixed failure codes or dataset/version/count/change metadata, never
conversation contents. Invalid fixtures or failed initial installation abort startup;
a later refresh failure follows the existing analytics HTTP 503/storage diagnostics,
and the next read retries. `ANALYTICS_DEMO_DATA_ENABLED=false` stops automatic install
and refresh; it does not erase previously stored data. No public seed/reset API exists.

### Optional development CLI

`scripts/seed_analytics_demo.py` is a thin wrapper over the packaged implementation;
the server never imports `scripts/`. For a separate local database:

```powershell
./.venv/Scripts/python.exe scripts/seed_analytics_demo.py --db-path work/analytics-demo.db --with-anomaly --as-of 2026-10-03T18:00:00Z
```

Without `--with-anomaly`, the CLI installs only 120/640 core data. Without `--as-of`,
both core and anomaly fixtures use the canonical reference clock. Explicit `--as-of`
shifts both together with stable IDs. `--reset` requests the same scoped repair; it
does not globally clear synthetic data or delete runtime. Use an isolated DB or disable
autoload when exploring historical snapshots, because autoload restores the current
full rolling dataset. The older fixed-clock restart smoke below is intended for that
manual, autoload-disabled workflow.

On Render Free, the source fixtures survive in the image and recreate demo analytics
after ephemeral DB loss. New runtime events do **not** have a durability guarantee.
See `HOSTED_DEMO.md` for deployment settings and `ANALYTICS_DEMO_VALIDATION.md` for checks.

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
is required or restored. Language and clarification metrics excluded by Stage 5A
remain null/unavailable. Response performance now consumes persistent numeric runtime samples;
phone paths can supply all six timings, while browser/text requests supply Agent only.
Missing fields/old sessions remain unknown and synthetic demo data never supplies measured
latency. See `ANALYTICS_API_CONTRACT.md#persistent-response-performance`. The safe event timeline displays enum/boolean/catalog payloads.

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

Optional historical manual workflow, with autoload disabled and a seeded local Docker DB:

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
