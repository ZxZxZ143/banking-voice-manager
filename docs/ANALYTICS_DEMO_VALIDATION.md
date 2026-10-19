# Automatic analytics demo validation — 2026-10-19

Implementation branch: `codex/analytics-demo-autoload`, based on hosting commit
`a844ed8` from `deploy/hosted-demo-20261019`, including main `58fa498`.
Origin is `ZxZxZ143/banking-voice-manager`. The separate hosting Dockerfile, access
gate and same-origin frontend/voice deployment are preserved.

## Initial observations confirmed

The original seed generated 120 sessions / 640 events, all `synthetic_demo`, on
2026-10-03. Its optional anomaly extension used `as_of` for 24 sessions / 48 events.
AnalyticsService and EventRecorder shared SQLiteEventStore through EventStore.
There was no startup seed; the hosting image did not copy `scripts/`.
The new canonical JSON was compared field-for-field against both original generators
from the base commit, with `as_of=2026-10-03T18:00:00Z`: **exact match**.

## Design and guarantees

SQLite remains the working store. A 343,261-byte JSON fixture is included as backend
package data. No external database, provider/LLM call or post-deploy job is introduced.
This fits Render Free's ephemeral filesystem: source data lives in the versioned image
and can always reconstruct the owned synthetic subset after a normal startup.

Dataset `veyra-dashboard-demo`, version `1`, contains 144 sessions / 688 events.
Lifespan loads it before serving requests when `ANALYTICS_DEMO_DATA_ENABLED=true`.
SQLite database v2 records explicit dataset membership, version, content fingerprint
and time anchor; event schema remains v1. Repair/replacement is transactional and does
not use global `reset_synthetic()`. Unchanged startup performs verification without
event writes; incomplete data is repaired. Runtime and unrelated synthetic rows remain
unchanged during operations in an existing DB. The same IDs are reused across refresh,
restart, version changes to continuing sessions, and empty-filesystem recreation.

Dates shift relative to the current five-minute UTC bucket at startup and on the first
analytics read in a later bucket. There is no timer or refresh work on repeated polls
inside a bucket. Core data fits in the last 11 hours; the anomaly baseline/spike retain
their relative intervals. The UI states the demo period. Runtime timestamps and anomaly
clocks remain real; synthetic sessions do not supply measured latency or fake active
calls. Disabling the flag stops install/refresh without removing records.

