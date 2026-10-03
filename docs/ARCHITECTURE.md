# Scenario Pack architecture — Stage 6 integration

Production registers `insurance_manager` and three proactive campaigns: `product_promoter`
(deposit), `card_promoter`, `loan_promoter`, plus consultative `fraud_security`. The sales campaigns reuse one implementation
with distinct manifests and isolated contexts. Shared sessions, HTTP, voice, traces and lifecycle remain
independent of their business logic. Stage 5A adds replaceable SQLite event persistence;
no external task broker, RAG or dynamic plugin loading is introduced.

```text
Browser text / final STT → POST /api/message
    → Shared Core: lock, snapshot, registry, activate/resume
    → mask authentication values → shared Risk candidate precheck
        → ordinary: no Risk model call → selected pack's normal turn
        → candidate: one structured Risk Agent call (bounded, no tools/retries)
        → relevant: source advice, selected business state/result retained
        → Fraud selected manually: reuse the same assessment, safe fact/question policy
    → Insurance: Router → Decision Policy → grounded business facts → LLM Composer
    → Product: structured Agent → deterministic catalog policy/reply
    → out-of-domain: current assistant scope reply, no selector/forwarding
    → Shared Core: typed local context/result + global status + trace commit
    → browser TTS → listening / handoff / ended

Either pack selected at Start → POST /api/conversation/start
    → same Shared Core → pack opener (zero model calls, no customer transcript)
    → branded assistant greeting → TTS → listening
```

## Shared Core and context firewall

`conversation/service.py` owns registry resolution, per-session locking, snapshots,
activation by explicit selection, terminal rejection and atomic commit. The bounded
locked LRU store retains 100 sessions; in-flight entries are pinned, reads/writes use deep
copies. Traces are bounded to 100 sessions × 100 turns. State is single-process, in-memory
and lost on backend restart. Failures commit no context, switch or trace.

`GlobalConversationContext` contains only session ID, global turn, language, channel and
conversation status. `ConversationContext` additionally holds the active pack, isolated
`scenario_contexts[pack_id]`. The old optional pending-switch field remains wire-compatible but production clears it and never proposes a natural switch.

Each pack receives only its typed local state and a copied global context. Its latest
typed result stays in its own entry. Shared code validates context/result types before
commit; it never merges slots, history, knowledge, prompts or tools. These are boundaries
between trusted developer-controlled Python components, not an OS sandbox for plugins.

## Contract, registry and lifecycle

`packs/contracts.py` defines the manifest, prompt, knowledge, tools, policies, state/output
schemas, completion rules, new-context factory and `handle_turn`. Product also implements
an optional `open_turn`; Insurance implements it too. Manifests contain public routing descriptions and no configuration
secrets. `core/services.py` explicitly constructs and registers these five assistants.

`packs/registry.py` performs dictionary lookup, never semantic routing or dynamic import.
Unknown IDs return 422 before any model call. New sessions default to Insurance; omitted
mode on later requests continues the active pack. Explicit mode switches immediately.

`packs/lifecycle.py` initializes, suspends, resumes and completes entries. Production
switching preserves completed leads. A soft first refusal permits one confirmation; a second
refusal closes the sales session. Explicit stop-sales requests close it immediately. A new
sales call needs a new session.
Insurance SCxx stack/pending lifecycle remains entirely within Insurance Manager.
Handoff/goodbye and a final sales refusal close the global session. Product interest
completes the local lead while leaving the global conversation active.

## Explicit manual selection only

`scenario_mode` or the UI selector is the only way to change assistants. Production does
not construct or call `ScenarioSelector`, and never forwards an out-of-domain question.
The old selector class and platform wire models remain compatibility/test artifacts.
Insurance and Product retain isolated suspend/resume contexts across manual changes.
Scope replies use no extra selector model call and cannot select another pack.

## Insurance Manager

