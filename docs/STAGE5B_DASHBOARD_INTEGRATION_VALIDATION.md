# Stage 5B dashboard integration validation

## Contract mapping established before implementation

Integration started from main at cfcd73a, authoritative for assistants, voice and Stage 5A storage.
Dashboard source: origin/feature/finance-dashboard (2defe23), based on
origin/feature/data-intelligence (8804d7c). Merge base with main: 5193ad7.
Integration branch: codex/stage5b-dashboard. Import only dashboard/frontend files;
do not merge historical backend, telephony, event store, runtime or conversation components.

| Dashboard need | Stage 5A source | Required integration |
|---|---|---|
| Overview totals/status/channel/handoff | Stored events and summary | Add persistent overview read model; unavailable clarification/latency remain null |
| Bounded session list and filters | Events grouped by session, final status, assistant, risk enums | Add EventStore session summaries and bounded sessions API |
| Session detail | Existing paged session events plus safe payloads | Add /sessions/{id}/detail; preserve Stage 5A /sessions/{id} unchanged |
| Ordered journey | Turn, sequence, event_type, assistant/scenario, payload | Add deterministic paged journey API |
| Risk levels/signals and Fraud data | risk_signal and fraud_case events | Add risk aggregate; advisory labels and safe case types |
| Sales/Insurance result details | sales_lead and insurance_result payloads | Expose latest typed results in session detail; no preferences or identifiers |
| Scenario/assistant counts | Persisted assistant_id and approved scenario_id | Add scenarios API; wire assistant filters to validated enum |
| Anomaly cards | Indexed historical event/signal counts | Add deterministic equal-window baseline detector with cold-start protection |
| Live Calls | channel=text/voice, latest status/time | Label as recent voice sessions; no PSTN/provider presence claims |
| DEMO badges/source | source=synthetic_demo/runtime | Use source field, source filter and aggregate source counts; no ID heuristic |
| Raw transcript/Agent reason/provider IDs | Intentionally absent | Remove those specific fields; retain timeline layout with safe structured event labels |
| Polling/error/stale/loading | Existing teammate client/hook | Preserve cancellation/hidden pause/nonoverlap; same-origin /api/analytics namespace |
| Conversation Demo | Current main ConversationPanel/runtime/security/voice | Retain current components; reconcile dashboard wrapper and scope current legacy CSS |
| Historical bearer-token proxy | No token required by current local backend | Use existing Vite/Nginx /api proxy; keep loopback binding and no browser credentials |

## Integration and conflict decisions

Before edits: working tree clean on main `cfcd73a`; fetch --all --prune completed.
Main/dashboard symmetric history contains 18 main-only and 15 dashboard-side commits.
Dashboard-only commits after data-intelligence are `33803b6` and `2defe23`.
The historical dashboard diff also includes phone/runtime/backend changes, so no wholesale
merge/cherry-pick was used. Thirty-six dashboard/frontend source/config/test files were
selectively copied and reconciled on `codex/stage5b-dashboard`, with current main runtime,
ConversationPanel, SecurityPanels, services, voice implementation and prior tests unchanged.

Semantic conflicts were resolved explicitly: App keeps main's lasting runtime/TTS and
teammate shell; current RiskPanel was restored inside the demo wrapper; current conversation
CSS is scoped; channel values use text/voice; schema-v1 safe results replace old transcript,
provider and reasoning fields; API client uses the Stage 5A namespace; richer session detail
is additive `/detail`. Sources drive badges, not ID patterns. Assistant suggestions consume
the persisted scenarios aggregate. Original shadcn CSS/components are retained; the unused
generator CLI's vulnerable dependency tree was removed, and its stylesheet/license vendored.
No routing prompt, product tuning, SDK transport, state policy or analytics LLM was changed.

## Implemented contract

Original GET `/api/analytics/events`, `/sessions/{session_id}`, `/summary` retain their
schemas and behavior. New GET endpoints: `/overview`, `/sessions`,
`/sessions/{session_id}/detail`, `/sessions/{session_id}/journey`, `/risk`, `/scenarios`,
`/anomalies`. All use EventStore via deterministic AnalyticsService. Limits default 100,
max 500; lists expose total/next_offset. Unknown detail is 404; storage error is typed 503.
Full models/semantics/filter mapping: `ANALYTICS_API_CONTRACT.md`, `FINANCE_DASHBOARD.md`.
Aggregate totals use full retained history, independent of the first event/session page.

