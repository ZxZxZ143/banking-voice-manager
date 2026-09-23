# Project Map

## Purpose and requirements

HackAlem Voice Router for fictional Saqta Insurance. Prioritize LLM-based scenario
selection in Russian, Kazakh and mixed-language dialogue, context, ambiguity, topic
changes, clarification and handoff. Final MVP requires voice; text remains available.
No encoder intent classifier or hardcoded evaluation utterances.
Business specification: `data/starter_kit/README.ru.md`.

## Current implementation status

- **Implemented:** FastAPI startup, validated data, health endpoint, React/Vite shell,
  frontend conversation runtime, browser TTS playback, supervisor trace view and typed integration adapters, backend typed contracts,
  bounded copied memory state/traces, catalog, read-only repositories,
  provisional deterministic policy, scenario-requirements inspection and action registry.
- **Partial:** one SDK agent factory/strict output schema; minimal STT and buffered TTS
  adapters with bounded calls and explicit credential errors; evaluation adapter; triage
  only trims whitespace and preserves a supplied language hint.
- **Scaffold only:** SDK Runner execution, backend text orchestration, scenario execution and
  confirmation, response generation, voice transport and supervisor feed.
  Existing backend text endpoint returns 501; voice sends an error then closes. The
  frontend's expected `/api/message` endpoint does not exist yet. No business action handlers exist.
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
| `backend/app/agent/` | Router protocol, SDK factory, prompts and output contracts |
| `backend/app/dialog/` | DialogState, bounded history and copied memory store |
| `backend/app/scenarios/` | Catalog, policy and non-executing requirements inspection |
| `backend/app/tools/` | Action registry, ToolResult and errors |
| `backend/app/data/` | Supplied JSON models, loaders and read-only repositories |
| `backend/app/response/` | Separate response contract and unimplemented generator |
| `backend/app/tracing/` | TraceRecord, nullable latencies and bounded collector |
| `backend/app/evaluation/` | Data check CLI, router-to-predictions adapter |
| `backend/tests/unit/`, `backend/tests/integration/` | Offline tests and API smoke checks |
| `frontend/src/main.tsx`, `App.tsx` | UI startup, live health and conversation/trace shell |
| `frontend/src/runtime/ConversationRuntime.ts` | Session lifecycle, transcript/text turn loop, voice input bridge |
| `frontend/src/services/agentClient.ts`, `tts.ts`, `tts/BrowserTtsService.ts` | HTTP/mock agent, TTS contract and browser playback |
| `frontend/src/components/voice/TtsDebugPanel.tsx` | Manual Russian/Kazakh browser voice check and playback timings |
| `frontend/src/components/trace/traceViewModel.ts`, `TracePanel.tsx` | Defensive view of supplied scenarios, context, clarification, handoff and latency |
| `frontend/src/api/`, `hooks/`, `types/`, `components/` | Client, health hook, contracts and UI modules |
| `frontend/vite.config.ts` | Local /health and /api proxy to backend port 8000 |
| `data/starter_kit/` | One canonical copy of business/evaluation inputs |
| `docs/ARCHITECTURE.md` | Detailed boundaries, contracts and parallel ownership |

Backend paths in this table are relative to `backend/app/` where abbreviated.

## Actual and planned flow

Startup loads seven JSON files once, checks shapes/references and constructs local services.
The browser fetches real health through Vite. The frontend runtime creates one session ID,
accepts text through `sendText()` or an STT callback through `handleTranscript()`, sends
`POST /api/message`, displays the reply, awaits TTS playback, then resumes listening unless
the API says `handoff` or `ended`. Browser TTS uses `speechSynthesis` and waits for
`onend`; `onstart` gives first-audio latency. A no-audio adapter remains for tests.
The voice check panel has Russian/Kazakh samples, selected voice and playback timings.
The conversation panel shows runtime and backend conversation status. The trace panel
renders only supplied fields, keeps multi-intent order, and uses browser STT/TTS first-audio
timings only when corresponding backend trace timings are absent. It does not show raw trace
data or infer routing decisions. Voice tools are in a disclosure below the main panels.
Mock agent replies and trace fixtures are visibly labeled and enabled only by
`VITE_USE_MOCK_AGENT=true` in Vite dev.
With the current backend and HTTP mode, `/api/message` returns a visible 404.

Planned: browser → STT → triage → Router Agent ↔ dialog state → policy → scenario engine
→ allowed tools ↔ knowledge/mock backend → response → TTS → browser. Each stage supplies
measured application-level traces, never hidden chain-of-thought. This pipeline is not wired yet.

## API and domain contracts

- `GET /health` → 200: status, service, mode=foundation and starter-kit counts.
- `POST /api/v1/turns/text`: UUID session_id, nonblank text up to 10,000 characters;
  valid input → 501 `{error: {code: not_implemented, message}}`; invalid input → 422.