Implementation lives in `packs/insurance_manager/`; former `agent/`, `dialog/`, `data/`,
`scenarios/`, `tools/` and `response/` paths remain compatibility exports. Canonical source
`data/starter_kit/` remains unchanged: 40 insurance flows, three system intents, 43 slots,
31 actions and 104 development examples. No duplicate dataset or expected labels enter
the Router. Stage 3.1 extends the Router output with a conversation signal, removes nullable
SDK slot placeholders, and supplies expected-answer context only from Insurance state.
Canonical routing is evaluated independently on the unchanged 104 inputs.

Insurance owns routing, confidence/priority policy, slot/ID validation, local 20-turn history,
client lookup ID, per-flow snapshots, pending/stack, clarification counters and RU/KK replies.
`InsuranceResult` records the actual outcome and collected data before slots clear. Read-only
synthetic lookups and grounded quotes work; actual insurer writes remain disabled.

The customer-facing path has four distinct authorities:

1. **Router** understands outcomes, entities, language and meaningful conversational progress.
2. **Decision Policy** authorizes an existing business path, clarification or terminal state.
3. **Grounded business logic** calculates/looks up facts and identifies the next missing field.
4. **Conversation Composer** phrases acknowledgement and one natural next question.

The SDK extraction schema is generated from the source slot catalog: closed slot names,
JSON types, enum values, identifier patterns and nonempty collections/strings. Invalid
optional entities need not invalidate an otherwise clear request. The business adapter
still independently validates dates, patterns, scenario IDs and ownership. A bare preference
to call «later» supplies callback intent, not a usable requested time; time collection continues.

Composer functionality lives in `packs/insurance_manager/composer.py` and uses the existing
bounded `StructuredAgent`. Its typed output is act, acknowledgement, question, recognized
conversation context and expected answer type. The server tracks expected_slot from the
business layer, so the model cannot choose a different collection target. Composer input
contains the current utterance, eight prior turns, language, local scenario/policy, masked
slots, missing fields, prior question, grounded fact block and allowed action. It receives
no other pack state, credentials, evaluation labels, provider tools or arbitrary backend objects.
The received-this-turn field names distinguish new data from an earlier flow's history.

Grounded localized facts are immutable blocks inserted by the server between acknowledgement
and question. This deliberate constraint preserves exact numbers, dates, statuses, documents,
coverage and limitations; free wording cannot add numerical facts or claim an executed write.
The LLM controls conversational framing rather than reauthoring authoritative insurance facts.
Policy status is a concise localized fact without identifiers or dataset dates. The Composer
may select an offered immutable end-date/period variant for an explicit date question;
the server suppresses follow-up filler for this answer. These dates still use the owned
record and canonical snapshot reference date. A completed scenario is never continued by
a stale model flag: its selected follow-up is treated as a fresh request.
Final dialogue no longer comes directly from scenario classification; deterministic replies
remain the grounded source and safe fallback. Invalid/provider-failed composition keeps
the business state and next step, with an allowlisted composer_error and measured latency.
If typed goal recognition succeeded but its wording was rejected, fallback retains only
new/existing goal metadata, asks a narrower question and resets misunderstanding. Rejected
prose never survives as facts or business authorization.

Conversational metadata tracks act, last question, expected answer type/slot, repair attempts,
phase and existing/new conversational context. Greeting is discovery, not a business scenario.
Valid requested identifiers have a literal numeric/RU/KK digit normalization path in
`expected_answers.py`: it validates the already requested field, never selects an intent.
Policy may continue the active workflow on that validated data even if routing output was
rejected; it never accepts an unknown new business scenario. Actual identifiers stay local.
literal RU/KK travel durations are remembered until an explicit start arrives. Inclusive
end-date arithmetic happens on the server; duration alone cannot supply a guessed start,
and an explicit end-date correction takes priority. This helper does not select an intent.
`privacy.py` masks presentation/history/source references and spoken digit sequences.

Meaningful answers reset misunderstanding. A non-explicit comprehension handoff needs
multiple different repair attempts with no progress; operational handoff follows collection
of required useful data. Explicit SC37 bypasses Composer and preserves the exact friendly
handoff phrase. Urgent catalog guidance retains its existing priority rules.

## Insurance manager behavior and local data