**Runtime durability across filesystem loss is not guaranteed.** Render Free restart,
redeploy or spin-down can discard the working SQLite. Automatic reload restores only
the packaged synthetic dataset. [Render Free limits](https://render.com/docs/free).

## Executed checks

| Check | Result |
|---|---|
| Full backend suite | 1493 passed |
| New isolated demo behavior tests | 18 passed within the full suite |
| Full frontend suite | 120 passed |
| TypeScript and Vite production build | Passed |
| Ruff lint and backend formatting | Passed |
| Dashboard Prettier check with `--end-of-line auto` | Passed; existing Windows checkout uses CRLF |
| Git whitespace check | Passed |
| Original core and anomaly fixture equivalence | Exact match |
| Offline Stage 6 core/Risk/SQLite/API smoke | Passed: two voice-channel fixture turns, terminal/Risk events and performance/history identical after reopening |

The new tests use temporary databases only. They cover empty startup through API;
repeated startup; filesystem recreation using a new empty path; runtime-only existing
DB and v1 migration; version replacement preserving runtime/unrelated rows; repair of
missing events, membership, marker and changed timestamps; old canonical seed adoption;
clock advances of two days and 400 days in one process; polling without installs;
parallel initializers; injected SQL failure with full rollback; runtime identity
collision; disabled mode; startup/refresh errors and retry; safe fixture diagnostics;
scoped CLI reset; and hosted login protection with automatic data enabled.
Sessions, pagination, source filters, Journey linkage, anomaly output, terminal status
and null demo latency are checked through existing APIs.

A single local timing observation, not a production benchmark: empty install 96 ms,
unchanged startup verification 59 ms, date refresh 71 ms, same-bucket check 0.02 ms.

## Container verification

Reproducible commands, without real provider credentials:

```powershell
docker build -f deploy/Dockerfile -t veyra-demo-autoload:test .
./.venv/Scripts/python.exe scripts/smoke_analytics_demo_image.py
```

The smoke starts the built image from an empty temporary host directory, with no
mounts or env file. It checks installed fixture availability, non-root user, writable
SQLite, absence of `scripts/` and real `.env`, static frontend, health, Sessions,
Journey, anomalies, runtime filter, zero active demo calls and null measured latency.
It then checks restart and complete container recreation, requiring the same 688 IDs.
Only its randomly named test container is removed; existing volumes are not touched.

**Passed on Docker Desktop / Linux Engine 29.2.0:** normal image startup, same-container
restart, then full container recreation without mounts. Every stage returned 144
synthetic sessions / 688 events with the same IDs. Package, writable non-root SQLite,
static UI, source filters, Journey, anomalies, inactive calls and null latency checks
all passed. The test container was removed automatically. Verified image:
`sha256:8e074b5e450708c8cbdd693dd993b97d53e8d779c4b7a49c1ec76a950d54bb8a`.

The local Engine initially failed on stale Windows IPC sockets. Empty socket directories
were preserved under backup names and recreated; no Docker images, volumes, real
databases or configuration were reset. The container checks above ran after recovery.

## Next deployment

Use branch `codex/analytics-demo-autoload`, or merge it into
`deploy/hosted-demo-20261019` and keep that configured branch. Build context `.`,
Dockerfile `deploy/Dockerfile`, health `/health`, one instance/worker.
Set `ANALYTICS_DEMO_DATA_ENABLED=true` and retain
`EVENT_DB_PATH=/app/data/runtime/veyra_events.db` (both are image defaults).
Keep existing access secrets, OpenAI credential/model and provider configuration in
Render environment settings. No seed/pre-deploy command is needed.

The initial implementation task did not change the live service. The subsequent
authorized deployment and its results are recorded below. Live paid LLM/STT/TTS and
PSTN calls are not part of this data-loading validation. The offline voice smoke uses
explicitly labelled provider fixtures, not measured live performance.

Skills used: `demo-readiness`, `security-review`, `render-docker`,
`vercel:react-best-practices` (the small dashboard notice).

## Live Render deployment — 2026-10-19

The user authorized merging, pushing and deploying, and confirmed workspace `main`.
`deploy/hosted-demo-20261019` was fast-forward merged from `a844ed8` to
`7e76943474a32ec0c01d52fa4e7ff3a82eb6b30c` and pushed to origin. Service `veyra`
(`srv-dbb0vje1egvs73cfbfp0`, Frankfurt, Free, one instance) already had auto-deploy
enabled for this exact branch/repository and `deploy/Dockerfile` with context `.`.
No duplicate manual trigger, environment-variable replacement, credential rotation,
seed command or shell job was used.

Deploy `dep-dbb3p1qvcj2c738bfai0` started at 15:51:35 UTC and reached **live** at
15:53:03 UTC for commit `7e76943`. At 15:52:56 UTC its new application instance logged:

```text
analytics_demo_ready dataset=veyra-dashboard-demo version=1 events=688 changed=True
```

Authenticated HTTPS checks against `https://veyra-nkaf.onrender.com` completed at
16:00:32 UTC:

| Live check | Result |
|---|---|
| Public `/health` and login page | HTTP 200; health remains minimal |
| Unauthenticated analytics | HTTP 401; existing access gate preserved |
| Authenticated storage health | `ok` |
| Automatic dataset metadata | enabled, version `1`, `rolling_5m`, 300-second interval |
| Synthetic overview | 144 sessions / 688 events |
| Last 11 hours filter | All 144 sessions available |
| Pagination and event identities | Disjoint session pages; 688 unique event IDs |
| Journey for core session 002 | Four stages linked to its timeline; terminal/inactive |
| Anomalies | Two synthetic alerts; current count 18, baseline 5, ratio 21.6 |
| Source isolation | Runtime-only query excludes synthetic events; runtime count 0 |
| Active demo sessions and measured latency | 0 active; every timing null with 0 samples |
| Repeated reads | Still 688 events; no growth |
| Served frontend | HTML/JS available; bundle includes the five-minute period notice |
| Application error logs after startup through 15:59 UTC | No error entries |

Observed synthetic timestamps span 2026-10-19 06:00:00–15:49:54 UTC, confirming
request-driven time refresh after startup. A manual visual/browser interaction check
could not run because both local browser tooling runtimes failed on the locked
BitLocker `D:` drive. API verification used normal password login and an in-memory
cookie; neither password nor cookie was saved in files, Git or application logs.
The safe detailed result is in ignored `work/render-demo-live-validation.json`.

Deployment skills: `render-deploy`, `demo-readiness`; `render-cli` guidance was read
but CLI execution was unnecessary because the Render connector supported deployment
monitoring. `computer-use` was read and attempted; its runtime was unavailable.
