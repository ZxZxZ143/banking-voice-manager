# Voice Router architecture

This repository is a runnable technical foundation for the Saqta Insurance contact-center simulation. It does not yet process a complete conversation. The business source is the canonical `data/starter_kit/` directory: 40 scenarios, 3 system intents, 43 slots, 31 action definitions, 10 sample dialogs, and 104 development utterances. All supplied business records are synthetic; relative business dates must use the dataset snapshot, **2026-10-01**.

## Intended flow

```text
Browser / microphone → STT → triage → one Router Agent ↔ dialog state
                                        ↓
                                  decision policy
                                        ↓
                                  scenario engine
                                        ↓
                                      tools
                                  ↙           ↘
                           knowledge      mock backend
                                  ↘           ↙
                                response generator → TTS → browser / speaker

All stages → trace collector → supervisor panel
```

Text input will enter at triage and remain available for development. The LLM selects scenarios; deterministic code owns constraints and execution. The compact catalog contains every scenario with description, exclusions (`not_this_if`), priority, and one example per language, plus all system intents. There is no retrieval index, intent classifier, database, or multi-agent orchestration.

## Module boundaries and present behavior

All backend paths below are relative to `backend/app/`.

| Boundary | Source | Implemented now / remaining work |
|---|---|---|
| Application composition | `main.py`, `core/services.py`, `core/config.py` | FastAPI lifespan loads and validates the seven JSON datasets once, then constructs shared services. Invalid or missing data prevents startup. Importing the app does not call OpenAI. |
| API transport | `api/routes/`, `api/websocket/` | Working health and streaming voice endpoints; text endpoint unavailable; no turn orchestration. |
| Speech input | `speech/stt/` | Typed recorded-audio interface and actual OpenAI transcription adapter with bounded timeout/retry. Not connected to API or microphone; no live-provider verification. |
| Triage | `triage/` | Trims whitespace, retains optional supplied language hint, measures elapsed time. Language detection, spoken-number/phone/IIN/plate/date normalization, urgency, and decomposition remain unimplemented. |
| Semantic routing | `agent/` | Prompt builders, `Router` protocol, output contracts, and a factory constructing one Agents SDK `Agent` with no tools/handoffs. `RouterAgent.route()` raises `NotImplementedError`; Runner execution is future work. |
| Conversation state | `dialog/` | Typed state, explicit copied history updates, bounded in-memory store. Orchestration must save updates and serialize concurrent turns per session. |
| Routing policy | `scenarios/decision_policy.py` | Pure provisional accept/clarify/handoff/continue policy; rejects unknown IDs, orders urgent scenarios first, preserves the others' spoken order. Does not execute or transfer. |
| Scenario requirements | `scenarios/catalog.py`, `scenarios/engine.py` | Catalog lookup and generic read-only identification/missing-slot inspection. `ScenarioEngine.execute()` raises `NotImplementedError`; workflows and confirmation execution remain unimplemented. |
| Business tools | `tools/` | Registry loads the authoritative action definitions, provides consistent results/errors, and supports future independent handlers. No handlers are registered. Irreversible registration and execution are always blocked. |
| Knowledge/backend access | `data/models.py`, `data/loaders.py`, `data/repositories.py` | Typed wrappers, uniqueness and cross-file reference checks; read-only deep-copy repositories. Knowledge lookup uses exact dotted keys, not semantic search. No prices, statuses, or mutations are invented. |
| Response generation | `response/generator.py` | Input/output contracts and protocol; configured foundation implementation raises `NotImplementedError`. Future generation is grounded in the selected scenario and data and cannot change routing. |
| Speech output | `speech/tts/` | Typed interface and actual OpenAI adapter that buffers an MP3 stream, measuring its first nonempty chunk. Not wired to API/speaker and not live-tested. |
| Supervisor traces | `tracing/` | Typed application-level trace and bounded copy-on-read/write collector. No public trace endpoint or active-turn integration yet. |
| Evaluation | `evaluation/` | Offline data validation and injectable router-to-predictions adapter. No model accuracy measurement until a router implementation is supplied. |
| Browser shell | `frontend/src/` | React/TypeScript/Vite UI checks real health and submits text to display the real 501 error. Conversation and trace areas are empty; microphone is disabled. No recorded audio or fabricated conversation. |

Speech adapters require explicit model settings (and a voice for TTS) when constructed. Missing credentials fail clearly; OpenAI SDK exceptions and timeouts become actionable speech errors. Other stream transport errors propagate to the future orchestration boundary. Transcription language and duration remain `null` when the provider does not supply them. TTS language records the requested language, not a verified audio-quality result. Provider tests use isolated test doubles; these are not a runtime fallback.

## Current API

| Endpoint | Input | Current result |
|---|---|---|
| `GET /health` | None | HTTP 200 after successful startup; actual loaded counts and `mode: "foundation"`. This does not probe OpenAI readiness. |
| `POST /api/v1/turns/text` | JSON `{ "session_id": "<UUID>", "text": "<nonblank text>" }`; text up to 10,000 characters | Valid requests return HTTP 501 with `error.code: "not_implemented"`; no routing, state mutation, or action. Invalid requests return FastAPI validation errors (422). |
| `WS /api/v1/voice` | WebSocket connection | PCM24 browser streaming to OpenAI with Silero automatic endpointing, partial/final transcripts and timings. See `VOICE_STREAMING_CONTRACT.md`; no routing/TTS orchestration. |

