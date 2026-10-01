# Scenario Pack architecture — Stage 2

`insurance_manager` is the only production Scenario Pack. Stage 2 separates reusable
conversation infrastructure from the existing insurance application. It adds no second
LLM, production business scenario, database, queue, RAG or dynamic plugin loading.

```text
Browser text / final STT → POST /api/message
    → Shared Core: session lock, snapshot, registry resolution, pack activation
    → InsuranceManagerPack: one Router → insurance policy/state → grounded replies
    → Shared Core: global status, isolated context/result, state+trace commit
    → existing browser runtime → TTS → listening / handoff / ended
```

## Shared Core

`conversation/service.py` owns per-session orchestration, registry/lifecycle resolution,
terminal-session rejection, snapshot boundaries and successful state/trace commit.
`conversation/store.py` retains the original bounded locked LRU algorithm: 100 sessions,
in-flight sessions pinned against eviction, deep copies on reads and writes. Provider or
pack failure commits no history, switch, context or trace. Trace collection remains bounded
to 100 sessions × 100 turns. State is single-process, in-memory and lost on restart.

`GlobalConversationContext` contains only session ID, global turn number, language,
channel and conversation status. The existing HTTP transport defaults channel to `text`,
including requests carrying a final transcript; no voice-layer pack selection is required.
There are no global insurance identifiers, slots, history or business results.

`ConversationContext` contains this global context, `active_scenario_pack`, and isolated
`scenario_contexts[pack_id]` entries. Each entry owns a typed local state, lifecycle and
latest structured result. It is not returned as a cross-pack frontend payload.

## ScenarioPack and manifest

`packs/contracts.py` defines the trusted in-process ScenarioPack protocol: manifest,
prompt, knowledge, tools, policies, state schema, output schema, completion rules,
new-context factory and `handle_turn`. A turn receives only the selected local context
and a copied global context. It returns local state, application result, reply and trace;
it receives no store, registry, other contexts or full application Settings.

The immutable Python manifest is intentionally simple:

```text
id: insurance_manager
name: Insurance Manager
interaction_mode: consultative
supported_languages: ru, kk, mixed
output_schema: InsuranceResult
```

`InteractionMode` defines `reactive`, `consultative` and `proactive` metadata. No proactive
execution or additional production pack is implemented. `core/services.py` is the explicit
composition root: it constructs Insurance Manager and registers it. Only router transport
receives the key/model/temperature/token/timeout settings; manifests contain no secrets.

## ScenarioRegistry and lifecycle

`packs/registry.py` implements register/get/exists/list and resolves the configured default.
Duplicate registration and unknown IDs fail clearly. An HTTP pack ID is a dictionary lookup,
never a module path or code import. Registry resolution performs no semantic routing and
adds no LLM call.

`packs/lifecycle.py` supports new activation, suspension on switching, resumption of an
existing local context, and completion. Lifecycle values are inactive/active/suspended/
resumed/completed. Completed contexts activate as fresh local state; suspended contexts
resume with their own state. Unknown or mismatched contexts are rejected before switching.
Production requests select only Insurance Manager. A second lightweight pack exists only
as a private test fixture to verify this foundation, not in startup registration.

Pack completion is distinct from completion of an insurance SCxx flow. A completed quote
or information reply can resume pending insurance work and leaves the pack active. Handoff
or goodbye sets the global terminal status and completes the pack context. Existing SCxx
stack, pending requests and per-flow slot snapshots are preserved inside Insurance Manager.

## Insurance Manager Pack

All implementation paths below are relative to `backend/app/packs/insurance_manager/`.

| Module | Owned behavior |
|---|---|
| `pack.py` | Manifest, pack construction/capabilities, typed InsuranceResult, turn boundary |
| `state.py`, `history.py` | InsuranceScenarioContext, bounded local history and flat legacy projection |
| `processor.py` | Existing reply-language guard, invalid-output clarification, insurance transitions and completion |
| `agent/` | Insurance prompt, SDK transport schema, Router, source slot/ID validation |
| `data/` | Canonical JSON adapters, cross-file validation and read-only repositories |
| `scenarios/` | Catalog, priority/confidence policy and non-executing requirements inspection |
| `tools/` | Action definitions, disabled irreversible writes, bounded owned-record/knowledge lookups |
| `response/` | RU/KK system/slot replies, grounded insurance quotes/lookups and assisted workflows |
| `wire.py` | Existing typed HTTP response schema |

