# Scenario Pack architecture — Stage 3

The two production packs are `insurance_manager` (consultative) and
`product_promoter` (proactive). Shared sessions, HTTP, voice, traces and lifecycle remain
independent of their business logic. No database, queue, RAG or dynamic plugin loading
is introduced.

```text
Browser text / final STT → POST /api/message
    → Shared Core: lock, snapshot, registry, activate/resume
    → selected pack: one structured Agent call → deterministic policy/reply
    → only when out-of-domain: public-manifest selector → customer confirmation
    → Shared Core: typed local context/result + global status + trace commit
    → browser TTS → listening / handoff / ended

Product selected at Start → POST /api/conversation/start
    → same Shared Core → Product opener (zero model calls, no customer transcript)
    → branded assistant greeting → TTS → listening
```

## Shared Core and context firewall

`conversation/service.py` owns registry resolution, per-session locking, snapshots,
activation, pending-switch confirmation, terminal rejection and atomic commit. The bounded
locked LRU store retains 100 sessions; in-flight entries are pinned, reads/writes use deep
copies. Traces are bounded to 100 sessions × 100 turns. State is single-process, in-memory
and lost on backend restart. Failures commit no context, switch or trace.

`GlobalConversationContext` contains only session ID, global turn, language, channel and
conversation status. `ConversationContext` additionally holds the active pack, isolated
`scenario_contexts[pack_id]` and optional pending switch. Pending metadata contains the
original request, source/target IDs, reply language and prior status, never private business
state. It is not passed to either pack or to the selector.

Each pack receives only its typed local state and a copied global context. Its latest
typed result stays in its own entry. Shared code validates context/result types before
commit; it never merges slots, history, knowledge, prompts or tools. These are boundaries
between trusted developer-controlled Python components, not an OS sandbox for plugins.

## Contract, registry and lifecycle

`packs/contracts.py` defines the manifest, prompt, knowledge, tools, policies, state/output
schemas, completion rules, new-context factory and `handle_turn`. Product also implements
an optional `open_turn`. Manifests contain public routing descriptions and no configuration
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

## Natural switching

Only a pack's `out_of_domain` result invokes `packs/selector.py`. Normal in-domain turns
call one pack Agent; opening and rejecting a pending switch call no model. Selector input
has exactly current text, current pack ID, public descriptions of registered packs and
global language. No private contexts, results, identity, history or expected labels enter it.

An allowlisted different target with confidence ≥0.75 produces a confirmation, preserving
the original pack's private state. Yes dispatches the original question to the target;
the trace retains the actual confirmation transcript. No preserves the old state. A new
non-confirmation request cancels the proposal and goes through the current pack. Unsupported
loans, fraud, technical support and unrelated requests do not force a pack switch.
Invalid selector output safely leaves the pack active. Provider/timeout failures roll back
the whole turn. The conditional selector shares a 55-second overall deadline below the
frontend's 60-second timeout.

## Insurance Manager

Implementation lives in `packs/insurance_manager/`; former `agent/`, `dialog/`, `data/`,
`scenarios/`, `tools/` and `response/` paths remain compatibility exports. Canonical source
`data/starter_kit/` remains unchanged: 40 insurance flows, three system intents, 43 slots,
31 actions and 104 development examples. No duplicate dataset or expected labels enter
the Router. The Stage 1 prompt, strict SDK schema and fresh input serialization remain
unchanged.

Insurance owns routing, confidence/priority policy, slot/ID validation, local 20-turn history,
client lookup ID, per-flow snapshots, pending/stack, clarification counters and RU/KK replies.
`InsuranceResult` records the actual outcome and collected data before slots clear. Read-only
synthetic lookups and grounded quotes work; actual insurer writes remain disabled.

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

Insurance retains its existing bounded transport. Product and selector use
`packs/structured_agent.py`: no SDK tools/handoffs, max_turns=1, SDK/client retry=0,
45-second per-call timeout, disabled SDK tracing and provider storage. Only narrow routing
settings reach the transport. No environment values enter prompts, manifests or traces.

HTTP errors remain 422 input, 503 configuration/capacity, 502 provider, 504 timeout and
409 terminal session. Invalid structured decisions lead to bounded clarification/handoff,
never an invalid business action. Shared terminal replies preserve exactly
**«Конечно, передаю диалог оператору.»** and localized goodbye.

## HTTP, frontend and voice

`POST /api/message` accepts `{session_id, text, scenario_mode?}`. Responses retain six fields:
session_id, response_text, routing, state, trace, conversation_status. OpenAPI declares
Insurance, Product and minimal platform-confirmation variants. Insurance keeps its flat
legacy state; Product exposes only its own state/result and shown catalog records.

`POST /api/conversation/start` accepts `{session_id, scenario_mode}` and opens Product via
the same locked core. Packs without an opener return 422. It creates an assistant event
`scenario.opened`, with no fabricated customer text and no Router latency.

The runtime keeps one UUID/history across switching. Product selected before Start opens
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
remaining model-output variability are in `STAGE3_VALIDATION.md`.