Router `scope_kind` distinguishes social, identity, banking and unrelated enquiries only
within `SYS_OUT_OF_SCOPE`; contradictory structured outputs are rejected. Asking whether
the assistant is human is distinct from requesting a human transfer. Scope replies preserve
the active scenario, collected data and expected field. Short answers resolve against the
previous question/history. Acknowledgement is optional; server guards remove filler and
consecutive reaction prefixes. Terminal facts need no extra reaction or repeated transfer.

Literal phones are masked across Router input/history/slots before provider transport.
Requested phone values are parsed from the original utterance locally, normalized from
domestic `8`, international `7` or a full ten-digit national number to `+7`, and merged only
into an authorized flow. Shorter local suffixes are not guessed. Composer
already receives masked identifiers. Lookup is demo ownership filtering, not authentication.
There are at most two client lookup attempts, including corrected identifiers; an unresolved
client still allows general information, while private operations collect remaining useful
context and hand off. Changing a resolved identity discards stale owned records.

`data/demo_profile.py` generates an optional in-memory overlay from runtime `DEMO_TEST_PHONE`.
The canonical kit remains intact; all other fields are deterministic fictional fixtures.
Docker's existing runtime `.env` mechanism is sufficient. `scripts/show_demo_profile.py`
prints only the created client's linked records and manual test guidance. Never commit its
personal phone output. Tests/evaluations use synthetic inputs with the personal overlay off.

`tools/capabilities.py` derives pending unavailable actions from authoritative scenario/action
definitions and an explicit allowlist of implemented grounded readers/calculators. It also
constructs a typed `ManagerSummary`: reason, scenario, collected field names, known-client
flag, successful read-only checks and next unavailable action. Actual writes/delivery/booking
are unimplemented regardless of the catalog's `irreversible` flag. Future integrations must
update capability/execution and confirmation policy together. Optional SMS on an information
flow does not force handoff when only the information was requested.

The safe summary is included in trace and the pack-local result; it contains no identifier
values and is not read verbatim to the customer. Explicit SC37 skips collection/Composer
and keeps the verified Russian phrase. Handoff is a demo terminal state, not a contact-center
connection. Available grounded checks run before unavailable-operation handoff.

## Product Promoter

`packs/product_promoter/agent.py` interprets intent, language and explicit preferences in one
structured SDK call. It does not write dialogue or invent conditions. The independent
`data/product_promoter/catalog.json` contains eight synthetic Merei Demo Bank products:
three deposits, three debit/payment cards and two loans, reference date 2026-10-01.
It also supplies fictional opening steps; the bot does not invent an existing bank app or
approval decision. A full Loan Consultant remains unimplemented. Stage 4 adds advisory
Fraud/Risk separately, without granting bank operation authority.

`models.py` defines strict catalog, decision, preferences, local context and `SalesLeadResult`
schemas. No identity, income, wealth, insurance or vulnerability fields exist. Context owns
category, explicit preferences, shown/compared/selected products, objections, interest,
next action, assigned campaign, last actual assistant text/question, sales phase and a bounded
refusal counter. The provider receives the previous question, not the whole offered product
text, so advertised features/numbers cannot become customer preferences. ISO currencies
remain normalized machine values. The first customer reply is not
language-biased by the default Russian opener.

`catalog.py` deterministically filters/ranks by currency, amount, term, liquidity,
replenishment, fees, cashback, withdrawals and digital availability. Amount without explicit
currency leads to a currency question. A comparison retains alternatives with different
restrictions. No universally best product or guaranteed return is promised.

`pack.py` starts with a branded offer for the already assigned campaign, presents actual
candidates and handles objections without changing rates. A typed information focus selects
facts, while `accepts_explanation` follows the actual previous explanation/opening offer;
the trace preserves both model intent and effective dialogue act. This is progression from
model interpretation and application context, with no text keyword intent selector.
A `question_topic` selects grounded facts rather than repeating the whole catalog.
Opening instructions and interest to apply are separate speech acts. A first soft refusal
gets one follow-up, a second ends the call; an explicit stop request ends it immediately.
Answers are brief and direct, with no suitability-check preface. Opening guides have two
catalog-owned steps; the next question invites opening/application, not another suitability
survey. `presentation.py` produces catalog-based summaries with human currency names, decimal commas, percentages
and amounts such as «50 тысяч тенге». Complete conditions are returned separately in
`product_conditions` for the UI disclosure; the frontend calculates no banking terms.