The canonical source remains `data/starter_kit/`, dated 2026-10-01: 40 insurance flows,
three system intents, 43 slots, 31 actions and 104 development examples. No JSON dataset
copy was created. Business records are synthetic. Dataset labels never enter Router input.

The Router remains one Agents SDK Agent/Runner call with no SDK tools/handoffs,
max_turns=1, no automatic retry, 45-second deadline, disabled SDK tracing and provider
storage. It owns language/decomposition, SCxx selections, confidence, alternatives,
slot extraction and continuation. Insurance policy/state/replies stay deterministic.
The Stage 1 prompt, strict SDK output schema and fresh input serialization are unchanged.

InsuranceScenarioContext owns response language, client lookup ID, active SCxx flow,
slots, flow snapshots, pending/stack, clarification counters/options, confirmation flag and
20-turn local history. `InsuranceResult` records actual selected/completed flow, status,
collected data before completion clears slots, referenced actions/sources, completed and
handoff flags. It describes the real application outcome, never successful insurer writes.
The latest result remains inside the selected pack entry.

## Context firewall

Shared code never merges pack-local slots, histories, results, prompts, knowledge or tools.
The selected pack receives exactly its registered context type; context/result types are
checked before commit. A switch suspends the old entry and initializes or resumes the
selected entry without copying business data. Global snapshot mutations cannot alter
stored session identity/status. Insurance's identity sharing between its own SCxx flows
remains an explicit insurance policy and does not cross the pack boundary.

Tests exercise two private contexts, switch/resume, selective Router input, structured
result isolation, snapshot mutation and failed-switch rollback. These are application
boundaries between trusted Python components, not an OS sandbox for untrusted plugins.
Only developer-controlled packs can be registered.

## Compatibility and transport

`POST /api/message` still accepts `{session_id, text}`. Optional
`scenario_mode="insurance_manager"` resolves the same pack; unknown IDs return 422
`unknown_scenario_pack` before a Router call. Responses retain the six top-level fields:
session_id, response_text, routing, state, trace, conversation_status. `wire.py` preserves
the concrete insurance response types in OpenAPI. Global and local state are projected to
the previous flat DialogState for API/Router compatibility, without persisting a second copy.

`agent/`, `dialog/`, `data/`, `scenarios/`, `tools/` and `response/` at the old app paths
are compatibility exports/adapters. Existing tests and callers remain valid; insurance
implementation lives inside its pack. The old Router import remains a module alias so
existing SDK transport injection points continue to work.

Trace adds scenario_pack_id, interaction_mode and context_lifecycle. The shared core
sets authoritative session/turn/status fields. Insurance trace still exposes short reasons,
selected flows, alternatives, source/action names and timings; it exposes no prompts,
secret config or hidden chain-of-thought. The supervisor UI reads both new and old traces.

HTTP error contracts remain 422 input, 503 configuration/capacity, 502 provider, 504 timeout
and 409 terminal session. Invalid structured routing remains safe SYS_UNCLEAR clarification,
then bounded handoff; it never executes an invalid business action. Explicit operator reply
remains exactly **«Конечно, передаю диалог оператору.»**; Kazakh replies and goodbye remain.

Streaming voice and ConversationRuntime are unchanged: PCM16/24 kHz → local Silero/OpenAI
STT → final-only same-session request → pack reply → browser TTS. Normal playback resumes
listening; handoff/ended keep it stopped. Docker retains two health-checked services and
loopback ports, with Nginx HTTP/WebSocket proxy and runtime-only `.env`.

## Actual boundaries

No actual insurer writes, policy issuance, SMS/email delivery, operator queue, authentication
or persistence is implemented. Synthetic identifier lookup is not authentication. The local
stand must remain private. Browser speech depends on installed voices; physical microphone
capture and Kazakh audio quality require manual verification. See `STAGE2_VALIDATION.md`
for measured regression results and model-output variability.
