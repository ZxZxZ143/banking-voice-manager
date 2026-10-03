# Stage 5A analytics backend contract

Dashboard/frontend is owned separately and is not implemented or integrated in Stage 5A.
All endpoints are read-only, deterministic and use existing structured application results.
Storage adds **zero LLM calls**. OpenAPI: backend `GET /openapi.json` on port 8000.
The existing frontend proxy forwards `/api` and `/health`, not `/openapi.json`.

## Base URL and access

Use relative `/api/analytics/...` through the existing Vite/Nginx same-origin proxy.
Docker demo origin: `http://127.0.0.1:5173`; direct backend: `http://127.0.0.1:8000`.
No CORS changes or authentication were introduced. This is a loopback/local demo boundary.
Session IDs are correlation identifiers, not credentials; clients must generate opaque IDs
and must not encode phone numbers, customer identities or secrets in them.

## Endpoints

| Method/path | Response model | Purpose |
|---|---|---|
| `GET /api/analytics/events` | `EventPage` | Filtered recent events |
| `GET /api/analytics/sessions/{session_id}` | `SessionEvents` | Ordered session/journey events |
| `GET /api/analytics/summary` | `AnalyticsSummary` | Aggregates across the filtered period |

No separate risk/sales/fraud endpoints exist. Filter events by `event_type`; summary exposes
these categories. No write/delete API exists.

## Parameters, dates and pagination

Events and summary accept these optional parameters:

| Parameter | Values/default |
|---|---|
| `from` | ISO 8601 date-time with timezone, inclusive lower bound |
| `to` | ISO 8601 date-time with timezone, exclusive upper bound |
| `assistant_id` | One assistant enum below |
| `event_type` | One event enum below |
| `risk_level` | `none`, `low`, `medium`, `high`, `critical` |
| `channel` | `text`, `voice` (matches the existing application contract) |
| `source` | `runtime`, `synthetic_demo` |
| `limit` | Integer 1–500, default 100 |
| `offset` | Integer 0–1,000,000, default 0 |

Session endpoint accepts only `limit` and `offset`; `session_id` length is 1–128.
`from` must precede `to` when both are supplied. Naive dates, invalid enums and out-of-range
pagination return 422. Omitting dates means all stored history. All filters are combined
with AND. Summary accepts pagination for contract consistency but **ignores it in aggregates**.
Do not interpret a summary as a count of just the current event page.

Event `created_at` is UTC ISO 8601 with `Z`; health timestamps are UTC. Period echoes the
requested timezone-aware bounds. Example: `2026-10-03T08:00:00Z`. For a literal `+` offset
in a URL, percent-encode it, or use the HTTP client's query parameter encoder.

Event list order is `created_at DESC`, then session, turn, sequence, event UUID. Within a
session order is `turn_number ASC`, `sequence ASC`, `created_at ASC`, UUID. Never reconstruct
a journey from timestamps alone. A page includes `total`, `limit`, `offset`, `next_offset`;
null `next_offset` means complete. Fetch subsequent pages with that offset. Count and rows
use one database read snapshot. Offset pages across separate requests can shift if new
events arrive; refresh the first page to obtain a fresh view.

## ConversationEvent schema v1

```json
{
  "event_id": "071b5c4b-a828-5f9a-a10c-1457a2d5299c",
  "schema_version": 1,
  "created_at": "2026-10-03T08:00:00Z",
  "session_id": "opaque-demo-session",
  "turn_number": 4,
  "sequence": 2,
  "channel": "voice",
  "assistant_id": "card_promoter",
  "event_type": "risk_signal",
  "conversation_status": "active",
  "scenario_id": null,
  "risk_level": "high",
  "risk_signals": ["bank_impersonation", "otp_requested_by_third_party"],
  "result_status": null,
  "source": "runtime",
  "payload": {
    "kind": "risk_signal",
    "analysis_status": "analyzed",
    "recommended_action": "security_review",
    "guidance_shown": ["do_not_share_secrets", "official_channels"]
  }
}
```

All displayed keys are present. Nullable fields use JSON null, lists use [] when empty.
`event_id` is a stable UUID derived from the idempotency key; do not infer time from it.
Turn numbers start at 1; sequence starts at 0 within a committed turn. Sequence gaps are
possible if a repeated terminal/start event is ignored. Payload is a **typed discriminated
union** (`kind` equals `event_type`), not arbitrary metadata. OpenAPI defines every variant.

