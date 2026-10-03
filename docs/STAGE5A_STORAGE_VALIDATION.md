# Stage 5A persistent storage validation

Validated 2026-10-03 on the existing `main` repository, preserving the Stage 4 assistants,
Risk behavior and voice/runtime contracts. Dashboard/frontend is owned separately and was
neither implemented, merged nor modified. No application LLM call was added by storage.
Skills actually used: **agent-evals** (deterministic regressions) and **security-review**.

## Architecture and schema

`ConversationEvent` in `backend/app/analytics/models.py` defines schema version 1, stable
event enums, opaque session correlation, committed turn number, per-turn sequence, UTC
timestamp, assistant/channel/status, optional scenario/risk/result metadata, source, and a
typed discriminated payload. EventStore is a protocol; SQLiteEventStore owns all SQL.

`events` contains event_id, schema_version, created_at, session_id, turn_number, sequence,
channel, assistant_id, event_type, conversation_status, scenario_id, risk_level,
risk_signals_json, result_status, source, payload_json and unique idempotency_key. Indexes
cover created_at, session/turn/sequence/time, assistant/time, event_type/time, risk/time,
and source. PRAGMA user_version=1 guards schema compatibility. SQLite uses WAL and private,
closed connections per operation with 100-ms lock timeout. No ORM or new package/service
is required. Explicit migration is required for a future schema version.

MessageService validates/commits existing state, result and trace first. EventRecorder
then maps safe fields and appends the entire turn batch in one transaction via a worker
thread. A failed business turn emits nothing. A failed DB write keeps the valid customer
response and emits only a fixed operational error code, plus degraded analytics health.
There is no durable outbox/replay; failed writes can lose events. Health counters reset
per process. No aggregates run during ordinary customer turns.

Idempotency hashes source/session/turn/event_type. Started/handoff/ended use a session-wide
key instead of turn. UUIDs derive deterministically from the hash. Unique constraint
ignores retried events, without overwriting original data. Invalid/colliding batches roll
back completely. Session reconstruction orders by turn/sequence/time/UUID, not time alone.

## Result mapping and privacy

| Existing output/state | Event | Stored projection |
|---|---|---|
| InsuranceResult | insurance_result | Catalog scenario, status, completed, handoff, allowlisted action names |
| SalesLeadResult | sales_lead | Assigned campaign/category, approved product IDs, outcome, interest, next action, completion/handoff |
| FraudCaseResult | fraud_case | Case type/status, signal enums, advisory level/action, guidance, completion/handoff |
| Relevant/failed RiskAssessment | risk_signal | Analysis status, level, signal enums, action and guidance, active assistant/channel |
| Committed handoff | operator_handoff | Terminal metadata only |
| Committed ended | conversation_ended | Terminal metadata only |

The initial opener/first customer turn creates conversation_started and assistant_selected;
committed turns create conversation_turn. Openers never fabricate a customer message.
Explicit switches emit assistant_selected. Security guidance retaining an unchanged
business result emits no redundant business snapshot; explicit terminal guidance persists
the updated result status. Risk signals work across all active assistants.

No full result/state/trace serialization is used. Collected phone/IIN/card values,
OTP/PIN/CVV/password/API credentials, raw user/assistant transcripts, preferences/amounts,
source text and free-text Risk reasons/errors are excluded. Synthetic secret values were
injected into result fixtures and API input; payloads/DB content contained none of their
private values. Short numeric fixtures are compared as values to avoid coincidence with
random UUID/hash digits. Schema-boundary revalidation also rejects arbitrary payload keys
introduced through unchecked model copies, without printing serializer warnings.

## APIs and teammate handoff

- `GET /api/analytics/events`: typed EventPage, bounded filters and limit/offset.
- `GET /api/analytics/sessions/{session_id}`: typed ordered SessionEvents/journey.
- `GET /api/analytics/summary`: typed deterministic aggregates.

Filters: timezone-aware from/to (inclusive/exclusive), assistant_id, event_type, risk_level,
channel and source. Default page 100, maximum 500; offset maximum 1,000,000. Invalid values
return 422; DB read failure returns a fixed typed 503. Unknown sessions return an empty
200 response. Summary counts latest matching result per session/assistant within the
period; raw event counts remain separately available. Risk signals count risk_signal
only, avoiding duplication from Fraud facts. SQL values are bound parameters.

All routes and discriminated schemas appear in backend OpenAPI. Existing Nginx/Vite proxy
already forwards /api and /health; it does not forward /openapi.json. OpenAPI checks use
direct backend port 8000. No broad CORS or frontend changes were made. The complete public
schemas/enums/errors/date/count semantics/empty states and Stage 5B integration checklist
are in `ANALYTICS_API_CONTRACT.md`.

## Docker, real events and restart persistence

Compose retains the existing backend/frontend services and loopback ports. EVENT_DB_PATH
is /app/data/runtime/veyra_events.db in named volume `insurance-manager_analytics_data`.
The directory is owned by the existing non-root backend user. Native default is repository
data/runtime/veyra_events.db. DB/WAL/SHM/runtime artifacts are Git-ignored and excluded from
Docker build context. No existing volume was deleted.

The corrected `scripts/stage5a_storage_smoke.py create` made **10 real conversation/start
requests** through Docker Nginx on port 5173, using the configured real provider for normal
Insurance, Sales and Risk/Fraud decisions. Four sessions produced **32 safe events**:

| Event type | Count |
|---|---:|
| conversation_started | 4 |
| assistant_selected | 4 |
| conversation_turn | 10 |
| insurance_result | 4 |
| sales_lead | 2 |
| risk_signal | 3 |
| fraud_case | 3 |
| operator_handoff | 1 |
| conversation_ended | 1 |