The health payload with the supplied files is:

```json
{
  "status": "ok",
  "service": "voice-router",
  "mode": "foundation",
  "starter_kit": {
    "scenarios": 40,
    "system_intents": 3,
    "actions": 31,
    "dev_utterances": 104
  }
}
```

Application errors use `{ "error": { "code": "...", "message": "..." } }`. Tool internals use `ToolResult(success, data, error)` with mutually exclusive success/error states; `to_payload()` returns the starter-kit error format or successful data. Foundation tool codes include `unknown_action`, `not_implemented`, and `irreversible_action_disabled`; business error codes remain defined by `actions.json`.

## Shared contracts and state ownership

| Contract | Source | Meaning |
|---|---|---|
| `RouterDecision` | `agent/schemas.py` | Language (`ru`, `kk`, `mixed`), semantic segments, unique selected scenarios, alternatives, slot object, continuation flag. Scores are finite values from 0 to 1. Reasons are brief supervisor-facing explanations. |
| `SemanticSegment` | `agent/schemas.py` | Text, scenario ID, confidence, reason, optional `depends_on`. Dependencies are **zero-based indices of earlier segments**; every segment references a selected scenario. |
| `RouterAgentOutput` | `agent/schemas.py` | Closed SDK transport schema represents slots as a list of `{name, value}` entries. `to_decision()` rejects duplicate slot names and restores the domain dictionary. This avoids an unrestricted object in strict structured output. |
| `DialogState` | `dialog/models.py` | Session/language/client, active scenario, stack, pending scenarios, slots, confirmation-pending flag, turn counter, consecutive low-confidence count, and up to 20 history entries. |
| `ExecutionRequirements` | `scenarios/engine.py` | Scenario identification requirement, first missing required slot, allowed action names, and confirmation requirement. This is inspection, not an authorization or execution result. |
| `ResponseInput` / `GeneratedResponse` | `response/generator.py` | Selected scenario, language, state, slots, tool results and knowledge → text and language. |
| `TraceRecord` | `tracing/models.py` | Turn, transcript, language, scenarios, alternatives, concise reason, slots, actions, and latency fields: STT, triage, router, tools, response, first TTS audio, total. `null` latency means unmeasured, not zero. No hidden chain-of-thought. |

`PolicySettings` is configurable in Python and starts with acceptance **0.75**, low confidence **0.45**, and handoff after **2** consecutive low-confidence turns. Policy is provisional and currently considers the least-confident selected scenario; mixed-confidence multi-intent behavior needs evaluation. The caller persists the returned low-confidence count and performs any actual handoff.

Dialog and trace stores are single-process memory with defensive copies. Defaults retain 100 sessions; history retains 20 turns and traces retain 100 records per session. Old entries are evicted when limits are reached. Restart loses state, separate workers do not share it, and no concurrent per-session turn serialization exists yet.

`awaiting_confirmation` records conversational state only. It is **not permission to execute**. A future confirmation executor must bind explicit approval to the previewed action and validated arguments, invalidate it when those change, and enforce single-use execution. The current registry cannot execute irreversible actions even if callers supply a confirmation flag.

## Parallel ownership

| Workstream | Primary files | Shared boundary to coordinate |
|---|---|---|
| Router v1 / evaluation | `backend/app/agent/`, `backend/app/evaluation/` | `RouterDecision`, catalog format, dialog input, prediction format |
| Dialogue / business execution | `backend/app/dialog/`, `backend/app/scenarios/`, `backend/app/tools/` | Policy results, tool results, explicit confirmation executor, session serialization |
| Speech | `backend/app/speech/`, then `backend/app/api/websocket/` | Audio framing, cancellation, provider lifecycle, language and timing metadata |
| API integration / response | `backend/app/api/routes/`, `backend/app/core/services.py`, `backend/app/response/` | Turn orchestration, response/error payloads, state updates, trace collection |
| Frontend / supervisor | `frontend/src/api/`, `types/`, `components/`, `hooks/` | Published API/voice/trace contracts; synchronize TypeScript and Pydantic changes |
| Source data access | `backend/app/data/`, canonical `data/starter_kit/` | Preserve supplied files; update typed wrappers and repositories only when required |

Agree shared contracts before editing another workstream's boundary. Each module should remain testable without microphone access or live credentials. No persistence service is required for this foundation.

## Evaluation and next slice

From the repository root after installing the backend:

```powershell
.venv\Scripts\python.exe -m app.evaluation --check-data
```

This validates supplied files; it does **not** evaluate routing. `generate_predictions(dataset, router)` accepts the `Router` protocol and passes each utterance's text with a fresh `DialogState(session_id=utterance.id)`. Expected labels and source language labels are not passed to the router. Router failures abort the run rather than producing fabricated predictions. `write_predictions()` creates a new output file exclusively, preserving previous runs.

The prediction format is `{ "U001": ["SC01"], "U085": ["SC27", "SC04"] }`. Once predictions exist, invoke the unchanged supplied evaluator from the repository root:

```powershell
.venv\Scripts\python.exe data/starter_kit/evaluate.py predictions.json data/starter_kit/dev_utterances.json
```

The evaluator measures first-scenario accuracy, set-based full match, and multi-intent recall, with language/type breakdowns. It does not validate scenario execution or conversational history. The recommended next module is **Router v1 + evaluation on all 104 dev utterances**, followed by text-turn orchestration, generic scenario execution, trace integration, and routing integration with the implemented voice test bench.