Anomalies compare one rolling hour with six preceding equal windows, per source, with
positive observed baseline, minimum five current events and 3× multiplier. Cold start/zero
baseline produce no anomaly. Risk signals/high-critical events, handoffs and distinct
session/case types are tracked. Explanations state anomalous increase and explicitly do not
establish cause. The same seed optionally adds baseline/current synthetic patterns; the
original 640-event dataset remains unchanged. Repeatability uses explicit aware as_of.

## Initial integration offline checks

- **731 backend tests passed**, including all 700 previous tests plus 31 new cases;
  final full run 31.37 seconds. Coverage includes overview, full-history summaries,
  pagination/filter validation, backward compatibility, safe results/journey order,
  risk/assistant aggregates, none versus unknown, cold start, source separation, fixed-clock
  persistent anomalies, latest snapshots, mixed data and real invalid SQLite-path 503.
- **80 frontend tests passed**: all 49 previous runtime/security/voice regressions plus
  31 adapted dashboard/analytics checks. Dashboard tests cover sections, loading, empty,
  stale/error/retry, filters/client contract, detail/journey order, advisory risk/anomaly
  wording, source badges, required-field errors and exclusion of unsafe additive fields.
- TypeScript, production Vite build and dashboard Prettier checks passed. Ruff check/format
  passed for backend and both affected/new scripts; git diff --check passed.
- All analytics tests use temporary SQLite/typed seed/HTTP fixtures, with no paid model call.
  The supplied Insurance/Product/Fraud model accuracy evaluations were not rerun because
  their routing prompts/transport/policies did not change. O11 remains unchanged.

## Real Docker/API and persistence checks

`docker compose up --build -d` built the actual backend/frontend with no third service.
Both services were healthy on loopback 8000/5173. Named volume analytics_data remains
mounted at `/app/data/runtime`; configured DB is `/app/data/runtime/veyra_events.db`.

The existing volume contained 704 Stage 5A rows (64 runtime + 640 synthetic). The compatible
seed `--with-anomaly` inserted 48 extra synthetic rows, producing 144 synthetic sessions.
One real HTTP Insurance opener + office-hours question through the frontend Nginx proxy
committed six runtime events, increasing runtime session count by one. Final evidence:
**758 events, 153 sessions** (144 synthetic + nine runtime). The runtime detail showed the
same two-turn session and source=runtime. No fake dashboard metric or response fallback.

Two actual anomaly results were returned from persisted history: OTP-requested signal and
high-risk-event frequency. Current count was 18, with positive prior baseline. Because
the normal rolling clock advances past the first seed boundary, observed baseline in the
real fixed-clock manifest was five (expected 5/6, ratio 21.6). The exact seed as_of fixture
has baseline six, expected one, ratio 18. These are advisory volume deviations.

The voice WebSocket upgraded through Nginx and rejected an invalid configuration before
provider/STT connection, returning the existing safe voice_failed code. This confirms the
HTTP/WS proxy boundary, not a fresh live transcription or audible browser TTS measurement.
Current voice/runtime offline regressions all passed.

Backend restart retained every event ID and identical fixed-clock overview/risk/anomalies.
Compose down/up **without -v** removed/recreated containers and network, retained all 758
IDs and the same aggregates/baselines. A final rebuild retained the same volume.
Reproducible checks: `scripts/stage5b_dashboard_smoke.py` and ignored local manifest.

## Performance: local Docker demo only

Thirty samples per endpoint through the actual same-origin Nginx HTTP proxy, on 758 rows:

| Endpoint | p50 ms | p95 ms |
|---|---:|---:|
| Overview | 22.93 | 28.32 |
| Sessions | 27.91 | 38.28 |
| Risk | 26.89 | 70.91 |
| Anomalies | 8.06 | 8.86 |
| Runtime session detail | 5.31 | 6.08 |

The three initial Overview API reads executed serially took **65.36 ms** in this HTTP
smoke. The UI normally issues them concurrently. This is an API-read measurement, **not**
a measured browser initial-render time. Browser rendering was subsequently verified below;
initial-render latency was not instrumented and no browser performance number is claimed.
No production-scale claim: aggregates materialize selected retained safe events; larger
volumes need measured capacity and potentially different EventStore aggregate methods.

## Focused security review

Reviewed mapping/storage → parameterized EventStore → typed API → single frontend client/
safe parsers → React rendering. Source field separation and enum filters are preserved.
No unsafe persisted fields, token proxy, data-changing analytics route, public host binding
or browser credentials were added. Current same-origin local access has no individual
supervisor auth/RBAC. Runtime .env stays ignored/excluded; privileged values remain server-side.