- **Expected frontend integration, not implemented by backend:** `POST /api/message` with
  `{session_id: string, text: string}`; response requires `{response_text: string,
  conversation_status: "active" | "awaiting_user" | "awaiting_confirmation" |
  "handoff" | "ended"}` and optionally `routing`, `state`, `trace` (untyped JSON).
  Frontend rejects malformed replies, times out after 20 seconds, and never substitutes a mock.
  Optional `trace` fields shown in the browser include turn, transcript, language, scenarios,
  alternatives, concise reason, slots, actions, clarification, handoff and `latency_ms`.
  Optional `state` fields shown include active_scenario, scenario_stack and pending_scenarios.
- `WS /api/v1/voice`: accepts, sends the same not-implemented error, closes 1013.
- `agent/schemas.py`: RouterDecision has language, semantic segments, ordered selections,
  alternatives, slots and continuation. SDK transport uses a named-slot list for closed JSON
  schema; `to_decision()` restores the slots object. Dependencies use earlier zero-based indices.
- `dialog/models.py`: session/language/client, active scenario, stack, pending scenarios,
  slots, confirmation flag, turn number, low-confidence count and bounded history.
- `tracing/models.py`: transcript, scenarios, alternatives, concise reason, slots, actions,
  and measured timings (stt/triage/router/tools/response/tts_first_audio/total). Unmeasured = null.
- `PolicySettings` defaults: accept 0.75, low 0.45, handoff after two low-confidence turns.
  Policy is pure and does not perform operator transfer.
- Engine inspection and awaiting_confirmation do not authorize execution. Irreversible
  action registration/execution is blocked. No supervisor endpoint/authorization exists yet.

## Data, state and evaluation

`data/starter_kit/` contains scenarios.json (40 + 3 system intents), slots.json (43),
actions.json (31), knowledge_base.json, mock_backend.json (11 clients, 11 policies,
4 claims, 2 payments), dialogs_sample.json (10), dev_utterances.json (104), evaluate.py,
README.md, README.ru.md and README.kz.md. All supplied data is synthetic; reference date
**2026-10-01**. JSON files use metadata wrappers, not bare root arrays. Originals are unchanged;
.DS_Store/AppleDouble files are excluded.

Knowledge uses exact dotted-key lookups, not retrieval. Repository reads return copies.
State/traces are bounded and per-process; restart loses them. Use one worker. Concurrent
turns within a session will need serialization when orchestration is added.
No database, migrations, RLS, persistent storage or upload service exists.

Evaluation passes only text and fresh state to an injected Router, without expected labels,
and writes `{utterance_id: [scenario_id, ...]}`. The supplied evaluator scores that output.
Offline adapter tests are not model accuracy measurements.

## Configuration and commands

Names: OPENAI_API_KEY, OPENAI_ROUTER_MODEL, BACKEND_HOST, BACKEND_PORT, FRONTEND_ORIGIN,
optional STARTER_KIT_PATH. Root .env.example is backend placeholders only. Frontend
`frontend/.env.example` defines `VITE_API_BASE_URL` (empty means Vite proxy) and
`VITE_USE_MOCK_AGENT` (false by default; true works only in Vite dev).
Health, UI and offline tests need no credentials. Model/voice selection and live provider
verification remain future integration work.

PowerShell from repository root:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -c backend/requirements.lock -e './backend[dev]'
./.venv/Scripts/python.exe -m app.main
./.venv/Scripts/python.exe -m pytest backend/tests -q
./.venv/Scripts/ruff.exe check backend/app backend/tests
./.venv/Scripts/ruff.exe format --check backend/app backend/tests
./.venv/Scripts/python.exe -m app.evaluation --check-data
./.venv/Scripts/python.exe data/starter_kit/evaluate.py predictions.json data/starter_kit/dev_utterances.json
```

Frontend (second terminal, repository root): `cd frontend`, `npm ci`, copy
`.env.example` to `.env.local` and set `VITE_USE_MOCK_AGENT=true` for independent UI
development, then `npm run dev`. Switch it to `false` when Agent Core serves `/api/message`.
Frontend checks: `npm run typecheck`, `npm run build`, `npm run test:runtime`,
`npm run test:tts`, `npm run test:trace`. Browser speech needs a supported browser and an installed voice;
Kazakh uses an exact/prefix voice when available, otherwise the browser default.
The evaluator needs real predictions from Router v1. Defaults: backend 127.0.0.1:8000,
frontend localhost:5173. Update Vite proxy if changing backend port.
Tested with Python 3.13 and Node 24.13; minimum Python 3.11.

## Skills and next step

Skills live in `.agents/skills/`; read only relevant ones: agents-sdk, agent-evals,
agent-debugging, security-review, demo-readiness. supabase-data is conditional on future
persistence; agri-rag-vision is irrelevant to current requirements.

Next: **Router v1 + evaluation on all 104 dev utterances**. Select a model and supply
credentials externally; connect a bounded SDK Runner, validate IDs/slots and measure
baseline routing before prompt optimization and voice wiring.
