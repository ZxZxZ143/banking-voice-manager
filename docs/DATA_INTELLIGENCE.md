# Backend Data Intelligence

Implemented MVP for Veyra's future Finance Supervisor Dashboard. Backend events are
canonical for analytics; the existing frontend store remains local interface state.
Only `web` and `phone` are product channels. No dashboard UI was added. Future UI
must use shadcn/ui. Risk analysis and financial routing belong to Agent Intelligence.

```text
/api/message ───────────────┐
                           ├→ ConversationEvent → shared app EventStore
Vonage/Twilio PhoneRuntime ─┘                       ↓
                                       Session Summary / Journey / Anomalies
                                                   ↓
                                           Analytics polling API
                                                   ↓
                                     Future shadcn/ui supervisor dashboard
```

## Runtime and access

The app lifespan creates one `InMemoryEventStore` and `AnalyticsService`, then injects
that store into both enabled phone gateways. Web events go to the same store.
Collection works even when the analytics API is disabled. There is no client event
write endpoint. Existing telephony authentication remains unchanged.

Analytics exposes transcripts and opaque Agent payloads, so all seven routes require
`ANALYTICS_ENABLED=true` and a nonblank server-side `ANALYTICS_API_TOKEN`. Requests
must supply `Authorization: Bearer <supervisor token>`. Missing/wrong authorization
returns 403; disabled/unconfigured analytics returns 503. Set the token only in the
ignored root `.env` or server environment. Do not put it in `VITE_*`, commit it, or
embed it in a public frontend bundle. A future dashboard needs an authenticated
operator boundary; this shared-token MVP is not individual-user RBAC. TLS is required
when accessed remotely. CORS permits Authorization only for the configured frontend
origin. No public unauthenticated supervisor feed was introduced.

Settings in `.env.example`:

| Name | Default | Meaning |
|---|---|---|
| `ANALYTICS_ENABLED` | false | Enable authenticated polling routes |
| `ANALYTICS_API_TOKEN` | empty | Supervisor-only secret; `SecretStr` in Settings |
| `ANALYTICS_DEMO_ENABLED` | false | Explicitly seed synthetic records at app startup |
| `ANALYTICS_MAX_EVENTS` | 5000 | Retained events; allowed 100–100000 |
| `ANALYTICS_WINDOW_SECONDS` | 3600 | Current rolling window; allowed 60–86400 |
| `ANALYTICS_BASELINE_WINDOWS` | 6 | Preceding equivalent windows; allowed 1–168 |
| `ANALYTICS_MIN_VOLUME` | 5 | Minimum current events; allowed 1–10000 |
| `ANALYTICS_ANOMALY_MULTIPLIER` | 3 | Current/expected threshold; allowed 2–100 |

Normal startup is unchanged:

```powershell
./.venv/Scripts/python.exe -m app.main
./.venv/Scripts/python.exe scripts/smoke_data_intelligence.py
```

On this development machine the existing environment is
`/private/tmp/veyra-foundation-venv/bin/python`. The smoke ignores `.env`, makes no
network calls, and uses a fixed synthetic clock. It does not seed a running app.
To demonstrate polling, explicitly enable both analytics and demo seeding in your
local ignored configuration. Disable demo seeding for real-call analytics; demo and
real records otherwise intentionally share the store.

## Canonical event and storage contracts

`backend/app/events/models.py` keeps the existing frontend-compatible envelope:
required `id` (generated UUID by default), `session_id`, timezone-aware ISO
`timestamp` (UTC now by default), `event_type`, `channel`. Optional nullable fields:
`language`, `text`, `scenario`, `action`, `confidence`, `conversation_status`,
`clarification`, `handoff`, `risk`, `routing`, `state`, `trace`, `latency`, `metadata`.
Unknown additive envelope fields remain allowed. Optional Agent objects are JSON
values; analytics does not change their business semantics.

Exactly seven event types: `session.started`, `transcript.final`, `agent.response`,
`scenario.selected`, `clarification.requested`, `handoff.requested`,
`conversation.ended`. Partial STT text is not recorded as a turn.

`EventStore` supports:

- `append(event)` with defensive copies, a 64 KiB serialized per-event bound, and
  oldest-first eviction when the configured count capacity is reached.
- `get_by_session(session_id)` and `list(session_id, channel, event_type, scenario,
  risk_level, from_time, to_time, limit)` using optional keyword filters.