A scanner loaded the actual configured API key/private demo phone internally and never
printed them. It scanned 321 source/build files, backend container logs, both image configs,
all 758 SQLite rows and DB/WAL/SHM files: **no configured private values found**. Schema/API
tests independently check safe payloads and redacted error behavior. npm audit reports
**zero vulnerabilities** after removing the unused generator CLI (components/CSS retained).

## Final browser release gate: passed, 2026-10-03

The existing branch started clean at `a7f5e33`. Real Docker images were rebuilt using
`docker compose up --build -d`. The documented seed ran without reset, with
`--with-anomaly --as-of 2026-10-03T06:27:43+00:00`: 48 additional events, 168 synthetic
sessions including previously retained seed runs. No persistent volume was removed.

The actual Nginx application at `http://127.0.0.1:5173` was operated through the Codex
in-app browser. The earlier browser-tool connection blocker no longer applied.
DOM observations and screenshots were inspected at 1440×1000 and 390×844 viewports.
The temporary viewport override was reset after validation.

| Browser section | Actual observed result |
|---|---|
| Overview | Populated cards, scenario/results counts and two anomaly summaries; missing latency remains a dash. Initial 184 sessions (16 runtime + 168 synthetic), final 189 (21 + 168). Visible DEMO + REAL DATA label and source counts. Polling picked up new runtime activity. |
| Live Calls | Populated voice cards, source/channel/DEMO labels and detail controls; clearly describes recent browser voice activity and unavailable PSTN presence. |
| Sessions | First page 100 rows, second page 84 of initial 184; next disabled at the end and previous restored page 1. Synthetic + text + critical filters returned 12 matching sessions. Insurance assistant filter returned 24 synthetic sessions. Runtime recent-activity filter returned five new sessions; exact-ID search selected one. Clear filters restored the list. |
| Session detail sheet | Open/close and Summary, Journey, Safe event timeline tabs worked. Synthetic Fraud result showed needs_review and operator_handoff; no confirmed transfer claim. Runtime detail showed 11 events and four turns, with source=runtime and no entered identifiers in the persisted timeline. |
| Risk & Fraud | Populated signal/case-type counts and high/critical sessions. Wording requires supervisor review and distinguishes unknown risk data from no observed signal. |
| Anomalies | Two synthetic cards: high-risk frequency and third-party OTP request frequency. Each showed current 18, historical total 26, expected 4.333 per equivalent window, ratio 4.2×. Explicit anomalous increase and cause-not-established wording. Runtime-only scope honestly showed insufficient baseline/no unusual volume. |
| Journeys | Selected synthetic Fraud conversation displayed conversation_started → assistant_selected → fraud_case → risk_signal → operator_handoff in original sequence. The detail Journey tab agreed; the Safe event timeline additionally included conversation_turn in its proper position. |
| Conversation Demo | Real Insurance opener/text responses, all five selectors (Insurance, Fraud, deposit/Product, Card, Loan), live HIGH advisory Risk panel, browser TTS and preserved session/history when leaving and returning. Corrected identifier-memory flow reached bounded handoff. |

Narrow layouts were visually checked across every section, including the detail sheet.
Controls/cards stacked readably, navigation and wide tables used contained scrolling,
and document scrollWidth equalled clientWidth in measured narrow views (375 CSS px with
scrollbar, or 390 without). Desktop Overview and the other sections remained usable.
No unsafe/private analytics fields appeared in inspected summaries, results or timelines;
the data projection and scanner checks below supplement these manual observations.

Empty/error states were exercised against the actual application:

- A nonexistent exact session ID produced No sessions found, zero results and disabled
  pagination; runtime-only Anomalies produced the insufficient-history empty state.
- An ignored temporary Compose override pointed EVENT_DB_PATH at the existing runtime
  directory, without touching the DB file. Health reported analytics degraded and the
  analytics API returned typed HTTP 503 analytics_storage_unavailable.
- Refresh showed Analytics unavailable · showing previous data with actionable storage
  guidance. A cold reload showed Analytics unavailable without fabricated zero metrics.
  Restoring standard Compose configuration and refreshing recovered the populated UI.

### Browser defects and bounded fixes

1. Two source-count separators in Overview rendered as replacement characters. They now
   render as middle dots; the rebuilt Docker UI was rechecked.