`SalesLeadResult` includes outcome, category, selected ID, explicit preferences, presented/
compared products, objections, interest and next action. Link/callback/application requests
are recorded only; no product opens, loan is approved/issued, link sends or callback schedules.
Caller-side scoring/target selection may assign the campaign through the existing start
API. No customer profiling, scoring algorithm or actual outbound phone call is implemented.

## SDK transport and errors

Insurance Router retains its bounded transport. Composer and Product use
`packs/structured_agent.py`: no SDK tools/handoffs, max_turns=1, SDK/client retry=0,
45-second per-call timeout, disabled SDK tracing and provider storage. Only narrow routing
settings reach the transport. No environment values enter prompts, manifests or traces.
`OPENAI_RESPONSE_MODEL` optionally selects the Composer model; otherwise it uses
`OPENAI_ROUTER_MODEL`. A normal Insurance turn makes two model calls; this cost is measured
as router, business, composer and total. Composer shares a 55-second turn deadline and
falls back safely when its remaining budget or provider fails. Opening makes zero calls;
explicit operator makes one Router call. Browser TTS first-audio remains separately measured.

HTTP errors remain 422 input, 503 configuration/capacity, 502 provider, 504 timeout and
409 terminal session. Invalid structured decisions lead to bounded clarification/handoff,
never an invalid business action. Shared terminal replies preserve exactly
**«Конечно, передаю диалог оператору.»** and localized goodbye.

## HTTP, frontend and voice

`POST /api/message` accepts `{session_id, text, scenario_mode?, channel?}`. Responses retain six base fields:
session_id, response_text, routing, state, trace, conversation_status. OpenAPI declares
Insurance, Product, Fraud, security-guidance and legacy platform variants; production emits no switch-confirmation turn. Optional `risk` is additive. Insurance keeps its flat
legacy state; Product exposes only its own state/result and shown catalog records.

`POST /api/conversation/start` accepts `{session_id, scenario_mode}` and opens either pack via
the same locked core. Packs without an opener return 422. It creates an assistant event
`scenario.opened`, with no fabricated customer text and no Router latency.

The runtime keeps one UUID/history across switching. Either pack selected before Start opens
automatically; selecting Product during listening also opens/resumes it immediately.
Insurance selection applies to the next customer request. The authoritative active pack
comes from the backend trace. Selection is locked during processing/playback. Reset creates
a new UUID. A Product lead panel and supplied trace metadata render defensively.

Voice remains pack-agnostic: PCM16/24 kHz → local Silero/OpenAI STT → final-only HTTP turn
→ pack reply → browser TTS. Capture stops during processing/playback and resumes after
normal speech. Handoff/ended keep it stopped, including playback failure. Opening plays
before microphone capture starts. Partials never enter conversation history.

## Shared Risk Intelligence and Fraud & Security

`app/risk/` belongs to shared infrastructure. `RiskInput` allows only masked current text,
language, text/voice channel, active assistant ID and `RiskContext`: previous stable signals,
pending safe question, response language. It receives no full pack state, identity, catalog,
history, prompts, tools or application Settings. Authentication values and card numbers are
masked before any pack model/history; Risk additionally masks phones/IIN, email and URLs.
Bare short numbers in a pending exposure answer are also masked. This is conservative
presentation redaction, not a universal DLP guarantee.

The regex precheck only identifies candidates and precautionary policy keys. It never
assigns risk levels or signals. `RiskAgent` reuses `StructuredAgent` with `max_turns=1`,
no tools/handoffs, `store=False`, disabled SDK tracing and no transport/model retries.
Default deadline is eight seconds and output is capped at 1000 tokens. Failures produce
`analysis_status=unavailable|invalid_output`, unknown relevance and no fabricated signals.
Clear precheck hints still render advice; other optional failures remain visible in risk
metadata while normal business processing continues.

