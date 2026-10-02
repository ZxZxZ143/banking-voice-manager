# Scenario Pack architecture — Stage 3.2

The two production packs are `insurance_manager` (consultative) and
`product_promoter` (proactive). Shared sessions, HTTP, voice, traces and lifecycle remain
independent of their business logic. No database, queue, RAG or dynamic plugin loading
is introduced.

```text
Browser text / final STT → POST /api/message
    → Shared Core: lock, snapshot, registry, activate/resume
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
secrets. `core/services.py` explicitly constructs and registers exactly the two packs.

`packs/registry.py` performs dictionary lookup, never semantic routing or dynamic import.
Unknown IDs return 422 before any model call. New sessions default to Insurance; omitted
mode on later requests continues the active pack. Explicit mode switches immediately.

`packs/lifecycle.py` initializes, suspends, resumes and completes entries. Production
switching preserves completed leads and refusals; it does not start selling again after a
refusal. Explicit new deposit/card interest can start a fresh Product consultation.
Insurance SCxx stack/pending lifecycle remains entirely within Insurance Manager.
Handoff/goodbye complete the pack and close the global session. Product interest/refusal
completes the lead while leaving the global conversation active.

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
`data/product_promoter/catalog.json` contains six synthetic Merei Demo Bank products:
three deposits and three debit/payment cards, reference date 2026-10-01.

`models.py` defines strict catalog, decision, preferences, local context and `SalesLeadResult`
schemas. No identity, income, wealth, insurance or vulnerability fields exist. Context owns
category, explicit preferences, shown/compared/selected products, objections, interest,
next action and last discovery question. ISO currencies remain normalized machine values.

`catalog.py` deterministically filters/ranks by currency, amount, term, liquidity,
replenishment, fees, cashback, withdrawals and digital availability. Amount without explicit
currency leads to a currency question. A comparison retains alternatives with different
restrictions. No universally best product or guaranteed return is promised.

`pack.py` asks one useful question, presents actual candidates, handles objections without
changing rates, respects refusal and records only explicit application interest. Opening
names Merei Demo Bank before asking about the customer's goal. `presentation.py` produces
conversational, catalog-based summaries with human currency names, decimal commas, percentages
and amounts such as «50 тысяч тенге». Complete conditions are returned separately in
`product_conditions` for the UI disclosure; the frontend calculates no banking terms.

`SalesLeadResult` includes outcome, category, selected ID, explicit preferences, presented/
compared products, objections, interest and next action. Link/callback/application requests
are recorded only; no product opens, link sends or callback schedules.

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

`POST /api/message` accepts `{session_id, text, scenario_mode?}`. Responses retain six fields:
session_id, response_text, routing, state, trace, conversation_status. OpenAPI declares
Insurance, Product and legacy platform variants; production emits no switch-confirmation turn. Insurance keeps its flat
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

Docker retains two health-checked services and loopback ports 8000/5173, Nginx HTTP/WS
proxy, non-root backend and runtime-only `.env`. Both catalog paths are explicit in Compose.
No authentication, persistence or contact-center connection is implemented. Installed
voices and real microphone quality require manual verification. Measured results and
remaining model-output variability are in `STAGE3_1_CONVERSATION_VALIDATION.md` and the
earlier `STAGE3_VALIDATION.md`.
