# Voice Router architecture

This repository provides text routing with in-memory conversations for the Saqta Insurance contact-center simulation; business execution and voice remain incomplete. The business source is the canonical `data/starter_kit/` directory: 40 scenarios, 3 system intents, 43 slots, 31 action definitions, 10 sample dialogs, and 104 development utterances. All supplied business records are synthetic; relative business dates must use the dataset snapshot, **2026-10-01**.

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

Implemented text path: `/api/message` → validation/session lock → one Router call with context → policy/state → local slot/system reply → state and trace. The LLM selects scenarios; deterministic code owns transitions. The compact catalog contains every scenario with description, exclusions (`not_this_if`), priority, up to two examples per language, required/optional slots and reference date, plus all system intents. There is no retrieval index, intent classifier, database, or multi-agent orchestration.

## Module boundaries and present behavior

All backend paths below are relative to `backend/app/`.

| Boundary | Source | Implemented now / remaining work |
|---|---|---|
| Application composition | `main.py`, `core/services.py`, `core/config.py` | FastAPI lifespan loads and validates the seven JSON datasets once, then constructs shared services. Invalid or missing data prevents startup. Importing the app does not call OpenAI. |
| API transport | `api/routes/`, `api/websocket/` | Working health and `/api/message`; legacy text/voice endpoints remain explicitly unavailable. |
| Speech input | `speech/stt/` | Typed recorded-audio interface and actual OpenAI transcription adapter with bounded timeout/retry. Not connected to API or microphone; no live-provider verification. |
| Triage | `triage/` | Foundation helper trims whitespace. New API validates/trims directly; language, normalization and decomposition share the single routing call. |
| Semantic routing | `agent/` | One Agents SDK Agent/Runner call, strict output, no tools/handoffs, max_turns=1, zero SDK/client retries, 45-second timeout. Validates IDs, alternatives, continuation, segments and slot types/patterns/enums. SDK tracing and response storage disabled. |
| Conversation state | `dialog/` | Message orchestration, copied bounded history, locked LRU state, active/pending/stack transitions and atomic successful-turn commits. |
| Routing policy | `scenarios/decision_policy.py` | Pure provisional accept/clarify/handoff/continue policy; rejects unknown IDs, orders urgent scenarios first, preserves the others' spoken order. Does not execute or transfer. |
| Scenario requirements | `scenarios/catalog.py`, `scenarios/engine.py` | Catalog lookup and generic read-only identification/missing-slot inspection. `ScenarioEngine.execute()` raises `NotImplementedError`; workflows and confirmation execution remain unimplemented. |
| Business tools | `tools/` | Registry loads the authoritative action definitions, provides consistent results/errors, and supports future independent handlers. No handlers are registered. Irreversible registration and execution are always blocked. |
| Knowledge/backend access | `data/models.py`, `data/loaders.py`, `data/repositories.py` | Typed wrappers, uniqueness and cross-file reference checks; read-only deep-copy repositories. Knowledge lookup uses exact dotted keys, not semantic search. No prices, statuses, or mutations are invented. |
| Response generation | `response/routing.py`, `response/generator.py` | Deterministic slot prompts/system replies in RU/KK, no second model call. Full grounded business-response contract remains a scaffold. No action success or actual transfer is claimed. |
| Speech output | `speech/tts/` | Typed interface and actual OpenAI adapter that buffers an MP3 stream, measuring its first nonempty chunk. Not wired to API/speaker and not live-tested. |
| Supervisor traces | `tracing/` | Typed application trace, bounded collector and current-turn trace returned by `/api/message`; no supervisor feed/public trace endpoint yet. |
| Evaluation | `evaluation/` | Offline data check and live-run CLI, predictions plus official evaluator report. Live accuracy remains unmeasured without key/model. |
| Browser shell | `frontend/src/` | React/TypeScript/Vite UI checks real health and submits text to display the real 501 error. Conversation and trace areas are empty; microphone is disabled. No recorded audio or fabricated conversation. |

Speech adapters require explicit model settings (and a voice for TTS) when constructed. Missing credentials fail clearly; OpenAI SDK exceptions and timeouts become actionable speech errors. Other stream transport errors propagate to the future orchestration boundary. Transcription language and duration remain `null` when the provider does not supply them. TTS language records the requested language, not a verified audio-quality result. Provider tests use isolated test doubles; these are not a runtime fallback.