Insurance answered an office question, Card recorded an application-interest flow, an
OTP request triggered advisory Risk while the exact public SalesLeadResult survived,
Fraud handled a caller/code concern and code-disclosure handoff, and Insurance goodbye
ended its session. All responses were successful and contained valid response text.
The transcript-to-core channel=voice contract was exercised with synthetic text; STT/TTS
hardware was not rerun for this backend-only stage.

An earlier attempt successfully created the same 32 events but failed its final OpenAPI
check because it used the frontend origin. The script was corrected to check backend
OpenAPI before creating conversations, then rerun successfully. These earlier events are
still valid runtime events; no data was silently removed.

With both live runs and the seed, SQLite had **704 rows: runtime=64, synthetic_demo=640**.
Before restart, all 704 IDs were captured in two bounded API pages and DB row count was
confirmed inside the container. Actual checks:

1. `docker compose restart backend`: the four smoke sessions retained the same 32 IDs,
   and all 704 stored IDs matched exactly.
2. `docker compose down` then `docker compose up -d`, without -v: again all 704 IDs matched
   exactly, including the 32 manifest events. Both services restarted successfully.
3. Final backend rebuild/recreation retained existing events and the typed API contracts.

Evidence is local/ignored: work/stage5a-live-events.json and
work/stage5a-volume-before.json contain only safe session/event IDs and counts. Application
conversation state/traces remain intentionally in-memory; restart persistence covers
analytics, not resuming an authenticated customer workflow. New sessions need fresh IDs.

## Seed and reset

`python scripts/seed_analytics_demo.py` in the installed backend environment creates
120 deterministic synthetic conversations: 24 insurance results, 72 sales leads,
40 risk signals, 24 fraud cases, 12 handoffs, 108 ended events; **640 total events**.
All rows have source=synthetic_demo and fixed 2026-10-03 UTC dates. The actual script was
run on a separate local DB and inside the Docker volume. A second local run inserted 0.
Local --reset removed 640 synthetic rows and recreated 640; an automated mixed-source
test confirms runtime events survive reset. No all-data wipe flag or delete API exists.

## Measured performance

`scripts/benchmark_analytics.py` uses an explicit new DB with **840 rows**: 640 synthetic
events plus 200 independently appended events. Timings include connection, validation,
transaction and commit; append has 200 samples and each query has 50. Docker benchmark DB
was temporary under /tmp, separate from runtime. Query p95 is the 48th of 50 sorted samples.

| Operation | Native Windows p50 / p95 ms | Docker Linux p50 / p95 ms |
|---|---:|---:|
| Single SQLite append | 5.52 / 6.47 | 7.00 / 8.68 |
| Summary query | 2.09 / 2.70 | 1.82 / 2.11 |
| Filtered events (high risk_signal) | 1.42 / 1.76 | 0.99 / 1.42 |
| Session events | 1.05 / 1.33 | 0.62 / 0.74 |

These are measured local/demo workloads, not production-scale guarantees. Normal customer
turns append multiple events in one commit. Existing trace timings are preserved and
exclude the new post-commit storage wait; the measurements above cover storage separately.

## Regression and security review

- **700 backend tests passed** (648 existing + 52 added), final full run 23.15 seconds.
- **49 existing frontend tests passed**; TypeScript typecheck and production Vite build
  passed. No frontend source, styles, routes, dashboard files or teammate branches changed.
- Ruff lint and format checks passed for backend/app and backend/tests; new scripts also
  passed checks. git diff --check passed.
- New checks cover schema/WAL/index initialization, append/batches, idempotency, restart,
  rollback atomicity, parallel writes, session/time/filter/page queries, aggregate snapshot
  semantics, all result mappings, private inputs/fields, synthetic-only reset, unavailable
  storage, log sanitization, OpenAPI and terminal Risk result mapping.
- Existing complete offline Insurance, Sales, Fraud/Risk/core/voice contract suites ran.
  Live regression here was the focused real Docker smoke above; the 104-case Insurance,
  Product and 50-case Fraud/Risk provider evaluation datasets were not rerun, since no
  routing prompts, SDK transport or classification policies changed.

Focused security review traced application result → allowlisted mapping → validated
SQLite rows → bound read queries → typed API. The actual configured API key and personal
demo phone (plus phone digit variants) were loaded only inside a local scanner and never
printed. Current source/frontend build files, both image configs, backend container logs,
and all 704 SQLite rows and database sidecar files were scanned with no matches. Inspection
confirmed ignored .env/runtime DB/build-context boundaries, non-root volume ownership,
bounded enum queries, opaque demo session IDs and absence of data-changing API routes.

## Remaining limitations and next stage

- Analytics is best-effort after business commit, with no durable outbox/replay. Storage
  outages can leave gaps despite successful conversations.
- No authentication/authorization, retention/backup policy or encryption was introduced;
  the existing loopback synthetic-demo boundary remains. Session ID is not authentication.
- SQLite and summary timings were measured at 840 rows; large deployments need separate
  capacity tests and potentially a different EventStore implementation.
- Offset pages can shift while new data arrives. Active state/traces reset after restart.
- Anomaly detection is deferred; indexed historical event/signal/assistant time queries
  provide its storage foundation. No confirmed-attack inference or LLM summary exists.
- STT/TTS/browser interaction was not retested live; all existing voice/runtime offline
  checks passed. Teammate dashboard integration, visual design, mocks and branch merge
  are explicitly Stage 5B work.
- Known **O11** remains: a card-campaign deposit request may be interpreted as decline
  instead of out_of_scope. Existing model variability was not changed or concealed.

Git deliverable is committed/pushed on existing main; actual commit IDs and push/working
tree status are reported in the final task response. Runtime DB, .env, work/, local logs,
benchmarks and evidence artifacts are excluded from the commit.