Assistant IDs: `insurance_manager`, `product_promoter` (deposit campaign), `card_promoter`,
`loan_promoter`, `fraud_security`.

Conversation/result statuses: `active`, `awaiting_user`, `awaiting_confirmation`, `handoff`,
`ended`. The confirmation status is reserved by the existing runtime.

| Event type / payload kind | Payload fields besides `kind` |
|---|---|
| `conversation_started` | `assistant_initiated: boolean` |
| `conversation_turn` | `assistant_initiated: boolean` |
| `assistant_selected` | `previous_assistant_id: AssistantId or null` |
| `insurance_result` | `completed`, `handoff` booleans; `actions: ActionName[]` |
| `sales_lead` | `campaign`, `product_category or null`, `selected_product_id or null`, `presented_product_ids`, `outcome`, `interest_level`, `next_action`, `completed`, `handoff` |
| `fraud_case` | `case_type`, `case_status`, `facts: RiskSignal[]`, `recommended_action`, `guidance_shown`, `completed`, `handoff` |
| `risk_signal` | `analysis_status`, `recommended_action`, `guidance_shown` |
| `operator_handoff` | No additional fields |
| `conversation_ended` | No additional fields |

Initial successful opener or first customer turn emits started and selected. Openers have
`assistant_initiated=true` and contain no artificial user message. Selection is emitted
again only on explicit assistant changes. Each committed turn has one conversation_turn.
Business result events are snapshots, including openers. Security guidance that preserves
the business result emits no redundant business result snapshot; explicit terminal guidance
does emit the updated result status/handoff/completion. Handoff/end events occur
only when the core commits the corresponding terminal state; no real operator dispatch
is implied. Failed/rolled-back business requests emit no events.

Insurance `scenario_id` is a catalog-approved SCxx/SYS ID or null; action names:
`kb_lookup`, `get_offices`, `find_client`, `get_policy`, `get_claim`. Other arbitrary strings
are dropped, never persisted. Product IDs are approved by the loaded catalog (currently
DEP-FLEX, DEP-SAVE, DEP-USD, CARD-DAILY, CARD-REWARD, CARD-CASH, LOAN-PERSONAL, LOAN-DIGITAL).

Sales enums:

- Campaign/category: `deposit`, `card`, `loan`.
- Outcome: `consulting`, `interested`, `declined`, `handoff`, `ended`.
- Interest: `unknown`, `low`, `medium`, `high`, `declined`.
- Next action: `continue_consultation`, `application_interest`, `send_application_link`,
  `callback_requested`, `operator_handoff`, `declined`.

Fraud case type: `none`, `social_engineering`, `transaction`, `phishing`, `remote_access`,
`account_access`, `lost_card`, `credential_exposure`. Case status: `open`, `informed`,
`needs_review`. These are advisory categories, not confirmed fraud findings.

RiskSignal values:

```text
bank_impersonation otp_requested_by_third_party otp_disclosed credential_disclosed
pin_or_password_requested cvv_requested suspicious_link remote_access_requested
remote_access_installed unknown_transaction account_takeover_concern
unauthorized_contact_change transfer_under_pressure lost_stolen_card coerced_transfer_sent
```

Risk recommended action: `none`, `show_security_guidance`, `security_review`,
`urgent_security_review`, `operator_handoff`.
Analysis status: `analyzed`, `unavailable`, `invalid_output`. An unavailable attempt may
produce a risk_signal with level `none` and empty signals; this **does not certify safety**.
Ordinary analyzed/nonrelevant turns generate no risk_signal.

Guidance enums: `do_not_share_secrets`, `end_suspicious_call`, `avoid_link`,
`avoid_remote_access`, `no_safe_account_transfer`, `official_channels`, `exposure_review`,
`transaction_review`, `card_review`, `account_review`, `remote_review`.

## Page and journey examples

```json
{"events": [], "total": 0, "limit": 100, "offset": 0, "next_offset": null}
```

Session response adds `session_id` and `channel`. Channel is the first event's channel,
even on later pages; individual events can differ. Unknown sessions return 200 with an
empty page and `channel: null`. An out-of-range offset returns [] with the actual total.

## Summary schema and count semantics

Empty store:

