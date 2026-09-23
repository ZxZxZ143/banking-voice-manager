# Project Map

## Purpose and requirements

HackAlem Voice Router for fictional Saqta Insurance. Prioritize LLM-based scenario
selection in Russian, Kazakh and mixed-language dialogue, context, ambiguity, topic
changes, clarification and handoff. Final MVP requires voice; text remains available.
No encoder intent classifier or hardcoded evaluation utterances.
Business specification: `data/starter_kit/README.ru.md`.

## Current implementation status

- **Implemented:** `POST /api/message`, one structured SDK routing call per turn,
  strict ID/slot validation, RU/KK/mixed routing contract, single/multi-intent prompt,
  continuation/topic switching, bounded in-memory sessions/traces, confidence policy,
  clarification questions/options, basic grounded read-only replies, evaluation CLI and a
  separate opt-in `/dev` manual stand. The integrated production frontend adds same-session
  runtime, microphone/file streaming STT, browser TTS and supervisor traces.
- **Verified offline:** API conversations and concurrency, actual installed SDK HTTP
  transport with fixtures (one request even on provider failure), and official evaluator
  integration. Live 104-case before/after measurements are recorded in `ROUTER_EVALUATION.md`;
  offline fixture checks are not model-accuracy measurements.
- **Still incomplete:** business writes/confirmation, actual identity verification, full
  business answers, real operator transfer and public supervisor feed.
  Legacy `/api/v1/turns/text` remains 501 and is not used. Live routing/STT use the local key;
  TTS uses installed browser voices. Missing dependencies fail visibly, without mock fallback.
- **Not introduced:** database, Supabase, vector store, RAG, queues, containers or extra agents.

## Navigation

| Path | Responsibility |
|---|---|
| `AGENTS.md` | Persistent engineering rules and Skills |
| `backend/pyproject.toml`, `backend/requirements.lock` | Package, checks, tested dependencies |
| `backend/app/main.py` | FastAPI factory, lifespan and startup command |
| `backend/app/core/` | Settings, contracts, per-app wiring, safe logging |
| `backend/app/api/routes/`, `api/websocket/` | Health/text HTTP and voice WS boundaries |
| `backend/app/speech/stt/`, `speech/tts/` | Provider protocols and minimal OpenAI adapters |
| `backend/app/triage/` | Text preparation; future language/normalization |
| `backend/app/agent/` | One-call SDK Router, safe errors, prompts and output validation |
| `backend/app/dialog/` | DialogueState (DialogState alias), message orchestration, locked LRU store |
| `backend/app/scenarios/` | Catalog, policy and non-executing requirements inspection |
| `backend/app/tools/` | Action registry plus narrow read-only client/policy/claim/knowledge helpers |
| `backend/app/data/` | Supplied JSON models, loaders and read-only repositories |
| `backend/app/response/` | Slot/system replies and SC17/25/31/33/34 grounded read-only slice |
| `backend/app/dev_stand/index.html`, `api/routes/dev.py` | Opt-in same-origin text debug stand; not production UI |
| `backend/app/tracing/` | TraceRecord, nullable latencies and bounded collector |
| `backend/app/evaluation/` | Data/live-eval CLI, exclusive predictions and official evaluator report |
| `backend/tests/unit/`, `backend/tests/integration/` | Offline tests and API smoke checks |
| `frontend/src/main.tsx`, `App.tsx` | UI startup, live health and conversation/trace shell |
| `frontend/src/runtime/ConversationRuntime.ts` | Session lifecycle, transcript/text turn loop, voice input bridge |
| `frontend/src/services/agentClient.ts`, `tts.ts`, `tts/BrowserTtsService.ts` | HTTP/mock agent, TTS contract and browser playback |
| `frontend/src/components/voice/TtsDebugPanel.tsx` | Manual Russian/Kazakh browser voice check and playback timings |
| `frontend/src/components/voice/VoiceControls.tsx`, `voiceRuntimeBridge.ts` | Streaming mic/file capture UI and final-transcript bridge to runtime |
| `frontend/src/components/trace/traceViewModel.ts`, `TracePanel.tsx` | Defensive view of supplied scenarios, context, clarification, handoff and latency |
| `frontend/src/api/`, `hooks/`, `types/`, `components/` | Client, health hook, contracts and UI modules |
| `frontend/vite.config.ts` | Local /health and /api proxy to backend port 8000 |
| `data/starter_kit/` | One canonical copy of business/evaluation inputs |
| `docs/ARCHITECTURE.md` | Detailed boundaries, contracts and parallel ownership |
| `docs/AGENT_CORE_3H_PLAN.md` | Supplied implementation plan, preserved unchanged |
| `docs/ROUTER_EVALUATION.md` | Live measurements, failures, general prompt changes and remaining errors |
| `docs/MVP_VALIDATION.md` | Integrated stand verification, startup and remaining demo limits |
| `scripts/` | Live API/runtime smoke checks and saved evaluation comparison |
| `docs/INTEGRATION.md` | Short frontend/Voice Input/Agent Core handoff contract and checks |
| `docs/VOICE_STREAMING_CONTRACT.md` | PCM protocol, dependencies, endpointing and voice checks |