- `update_latency(event_id, values)` to expose already-measured phone timings on a
  retained Agent event; false when the event has already been evicted.

Append order is authoritative, even for equal or older timestamps. Reads return
copies. A lock protects concurrent event appends, timing updates, and read snapshots.
Time bounds are timezone-aware and inclusive. Store `limit=0` returns no events;
negative limits/ranges and naive timestamps are rejected. Event risk filtering uses
that event's explicit risk, unlike session risk filtering below.

Storage is intentionally process-local and bounded, not durable. Restart loses
records. Multiple app workers have separate stores: use one worker for this MVP.
The default worst-case serialized allowance is 5000 × 64 KiB, plus Python object
and query-copy overhead. Oversized events fail with safe static recording warnings;
recording failures do not break a conversation. Overview exposes retained count,
capacity, and cumulative evictions; counts always describe retained history, not an
all-time customer population. Anomaly `partial_history` flags eviction. Session
`partial_history` flags a missing retained start; it cannot detect every intermediate
lost event. Polling is eventually consistent across concurrent turns, not a database
transaction spanning an entire report. Persistence is deferred.

## Web and phone ingestion

Successful `/api/message` responses generate server-owned session start (once while
retained and Agent turn=1), final transcript, Agent response, selected scenario, explicit clarification
or handoff, and Agent terminal events as applicable. Failed Agent calls do not create
successful analytics turns. An evicted continuing session does not get a fabricated new
start: its summary reports missing start/partial history. The current web client needs no change to produce server
analytics. Browser Stop/reset and browser TTS completion are not visible to this
backend; they are not fabricated as canonical terminal or playback events.

Optional request addition:

```json
{
  "session_id": "your-web-session-id",
  "text": "user utterance",
  "transport": {"language": "kk", "stt_after_commit_ms": 125}
}
```

`transport.language` accepts only ru/kk/mixed; timing is finite, nonnegative, at most
150000 ms. Extra transport fields are forbidden. Frontend routing/risk/scenario/action
fields are rejected and cannot override Agent decisions. Timing is labelled
`client_stt_final_ms`, separate from trusted phone timing. Channel is always web.
A retained phone session ID on `/api/message` returns 409 `channel_conflict`. Web
latency measures the server's existing message processing. `MessageResult.risk` is an
optional passthrough field; absent risk is omitted to preserve the old HTTP shape.
No analyzer, financial routing, Agent model, prompt, or response logic was changed.

PhoneRuntime continues its existing events, same Agent UUID across turns, half-duplex
behavior, and provider playback acknowledgements. Minimal changes add turn numbers
and copy existing measured latency onto `agent.response`; TTS latency becomes visible
at TTS readiness, complete-turn metrics after playback acknowledgement. There are no
new waits or changes to endpointing, audio, STT, Agent, TTS, transport, or backpressure.
Provider metadata includes retained provider/call UUID/SID/stream identifiers.

## Agent extraction boundary

`events/normalize.py` isolates field assumptions; `response_events()` reuses it.
Exact current reads:

| Source | Fields read / priority |
|---|---|
| Top-level | `response_text`, `conversation_status`; opaque `risk`, `routing`, `state`, `trace` preserved |
| routing | `scenarios`, fallback `selections`, each string or `{scenario_id, confidence, ...}`; used only when `trace.scenarios` is not a list. `clarification_question`; `language` fallback |
| risk | `level`: unknown/low/medium/high/critical, else unknown. `signals`: strings or objects using first string `code`, then `type`, then `id`; nonempty keys ≤128 chars, unique. `recommended_action` is preserved in opaque risk but not executed or used for classification |
| state | `language` only as a fallback after trace/routing; other fields preserved, not interpreted as scenario transitions |
| trace | `scenarios` takes precedence, `language`, `actions`, `clarification === true`, `handoff === true`, `latency_ms`, and `turn`/`turn_number` for latency correlation |
| event metadata | `turn` first for latency correlation; whitelist provider/call UUID/SID/stream identifiers and `demo` for summary metadata |

Unknown optional formats are ignored for aggregation, while original JSON remains
available in the protected timeline. No additional scenario aliases are guessed.
Risk absence never means low. Structured RiskSignal originates from Agent; demo risk
is explicitly synthetic. No risk scoring or LLM analytics call was added.