```json
{
  "period": {"from": null, "to": null},
  "conversations": 0,
  "handoffs": 0,
  "event_counts": {},
  "results_by_assistant": {},
  "risk": {"total": 0, "high": 0, "critical": 0, "levels": {}, "signals": {}},
  "sales": {"leads": 0, "interested": 0, "declined": 0, "outcomes": {}},
  "fraud_cases": 0,
  "fraud_case_types": {}
}
```

- `conversations`: distinct session IDs with **any matching event** in the period.
- `event_counts`: raw matching snapshot/event counts by event type.
- `handoffs`: matching operator_handoff events (unique per session).
- `results_by_assistant`: latest matching result per session/assistant/result type.
- `sales`: latest matching sales snapshot per session/assistant; leads include consulting,
  interested, declined, handoff and ended, rather than only application consents.
- `fraud_cases`, `fraud_case_types`: latest matching fraud snapshot per session/assistant,
  excluding case_type=none (e.g. opener).
- `risk.total`: risk_signal events with a non-none risk level. High/critical count these
  triage levels. `levels` additionally includes none for unavailable attempts.
  `signals` counts each signal occurrence in risk_signal events only, avoiding duplication
  from fraud_case facts; key order is descending count, then enum name.

Result deduplication is **within the filtered period**, not the lifetime outcome outside
it. A conversation continuing today can appear today even if it began yesterday. Summary
filters all events before aggregation; filtering only risk_signal naturally gives zero
sales. Missing count-map keys mean zero. No LLM summary, customer profile or anomaly verdict
is returned. Time-window event/signal/assistant counts are supported through indexed filters.

## Errors and storage health

- Invalid params: 422 FastAPI `detail` validation list; reversed/equal time bounds include
  a `query.from` error with message `from must be before to`.
- Storage read failure: 503, `{"detail":{"code":"analytics_storage_unavailable",
  "message":"Analytics storage unavailable"}}`. No paths/SQL/exception text are returned.
- `GET /health` remains 200 for the functioning application and adds `analytics`:
  `status=ok|degraded`, `backend=sqlite`, `failure_count`, `last_error`, `last_failure_at`.
  Error codes are `storage_unavailable`, `event_mapping_failed`; no absolute host path.
  Counts include initialization, mapping, write and API read failures. Successful writes
  clear the current error; lifetime process failure count and last-failure time remain.
- Writes occur after customer state/result/trace commit. Storage failure never changes an
  otherwise successful response. Lost events are logged with a fixed code; there is no
  durable outbox or automatic replay. Health counters reset on process restart.

## Persistence and privacy

`EVENT_DB_PATH` defaults to `data/runtime/veyra_events.db` at the repository root. Docker
sets `/app/data/runtime/veyra_events.db` in the `analytics_data` named volume, owned by the
non-root backend user. `docker compose down` followed by `up` retains the volume; deleting
the volume is destructive and is not part of validation. DB/WAL/SHM files are Git-ignored
and excluded from Docker build context. Analytics persists; conversation state remains
in-memory. Start a fresh opaque session ID after backend restart; analytics is not a
conversation-resume or authentication store.

Stored payloads contain only allowlisted enums, booleans and catalog IDs. No phone, IIN,
card number, OTP, PIN, CVV, password, credentials, customer preferences/amounts, collected
data, raw transcript, assistant reply, free-text risk reason, source text or full trace is
serialized. A risk signal such as `otp_disclosed` records the category, never the code.

## Synthetic demo data

From repository root after backend installation:

```powershell
./.venv/Scripts/python.exe scripts/seed_analytics_demo.py
./.venv/Scripts/python.exe scripts/seed_analytics_demo.py --reset
# Isolated local fixture:
./.venv/Scripts/python.exe scripts/seed_analytics_demo.py --db-path work/analytics-demo.db
```

Seed dates are deterministic: 2026-10-03 08:00–09:59 UTC. It creates 120 conversations,
24 insurance results, 72 sales results, 40 risk signals, 24 fraud results, 12 handoffs,
108 ended events; 640 total events. All have `source=synthetic_demo`. Rerun inserts zero.
`--reset` deletes only synthetic_demo rows, then recreates the seed; runtime rows survive.
To seed Docker's actual volume, stream the script into the existing backend, since image
runtime deliberately contains application/data only:

```powershell
Get-Content -Raw scripts/seed_analytics_demo.py | docker compose exec -T backend python -
```

Filter `source=runtime` for live data or `source=synthetic_demo` for fixtures. Never mix
synthetic counts into operational metrics accidentally.

## Frontend integration checklist