Backend paths in this table are relative to `backend/app/` where abbreviated.

## Actual and planned flow

Startup loads seven JSON files once, checks shapes/references and constructs local services.
Implemented text API: request validation → per-session lock → prior-state snapshot → one
Router Agent structured call → validation/policy → context transition → deterministic
read-only lookup/slot/system reply → state + trace → wait for next turn. No second LLM,
LLM tools, RAG, agent handoffs or provider-side conversation storage.
The SDK uses `max_turns=1`, no SDK/client retries, 45-second timeout and disabled SDK tracing.
The current utterance is serialized after background state/history to reduce stale-context
selection; no expected labels or evaluation IDs enter the routing input.

The browser fetches real health through Vite. The frontend runtime creates one session ID,
accepts text through `sendText()` or only `utterance.final` through `handleTranscript()`, sends
`POST /api/message`, displays the reply, awaits TTS playback, then resumes listening unless
the API says `handoff` or `ended`. Browser TTS uses `speechSynthesis` and waits for
`onend`; `onstart` gives first-audio latency. A no-audio adapter remains for tests.
Voice controller start/stop calls are serialized so a delayed start is stopped on reset/end.
VoiceControls opens one WebSocket per utterance using that same session ID; partials stay
in the voice UI. Real HTTP mode is the default; no key enters the frontend.
The voice check panel has Russian/Kazakh samples, selected voice and playback timings.
The conversation panel shows runtime and backend conversation status. The trace panel
renders only supplied fields, keeps multi-intent order, and uses browser STT/TTS first-audio
timings only when corresponding backend trace timings are absent. It does not show raw trace
data or infer routing decisions. Voice tools are in a disclosure below the main panels.
Mock agent replies and trace fixtures are visibly labeled and enabled only by
`VITE_USE_MOCK_AGENT=true` in Vite dev.
Uncheck «Голосовой ввод» for text-only input with the same runtime/session/TTS. This stops
capture, ignores late voice finals and prevents automatic microphone restart. The local Stop
button does not overwrite backend conversation_status or supervisor trace with a fake end.
The end-to-end path is browser → STT → Router Agent ↔ dialog state → policy → bounded
read-only tools ↔ knowledge/mock backend → response → browser TTS → listen again.
Application traces expose concise reasons and measured latency, never hidden chain-of-thought.

## API and domain contracts

- `GET /health` → 200: status, service, mode=foundation and starter-kit counts.
- `POST /api/message`: `{session_id, text}`; nonblank string ID up to 128 characters,
  text up to 10,000 characters, whitespace trimmed. Reuse the ID for later turns.
  Returns `{session_id, response_text, routing, state, trace, conversation_status}`.
  Invalid input 422; missing key/model 503; provider/structured-output failure 502;
  timeout 504; ended/handoff session 409 (use a new ID); busy session pool 503.
  Failed routing does not commit history/state/trace. Responses do not claim actions ran.
- `GET /dev`: standalone debug form, enabled only with `ENABLE_DEV_STAND=true` (otherwise
  404). Reuses editable session ID, shows reply/status/routing/state/trace and browser/backend
  latency. Text rendered safely; no key in browser. New session does not erase older sessions.
- `POST /api/v1/turns/text`: UUID session_id, nonblank text up to 10,000 characters;
  valid input → 501 `{error: {code: not_implemented, message}}`; invalid input → 422.
- Frontend rejects blank/malformed replies, times out after 60 seconds, accepts additive
  response fields, and never substitutes a mock.
  Optional `trace` fields shown in the browser include turn, transcript, language, scenarios,
  alternatives, concise reason, slots, actions, clarification, handoff and `latency_ms`.
  Optional `state` fields shown include active_scenario, scenario_stack and pending_scenarios.
- `WS /api/v1/voice`: one-utterance PCM16 streaming STT; final event includes text,
  nullable language and `stt_after_commit_ms`. See `docs/VOICE_STREAMING_CONTRACT.md`.