## Session summary and journey

`ConversationSessionSummary` includes session/channel, nullable start/end, latest event
time/language, ordered unique scenarios, primary and last scenario, highest observed
known risk and unique signals, latest raw risk, clarification count, handoff,
completed/active/status, response turn count, nullable duration and average Agent/TTS
latency, latest turn timings, provider metadata, partial-history flag.

Primary scenario is the most frequently explicitly selected scenario; equal counts
sort by key. Highest risk is retained even if a later Agent response omits risk.
Latest raw risk can therefore be null while highest observed risk is high. Duration
requires both retained timestamps and a nonnegative interval. `completed` means
explicit normal session termination (`phone_status=ended` or Agent status ended),
not confirmed business action success. Handoff/error/cancellation are distinct.
`active` is an MVP heuristic: retained start, no end/terminal status, last event within
five minutes and not future-dated. It is not provider presence or a live speaking flag.
Recent sessions also mean last event within five minutes.

`JourneyEvent` contains ID/session/timestamp/scenario/action/source_event_id/channel
and clarification/handoff/completion flags. Derivation follows append order of explicit
selected scenarios and lifecycle transitions. Adjacent repeated scenario with the
same action collapses; changed action or intervening lifecycle stage remains. Handoff
appears where recorded; absent supplied scenario remains null rather than inventing
`OPERATOR`. Terminal normal completion is flagged only when explicit. The timeline
still retains every source event, including collapsed selections. This is a Customer
Intent Journey foundation, not a full enterprise CJM suite.

## Aggregates, latency, and anomalies

Overview provides total, active, recent, channels, scenario session counts, statuses,
clarification event count, clarification-session rate, handoff-session count/rate,
risk distribution, high/critical session count, signal session counts, associated
high-risk scenario session counts, timings, and storage limits. Zero-session rates
are zero. Signal/scenario association is not causation. Ranked ties sort by key.

Latency entries have `{average_ms: number|null, samples: number}`. Samples are
per retained turn, with transcript and response merged by turn number. Cloned
scenario/clarification events do not multiply timing samples. Missing, negative,
boolean, nonnumeric or nonfinite timings are excluded; missing values are never zero.

| Metric | Meaning |
|---|---|
| `endpointing_ms` | Last available speech/activity end → endpoint decision |
| `stt_final_ms` | Endpoint/commit → final STT; legacy transcript `stt` also maps here |
| `agent_ms` | Agent/backend message processing; legacy trace `total`, never phone end-to-end |
| `tts_ms` | Backend TTS request → full ready audio |
| `tts_first_audio_ms` | Optional supplied legacy `tts_first_audio`; missing if unmeasured |
| `speech_end_to_playback_submit_ms` | Speech/activity end → provider audio submission, not confirmed acoustic onset |
| `speech_end_to_playback_complete_ms` | Speech/activity end → provider playback acknowledgement |
| `final_to_playback_complete_ms` | STT final → provider playback acknowledgement |
| `client_stt_final_ms` | Optional browser-supplied STT after commit; distinct provenance |

Current browser TTS timings are not known server-side. Manual phone finals without
speech/end/endpoint measurements cannot contribute those metrics. Acoustic onset is
not measured. Providers' existing acknowledgements define playback completion; mocks
only acknowledge an offline sink and do not measure a real phone.

Anomalies count explicit `scenario.selected` occurrences and unique signal keys per
`agent.response`. Multiple turns can contribute multiple events; these are not unique
customer counts. Current window `[now−W, now]`, historical baseline
`[now−(N+1)W, now−W)`; future/older events excluded. Defaults W=3600 seconds, N=6.
`baseline_count` is the entire historical total; expected equivalent-window count is
`baseline_count/N`. Emit when current count ≥5 and ratio ≥3. With zero baseline,
ratio is null; current volume ≥5 emits a medium-severity new-count signal. Severity
is low below 4×, medium from 4×, high from 6×; zero-baseline severity is medium.
Thresholds are transparent, configurable, and deterministic. Sparse/missing historical
coverage is not proof of a genuine population spike. Explanations say abnormal
increase, never confirmed attack, campaign, fraud or intent. ID/detection/window depend
on evaluation time; repeated production polls advance the rolling clock. Fixed-clock
service calls are deterministic. Results sort current count descending, metric/key.