- Base endpoint: relative `/api/analytics` through the existing proxy.
- Summary endpoint: `GET /api/analytics/summary` with period/filter parameters.
- Events endpoint: `GET /api/analytics/events` with limit/offset and filters.
- Session/journey endpoint: `GET /api/analytics/sessions/{encoded_session_id}`.
- Risk endpoint: `GET /api/analytics/risk` (Stage 5B); event/summary endpoints remain available.
- Enums: use the documented values/OpenAPI; display unknown future schema versions safely.
- Date format: ISO 8601 with timezone, events in UTC Z; from inclusive/to exclusive.
- Pagination: default 100, max 500, next_offset/null; journey also paginated.
- Empty responses: render zero scalars, missing count-map keys as zero, [] and nullable channel.
- Synthetic seed command: `python scripts/seed_analytics_demo.py` in the installed backend
  environment; optional `--reset` or `--db-path`. Select source=synthetic_demo.
- Show read errors/degraded storage honestly. Integrated dashboard: `FINANCE_DASHBOARD.md`.

## Stage 5B additive dashboard contract

The three Stage 5A endpoints and their response models remain unchanged. New read-only
routes are implemented in `backend/app/api/routes/dashboard.py`, models in
`analytics/dashboard_models.py`, deterministic reads in `analytics/dashboard.py`, using
EventStore snapshot/history methods implemented by SQLiteEventStore.

| GET /api/analytics suffix | Response |
|---|---|
| `/overview` | DashboardOverview: full selected sessions, recency, channels, assistant/status/source counts, handoffs, RiskAnalytics, sales outcomes, completed Insurance results; unavailable latency/clarification null |
| `/sessions` | SessionPage: `sessions,total,limit,offset,next_offset` |
| `/sessions/{session_id}/detail` | DashboardSessionDetail: full `summary`, bounded raw safe `timeline`, meaningful `journey` from that event page, pagination |
| `/sessions/{session_id}/journey` | JourneyPage: bounded `stages`, pagination; unchanged event ordering |
| `/risk` | RiskAnalytics: levels unknown/none/low/medium/high/critical, high-risk sessions, unique-session signals/associated assistants, latest case types |
| `/scenarios` | RankedCount[]: unique session count per observed assistant ID (five bounded catalog keys) |
| `/anomalies` | AnomalyPage: `anomalies,history_status,as_of`, pagination |

Session aggregates group the full retained source/session history before applying
`assistant_id` (any observed assistant), channel (latest turn), risk_level (highest analyzed
level), active and from/to (latest event time inclusive/exclusive). `session_id` is exact.
These endpoints accept source/runtime/synthetic_demo, aware `as_of`, bounded limit/offset.
The aggregate endpoints ignore page size when calculating totals. `scenarios` is the
dashboard's legacy field name for **assistant IDs**; approved Insurance scenario IDs are
separate `scenario_ids` in session summaries. The frontend's scenario filter maps to
validated `assistant_id`, not guessed intent strings.

Detail/journey accept source, as_of, limit, offset and encoded path session ID. Unknown
detail → typed 404 `analytics_session_not_found`; unknown journey → empty page. Original
`/sessions/{session_id}` remains SessionEvents, including its prior empty 200 behavior.
Anomalies accept source/assistant/channel/session/as_of/limit/offset. They reject from/to,
active and risk_level with 422 because the comparison uses configured equal windows.
The existing event endpoint retains event_type filtering; no unused dashboard event-type
control was added. Invalid enums/ranges/naive timestamps → 422. Store failure → the same
typed 503 `analytics_storage_unavailable`, never a fabricated aggregate.

Session summaries include start/latest/end, collapsed assistant sequence, latest assistant,
source runtime/synthetic_demo/mixed, final status, highest **analyzed** risk or unknown,
safe signals, handoff, normal-ended flag, max committed turn, latest result per
assistant/type, and partial_history when the start event is missing. Active requires no
terminal event and activity in the previous five minutes. Duration uses stored timestamps;
same-turn timestamps can legitimately give zero. None means analyzed/no observed signal;
unknown means no analyzed risk event. Risk categories remain advisory. A result's completed
flag is not a real policy write, sale, verified incident or operator transfer.

Anomaly settings, cold-start and count semantics, seed extension and restart commands:
`FINANCE_DASHBOARD.md`. Source baselines are always separate. Public pages remain bounded;
internal aggregates materialize the full selected safe history at current local demo scale.