- `agent/schemas.py`: RouterDecision has language, response_language (ru/kk), segments, selections,
  alternatives, slots, optional clarification_question and continuation. SDK transport uses a named-slot list for closed JSON
  schema; `to_decision()` restores the slots object. Dependencies use earlier zero-based indices.
  SDK selections/segments are nonempty even for system intents. Fresh routing input omits
  storage language defaults; source enum spellings normalize before strict validation.
- `dialog/models.py`: DialogueState includes session/language/response_language/client,
  active scenario, stack, pending scenarios, slots, confirmation flag, turn number,
  unclear and consecutive-low-confidence counts, clarification_options, conversation_status and bounded history.
  Statuses: active, awaiting_user, awaiting_confirmation, handoff, ended; confirmation is
  reserved, not emitted until a real preview/confirmation workflow exists.
- `tracing/models.py`: transcript, scenarios, alternatives, concise reason, slots, actions,
  session/turn, clarification/handoff/status, active/pending and measured timings
  (router/policy/response/total), source_keys, policy_outcome and completed_scenario.
  Actions list only attempted read-only helpers; unmeasured stages = null. Read-only helper
  duration is included in response latency, not a separately measured tools span.
- `PolicySettings` defaults: accept 0.75, low 0.45, handoff after two low-confidence turns
  or three unresolved clarifications. A confident SC37 request independently triggers handoff.
  Confident urgent requests proceed even with a weak secondary intent; only confident
  selections become active/pending, while original evidence remains in routing/history.
  Urgent requests precede normal requests; continuation preserves pending items and slots.
  Clarification/out-of-scope preserve active work; goodbye ends the session. Policy does not
  perform operator transfer, and the response explicitly says transfer is unavailable.
- A completed read-only answer clears only that scenario: next co-request, then suspended
  stack (LIFO), then older pending work. No remaining work yields `active`, not `ended`.
  Identity correction replaces the old counterpart; a changed established identity drops
  stale policy/claim numbers unless supplied anew. Owned-record filtering is demo lookup,
  not authentication. Unsupported business actions stay unavailable and never report success.
- Engine inspection and awaiting_confirmation do not authorize execution. Irreversible
  action registration/execution is blocked. No supervisor endpoint/authorization exists yet.

## Data, state and evaluation

`data/starter_kit/` contains scenarios.json (40 + 3 system intents), slots.json (43),
actions.json (31), knowledge_base.json, mock_backend.json (11 clients, 11 policies,
4 claims, 2 payments), dialogs_sample.json (10), dev_utterances.json (104), evaluate.py,
README.md, README.ru.md and README.kz.md. All supplied data is synthetic; reference date
**2026-10-01**. JSON files use metadata wrappers, not bare root arrays. Originals are unchanged;
.DS_Store/AppleDouble files are excluded.

User-supplied `scenarios.json`, `dev_utterances.json`, `evaluate.py` from Downloads /
`voice_router_dataset/case_2/voice_router_dataset` were reverified on 2026-09-23:
all three canonical copies match their supplied SHA-256 hashes byte-for-byte. Keep these
files unchanged as the baseline for future work. Router uses descriptions, not_this_if,
priority, up to two source examples per language, slots and reference date; never dev labels.

Knowledge uses exact dotted-key lookups, not retrieval. Repository reads return copies.
State/traces are bounded and per-process; restart loses them. Use one worker. State keeps
100 LRU sessions and 20 history entries each; traces keep 100 sessions × 100 turns.
Concurrent same-session turns are serialized, distinct sessions can run concurrently,
and active sessions are pinned against eviction. Session IDs are demo correlation IDs,
not authentication: keep the service local until access control is implemented.
No database, migrations, RLS, persistent storage or upload service exists.

Evaluation passes only text and fresh state to an injected Router, without expected labels,
and writes `{utterance_id: [scenario_id, ...]}`. The supplied evaluator scores that output.
Offline adapter tests are not model accuracy measurements. `--run` defaults to all 104
utterances, invokes unchanged `evaluate.py`, and saves predictions plus a sibling
`.report.txt` with official metrics and `.details.json` with validated outputs, safe failure
codes, model/prompt/data fingerprints and routing timings. Outputs are exclusive-create.
Default failure aborts; explicit `--continue-on-error` records null decision/empty prediction
and counts it wrong, never fabricating a route. `--limit N` is an explicit subset run.
Concurrency and call-start pacing are configurable; use serial paced runs for comparison.
Allowlisted validation_reason distinguishes output contract failures without saving raw
rejected values. Live manual slot misses/unstable output rejection remain documented in the
evaluation report; a high scenario score is not evidence of complete business behavior.
Latest integrated 104-case run (gpt-4.1-mini, current utterance last, serial paced): primary
91.35%, full 90.38%, multi-intent recall 92.31%; zero provider failures and one invalid output.
Earlier before/after regressions and complete subgroup/error analysis are retained in
`docs/ROUTER_EVALUATION.md`; no perfect-routing claim is made. Deterministic reply rendering
uses grounded RU/KK translations. Current monolingual request language overrides stale reply
language; a conflicting generated clarification is replaced with a localized fallback.
A small Kazakh-orthography guard also protects reply language from stale Russian context
labels; a borrowed place name or greeting in a longer Russian sentence is not enough.
This affects replies only, not scenario selection or the recorded Router language label.