`RiskAssessment` uses stable signal enums, advisory none/low/medium/high/critical levels,
allowlisted recommendations and application-generated reasons. Levels are neither fraud
probabilities, customer trust/credit scores nor legal findings. The synthetic policy in
`data/security/policy.json` owns all guidance and safe questions. No URL fetch, account
block/freeze, transaction rejection or real security investigation occurs.

Each entry keeps its last pack-produced public projection separately from private state.
A security detour uses that safe projection and a fresh trace, preserving the selected
business context and typed result; no business Router/Composer/Product call is made on
that turn. The lifecycle remains active/resumed/completed as before. Only explicit
operator/farewell may terminate it. A normal continuation then uses the retained state.

The manually selected `packs/fraud_security/` consumes the same assessment once, asks at
most one safe follow-up, tracks enum facts and asked questions, and produces
`FraudCaseResult`. Exposed credentials, installed remote access, completed coerced
transfers, lost card/account access concerns or a specified unknown transaction need
human review. Global handoff means prepared demo transfer, not a real contact-center
connection. `case_status` distinguishes open/informed/needs_review. Previous case facts
remain in its own context; neither a Risk signal nor speech selects this pack.

The common frontend renders allowlisted Risk metadata and FraudCaseResult, masks secret
values in user history/requests/voice diagnostics and diagnostic JSON exports, and retains the existing final-only
voice/TTS lifecycle. Guard replies use routing response_language because business state
language is deliberately preserved. Ordinary replies keep existing language precedence.

`POST /api/security/precaution` is a zero-model, session-free source lookup. The frontend
candidate gate calls it concurrently with the single authoritative message request and
speaks the short source sentence before awaiting model completion. Capture remains stopped.
The canonical assistant response enters history once; already-spoken source text is removed
only from remaining TTS audio. A failed optional cue leaves the authoritative response intact.
It assigns no risk level or signals and cannot select assistants. Ordinary turns make no
cue request. Browser `safetyFirstAudioMs` measures turn-to-warning audio onset; it is separate
from backend analysis time and never derived from generated token count.

Docker retains two health-checked services and loopback ports 8000/5173, Nginx HTTP/WS
proxy, non-root backend and runtime-only `.env`. Both catalog paths are explicit in Compose.
Web/demo APIs have no production authentication or contact-center connection. Stage 6
phone callbacks separately require provider signatures. Installed
voices and real microphone quality require manual verification. Measured results and
remaining model-output variability are in `STAGE3_1_CONVERSATION_VALIDATION.md` and the
earlier `STAGE3_VALIDATION.md`.

## Stage 5A persistent event backend

The shared MessageService emits allowlisted ConversationEvents only after successful
state/result/trace commit. EventRecorder maps InsuranceResult, SalesLeadResult,
FraudCaseResult and relevant/failed RiskAssessment deterministically, without model
calls. A security detour retaining a business result emits no duplicate result snapshot;
explicit terminal guidance persists its updated result status.
It uses EventStore, implemented by SQLiteEventStore: schema-v1 events table, indexed
time/session/assistant/type/risk fields, unique idempotency key, and atomic turn batches.
Session order uses turn number plus sequence. Whole results, collected identifiers,
preferences, transcripts, replies and free-text risk reasons never enter storage.

Each DB operation owns and closes its connection. WAL permits concurrent readers;
lock waits are bounded to 100 ms. Post-commit writes run in a worker thread so SQLite
does not block the async customer/voice event loop. Persistence errors leave successful
customer replies intact, log fixed error codes and appear in additive /health analytics
diagnostics. There is no durable outbox; write failures can leave analytics gaps.

`EVENT_DB_PATH` configures the local DB; Compose mounts a non-root-owned analytics_data
named volume at /app/data/runtime. Only safe events persist; bounded conversation state
and traces remain process-local. SQLite schema user_version=1 rejects unknown versions;
future schema evolution needs explicit migration, not an ORM dependency now.