## Current API

| Endpoint | Input | Current result |
|---|---|---|
| `GET /health` | None | HTTP 200 after successful startup; actual loaded counts and `mode: "foundation"`. This does not probe OpenAI readiness. |
| `POST /api/message` | JSON `{ "session_id": "abc123", "text": "<nonblank text>" }`; ID 1–128, text 1–10,000 characters | Returns session_id, response_text, routing, state, trace, conversation_status. 422 invalid input, 503 unconfigured/busy, 502 provider/output error, 504 timeout, 409 terminal session. Failed turns do not advance state. |
| `POST /api/v1/turns/text` | JSON `{ "session_id": "<UUID>", "text": "<nonblank text>" }`; text up to 10,000 characters | Valid requests return HTTP 501 with `error.code: "not_implemented"`; no routing, state mutation, or action. Invalid requests return FastAPI validation errors (422). |
| `WS /api/v1/voice` | WebSocket connection | Accepts, sends an error object with `code: "not_implemented"`, then closes with code **1013** and reason `Voice transport not implemented`. No audio exchange. |

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
| `RouterDecision` | `agent/schemas.py` | Language (`ru`, `kk`, `mixed`), response_language (`ru`/`kk`), semantic segments, unique scenarios, up to two alternatives, slot object, continuation flag. Scores are finite values from 0 to 1. Reasons are brief supervisor explanations. |
| `SemanticSegment` | `agent/schemas.py` | Text, scenario ID, confidence, reason, optional `depends_on`. Dependencies are **zero-based indices of earlier segments**; every segment references a selected scenario. |
| `RouterAgentOutput` | `agent/schemas.py` | Closed SDK transport schema represents slots as a list of `{name, value}` entries. `to_decision()` rejects duplicate slot names and restores the domain dictionary. This avoids an unrestricted object in strict structured output. |
| `DialogueState` (`DialogState` alias) | `dialog/models.py` | Session/language/response-language/client, active scenario, stack, pending scenarios, slots, confirmation flag, turn counter, unclear/low-confidence counts, conversation status and up to 20 history entries. |
| `ExecutionRequirements` | `scenarios/engine.py` | Scenario identification requirement, first missing required slot, allowed action names, and confirmation requirement. This is inspection, not an authorization or execution result. |
| `ResponseInput` / `GeneratedResponse` | `response/generator.py` | Selected scenario, language, state, slots, tool results and knowledge → text and language. |
| `TraceRecord` | `tracing/models.py` | Session/turn, transcript, language, scenarios, alternatives, reason, slots, empty actions, clarification/handoff, active/pending/status, router/policy/response/total latencies. Other stages remain null. No hidden chain-of-thought. |

`PolicySettings` starts with acceptance **0.75**, low confidence **0.45**, handoff after **2** consecutive low-confidence turns or **3** unresolved clarifications. Ordinary multi-intent acceptance uses the least-confident selected scenario. A confident SC37 request independently triggers handoff, even with an uncertain secondary intent. Actual operator transfer is unavailable and is not claimed.

Dialog and trace stores are single-process memory with defensive copies. Defaults retain 100 sessions; history retains 20 entries and traces retain 100 records per session. Same-session turns are serialized; different sessions run concurrently. In-flight sessions are pinned against LRU eviction and the lock pool is bounded. Restart loses state; use one worker. Session IDs are not authentication: keep this demo local until access control exists.

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

Live evaluation (key/model required):

```powershell
.venv\Scripts\python.exe -X utf8 -m app.evaluation --run --output predictions-v1.json
```

Defaults to all 104 utterances; `--limit N` explicitly selects a subset. Saves new predictions plus `predictions-v1.report.txt` using unchanged `evaluate.py`. The evaluator measures first-scenario accuracy, set-based full match, and multi-intent recall, with language/type breakdowns and first errors. It does not validate execution or dialogue history. Missing credentials prevented the initial live baseline; offline API/SDK transport checks are not model-quality metrics. Next: measure the live baseline, then business workflows, frontend integration and voice as separate milestones.