## Analytics API contract for the future dashboard

All routes have typed Pydantic responses and require the supervisor header above.
Collection endpoints return arrays directly; there is no hidden cursor/pagination.
Timestamps are timezone-aware ISO strings, nullable metrics are JSON null.

| GET endpoint under `/api/v1/analytics` | Response |
|---|---|
| `/overview` | `AnalyticsOverview` aggregates and storage diagnostics |
| `/sessions` | `ConversationSessionSummary[]`, most recent first, ID tie break |
| `/sessions/{session_id}` | `SessionDetail {summary, timeline: ConversationEvent[], journey: JourneyEvent[]}` |
| `/sessions/{session_id}/journey` | `JourneyEvent[]` in retained append order |
| `/anomalies` | `Anomaly[]` with ID/time/metric/key/current_count/baseline_count/baseline_expected_count/ratio/severity/window/explanation/partial_history |
| `/scenarios` | `{key, count}[]`, unique session counts per selected scenario |
| `/risk` | levels (including unknown), high_risk_sessions, top_signals, high_risk_scenarios |

Overview/sessions/scenarios/risk accept `channel=web|phone`, `scenario` (1–128 chars),
`risk_level=unknown|low|medium|high|critical`, `from`, `to` (timezone-aware), and
`session_id` (1–128 chars). Time ranges select sessions having at least one event
inside the inclusive range; summaries/aggregates use their entire retained history.
They are not clipped partial turns. Session risk filter uses highest observed session
risk. Sessions additionally accept `active=true|false`, `limit=1..500` (default100).
Anomalies accept channel/scenario/risk_level/limit and always use the configured
current rolling clock, not arbitrary from/to windows. Their risk filter uses each
event's own Agent risk; absent-risk scenario events are excluded by a known-risk
filter. A scenario filter applies to scenario count keys and to supplied scenarios
on risk-signal response events. Detail/journey validate ID length and return 404 for
unretained sessions. Invalid query/range/channel returns 422. Use the generated
`/openapi.json` for exact schema fields.

Example operator polling (token remains in a local environment variable):

```bash
curl -H "Authorization: Bearer ${ANALYTICS_API_TOKEN}" \
  'http://localhost:8000/api/v1/analytics/sessions?channel=phone&active=true&limit=20'
curl -H "Authorization: Bearer ${ANALYTICS_API_TOKEN}" \
  'http://localhost:8000/api/v1/analytics/overview?channel=phone'
```

For a recent/history view use `channel=phone&from=<encoded ISO timestamp>` without
`active=true`; ended calls remain queryable. Summaries expose call metadata, status,
last scenario, risk, latest timings, start and latest timestamp. No dashboard WebSocket
was added; poll these endpoints. Web local Stop cannot reliably close a backend session
in this MVP, so active can persist until the five-minute heuristic expires.

## Synthetic demo

`analytics/demo.py` produces 170 clearly marked DEMO events / 38 sessions at a supplied
clock: web multi-stage journey with clarification/handoff and unknown risk, 24 historical
phone sessions with synthetic low risk, 12 synthetic high-risk phone sessions and
handoffs, and one recent active phone session. Six historical windows yield 4 selected
FRAUD_CALL_REPORT events/hour; current window yields12/hour, ratio3. Risk-signal spike
has zero historical baseline and ratio null. IDs, session names, text, and metadata
mark DEMO; phone metadata uses provider `demo` and DEMO call IDs, no customer numbers.
Fixed clock gives identical fixtures. Explicit startup seeding uses current time so
recent polling is useful. Fixture IDs/scenario names do not alter real Agent routing.

## Verification scope

Focused tests in `backend/tests/unit/test_data_intelligence.py` cover bounded/copy-safe
storage and filters, strict channels/timestamps, web backend ownership and spoof
rejection, shared application store for both phone gateways, existing latency exposure,
summaries, ordered/collapsed journeys, risk unknown/high handling, ranked ties,
window boundaries and baseline-zero anomalies, auth/API validation and synthetic demo.
Existing backend/PhoneRuntime/Vonage/Twilio and frontend regressions are required.
Offline mocks are labelled; no new live call was made for this task. Persistence,
financial scenarios/Risk Analyzer, operator transfer, RBAC, dashboard UI, browser
playback ingestion and streaming dashboard updates remain deferred.