Typed read-only event/session/summary endpoints use indexed filters and bounded pages.
Summary deduplicates evolving results by session/assistant within the filtered period.
Historical queries now support the deterministic Stage 5B anomaly analysis below.
Stage 5A introduced storage; Stage 5B integrated the teammate dashboard/frontend.
See `ANALYTICS_API_CONTRACT.md` for schemas, count semantics, seeding and Stage 5B checklist.


## Stage 5B persistent dashboard

The teammate Finance Dashboard's React shell/components/styles are selectively integrated,
without its historical phone backend, process-local store, runtime or token proxy. Current
conversation/runtime/assistant/voice code remains. App owns one lasting ConversationRuntime
and BrowserTtsService; dashboard navigation hides the mounted demo and stops capture on exit.
Scoped conversation CSS prevents collisions with Tailwind/shadcn dashboard styles.

The existing loopback Vite/Nginx `/api` proxy serves one `/api/analytics` namespace. Additive
`api/routes/dashboard.py` invokes AnalyticsService, which reads validated safe event snapshots
through EventStore. SQLiteEventStore owns SQL/connections; no route queries SQLite directly.
No stored transcript, free-text explanation, provider ID or customer data is recreated.
Nullable excluded metrics stay unavailable. The old event/session/summary APIs are unchanged;
the richer detail route has `/detail` to preserve the original session response.

Session summaries/overview/risk operate on complete retained source/session histories with
filters applied after grouping. Latest results are snapshots per assistant/type. Journey
stages come from meaningful event enums in original turn/sequence order. Anomalies query
indexed time history and compare a rolling window to N previous equal windows per source,
with minimum volume, positive baseline and earliest-history coverage. They report observed
increases for review, not confirmed incidents; no LLM is involved. Cold starts are explicit.

The frontend client validates required contract fields and source/risk/channel identity,
uses backend totals and page metadata, and retains labelled stale data on read errors.
Polling cancels obsolete requests, avoids overlap and pauses while hidden. Aggregates
materialize safe retained events in application memory at demo scale; large-volume storage
queries/capacity work require future measurement. Persistence retains its best-effort gap
limitation. See `FINANCE_DASHBOARD.md` and `STAGE5B_DASHBOARD_INTEGRATION_VALIDATION.md`.

## Stage 6 phone transport

The teammate implementation from `feature/backend-phone-runtime` →
`feature/twilio-telephony-provider` → `feature/vonage-telephony-provider` is selectively
ported; historical core/events/frontend code is not merged. `main.py` builds an optional
gateway for each enabled/configured provider, sharing the current Services.messages object.
Both use the same PhoneRuntime implementation and shared speech modules; each gateway owns
its bounded transport registry and playback acknowledgements.

```text
signed Twilio/Vonage admission → provider decoder/resampler → PCM16LE mono 24k
    → shared streaming STT → final-only PhoneRuntime → AgentBridge
    → current MessageService.process(session UUID, text, channel="voice")
    → existing selected pack + shared Risk + EventRecorder → SQLite
    → backend OpenAI TTS → provider codec → playback acknowledgement → listen/close
```

Browser `/api/v1/voice` uses the extracted STT relay with unchanged wire semantics; browser
TTS remains frontend-owned. Phone starts listening and defaults to Insurance; it does not
add a second Router, auto-selector, campaign or greeting model. Phone response-language
precedence matches browser security guidance while preserving business state.

MessageService.end_session closes a committed transport conversation under its existing
session lock without adding a turn or invoking models. EventRecorder.record_end writes an
idempotent safe terminal event, preserving handoff. An unanswered call with no committed
turn creates no analytics conversation. Transcripts, raw audio and provider IDs stay outside
SQLite. Best-effort storage/cancellation limitations still apply; runtime state/tombstones
are process-local. See `PHONE_RUNTIME.md` for bounds and authentication, and
`STAGE6_TELEPHONY_INTEGRATION_VALIDATION.md` for measured offline evidence.