## Configuration and commands

Names: OPENAI_API_KEY, OPENAI_ROUTER_MODEL, ROUTER_TIMEOUT_SECONDS (45),
ROUTER_MAX_OUTPUT_TOKENS (2500), BACKEND_HOST, BACKEND_PORT, FRONTEND_ORIGIN,
ROUTER_ACCEPT_THRESHOLD (.75), ROUTER_LOW_THRESHOLD (.45), ROUTER_HANDOFF_AFTER (2),
ROUTER_MAX_UNCLEAR_TURNS (3), ENABLE_DEV_STAND (false), optional STARTER_KIT_PATH.
Root .env.example contains no credentials; .env is ignored.
Health, UI and offline tests need no credentials. Live routing/evaluation needs an explicit
Responses/structured-output-compatible model and key. Local .env has a verified key and
`gpt-4.1-mini`; the model remains configurable, with no implicit production default.
Frontend
`frontend/.env.example` defines `VITE_API_BASE_URL` (empty means Vite proxy) and
`VITE_USE_MOCK_AGENT` (false by default; true works only in Vite dev).
Streaming STT uses gpt-live-transcribe and local faster-whisper Silero VAD (voice extra).
Browser TTS uses the backend response_language and installed OS/browser voices.

PowerShell from repository root:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -c backend/requirements.lock -e './backend[dev,voice]'
./.venv/Scripts/python.exe -m app.main
./.venv/Scripts/python.exe -m pytest backend/tests -q
./.venv/Scripts/ruff.exe check backend/app backend/tests
./.venv/Scripts/ruff.exe format --check backend/app backend/tests
./.venv/Scripts/python.exe -X utf8 -m app.evaluation --check-data
./.venv/Scripts/python.exe -X utf8 -m app.evaluation --run --output predictions.json --concurrency 1 --min-interval-seconds 4 --continue-on-error
./.venv/Scripts/python.exe -X utf8 scripts/smoke_agent_core.py --pace-seconds 4
node scripts/smoke_teammate_runtime.mjs origin/feature/conversation-runtime http://127.0.0.1:8000
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/message -ContentType 'application/json; charset=utf-8' -Body '{"session_id":"abc123","text":"Сколько стоит страховка на машину?"}'
```

Frontend (second terminal, repository root): `cd frontend`, `npm ci`, `npm run dev`.
Keep `VITE_USE_MOCK_AGENT=false` for the full live stand; true is for isolated dev fixtures only.
Frontend checks: `npm run typecheck`, `npm run build`, `npm run test:runtime`,
`npm run test:tts`, `npm run test:trace`, `npm run test:integration`,
`npm run test:voice-bridge`. Browser speech needs a supported browser and an installed voice;
Kazakh uses an exact/prefix voice when available, otherwise the browser default.
The evaluator needs real predictions from Router v1. Defaults: backend 127.0.0.1:8000,
frontend localhost:5173. Update Vite proxy if changing backend port.
Tested with Python 3.13 and Node 24.13; minimum Python 3.11.

## Skills and next step

Skills live in `.agents/skills/`; read only relevant ones: agents-sdk, agent-evals,
agent-debugging, security-review, demo-readiness. supabase-data is conditional on future
persistence; agri-rag-vision is irrelevant to current requirements.

Integrated `feature/agent-core-router-eval` with `origin/integration/voice-runtime` (0261acc),
which already includes `origin/feature/conversation-runtime` (cb9e7fb) and
`origin/transcribtion` (138d5fb), without modifying teammate branches. Transcript language
and STT timing stay on the runtime side; only session_id/text cross the Core API boundary.
`/dev` remains an optional separate text debugger, not the full voice stand.

Next: resolve measured routing errors, improve complete RU/KK business wording and actual
identity verification, then implement one preview/confirmation workflow when needed.
No DB or extra agent was added; irreversible execution remains blocked.