2. The required Insurance-memory check exposed a release blocker: a new IIN was combined
   with an already-failed phone and incorrectly asked for that phone again. Client lookup
   now excludes individually failed values by their existing fingerprint. Corrected values
   remain eligible, and simultaneously supplied conflicting identities remain rejected.
   No prompt, routing selection, schema, sales-campaign behavior or telephony changes were made.
   Three new deterministic cases failed before the fix and passed afterward: RU/KK
   exhaustion and successful alternative IIN. The 77-test focused suite also preserved
   conflicting-identity and correction behavior.
3. Ruff found two existing hotfix formatting deviations in composer.py and
   test_message_v2.py. Formatting was normalized; both Python ASTs were checked unchanged.

On the final image, real browser session `35928564-58aa-4f9d-8178-2a812dd2e24f`
progressed unavailable policy → unknown synthetic phone → unknown synthetic IIN →
lookup_exhausted. It retained renewal, unavailable policy, failed phone/IIN, collected
field names and operator_review; transcript identifiers were masked in the trace and
terminal input was disabled. No repeated policy/phone request or unsupported plate lookup.
Leaving/returning preserved the same session and history. Source=runtime and its 11
events were then inspected through the dashboard already open before the conversation.

A separate live Insurance security question produced HIGH with bank-impersonation and
third-party-code signals and explicit advisory wording. It preserved the Insurance
assistant. Microsoft Irina (ru-RU) browser TTS reported firstAudioMs=737 and totalMs=5199
for the manual voice sample; normal replies transitioned speaking → awaiting text.
These are real browser playback events, not an independent acoustic-quality measurement.
One live routing request timed out with an honest HTTP 504 error. Reset and repeat passed;
no provider-success claim is made for the timed-out attempt.

### Final persistence, checks and security

After the browser was already open, the existing HTTP smoke created an additional real
opener + office-hours conversation (six runtime events). Overview polling displayed
**189 sessions: 168 synthetic + 21 runtime; 928 total events**. The smoke also verified
the Nginx voice WebSocket's existing safe rejection before external STT connection.

`docker compose restart backend` completed. The browser reloaded the populated dashboard.
All **928 event IDs** and exact fixed-clock Overview/Risk/Anomalies results matched the
pre-restart manifest. The same comparison passed again after restoring the temporary
storage-failure configuration. Both services finished healthy on loopback 8000/5173;
the original analytics_data volume and standard database path remain in use.

Final checks on the release changes:

- **757 backend tests passed**, 36.44 seconds (754 existing + three new regressions).
- **80 frontend tests passed**, 1.73 seconds, no failures/skips.
- TypeScript, Vite production build, dashboard Prettier, Ruff lint, Ruff formatting
  (172 files), and git diff --check passed.
- No expensive LLM evaluation dataset was rerun. The bounded lookup fix was checked by
  deterministic regressions, the full backend suite and the actual browser reproduction;
  Router/Composer prompts were unchanged. Earlier model-evaluation limitations remain.
- Focused security review covered typed safe projections, bounded validated GET routes,
  parameterized SQLite reads, frontend allowlists/React rendering and loopback proxy access.
  No release-blocking security findings. Runtime secrets remain server-side; no auth/RBAC
  or production-readiness claim was added.
- Final privacy scan passed across **326 source/build files**, backend logs, both image
  configurations, **928 SQLite rows** and DB/WAL/SHM files. No configured private values
  found; values were never printed. npm audit: **zero vulnerabilities**.

All required release gates passed. Release proceeds by a normal fast-forward of main
from `cfcd73a`, preserving `5fcf5eb`, `4a7828e`, `5cf444c` and Insurance hotfix `a7f5e33`
plus the documented gate fixes. The actual final main/origin hashes and clean-tree check
are reported after the push; no force or discarded branch work is permitted.

## Remaining limits and skills

Storage remains best-effort post-commit and can leave gaps; no durable outbox, production
auth, retention/backup policy, new store or production scale guarantee was introduced.
Offset pages may shift during new traffic; active is a recency heuristic. Persisted latency,
language and clarification metrics are unavailable. The synthetic anomaly is time-dependent.
Known **O11**: card-campaign deposit request can be interpreted as decline instead of
out_of_scope; no Product tuning was mixed into this integration.

Initial integration skills: agent-debugging, security-review, demo-readiness and computer-use.
Final release-gate skills actually used: demo-readiness, security-review, agent-debugging,
agents-sdk and agent-evals (the latter three for the browser-discovered lookup blocker).
