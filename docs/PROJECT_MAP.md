# Project Map

## Purpose and requirements

HackAlem Voice Router for fictional Saqta Insurance. Prioritize LLM-based scenario
selection in Russian, Kazakh and mixed-language dialogue, context, ambiguity, topic
changes, clarification and handoff. Final MVP requires voice; text remains available.
No encoder intent classifier or hardcoded evaluation utterances.
Business specification: `data/starter_kit/README.ru.md`.

## Current implementation status

- **Implemented:** FastAPI startup, validated data, health endpoint, React/Vite shell,
  typed contracts, bounded copied memory state/traces, catalog, read-only repositories,
  provisional deterministic policy, scenario-requirements inspection and action registry.
- **Partial:** one SDK agent factory/strict output schema; minimal STT and buffered TTS
  adapters with bounded calls and explicit credential errors; evaluation adapter; triage
  only trims whitespace and preserves a supplied language hint.
- **Scaffold only:** SDK Runner execution, text orchestration, scenario execution and
  confirmation, response generation and supervisor feed. Text returns 501.
  No business action handlers exist.
- **Voice bench implemented:** browser mic/file PCM -> backend WS -> OpenAI live
  transcription, Silero automatic endpointing (default 2.5 s), partial/final text and timings.
  No routing/TTS integration. See `docs/VOICE_STREAMING_CONTRACT.md`.
- **Not introduced:** database, Supabase, vector store, RAG, queues, containers or extra agents.

## Navigation

Voice recording tests: `scripts/transcribe_audio.py` is a standalone faster-whisper
offline runner for A01-A27; see `docs/VOICE_TESTS.md`. It saves local transcripts and
STT timings under ignored `work/voice/`; it does not implement live endpointing,
TTS, or replace the backend STT adapter. Dependencies: `scripts/requirements-voice.txt`.
`scripts/test_openai_stream.py` replays one recording in real time directly to OpenAI
`gpt-live-transcribe`, using a server-side OPENAI_API_KEY from ignored .env. This
standalone cloud probe records partials and post-commit latency. The integrated
browser/automatic endpointing/backend test is `scripts/test_voice_backend.py`. See
`docs/VOICE_STREAMING_CONTRACT.md`; dependencies: `scripts/requirements-cloud-voice.txt`.

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
| `frontend/src/main.tsx`, `App.tsx` | UI startup, live health, conversation/voice/trace areas |
| `frontend/src/api/`, `hooks/`, `types/`, `components/` | Client, health hook, contracts and UI modules |
| `frontend/vite.config.ts` | Local /health and /api proxy to backend port 8000 |
| `data/starter_kit/` | One canonical copy of business/evaluation inputs |
| `docs/ARCHITECTURE.md` | Detailed boundaries, contracts and parallel ownership |

Backend paths in this table are relative to `backend/app/` where abbreviated.

## Actual and planned flow

Startup loads seven JSON files once, checks shapes/references and constructs local services.
The browser fetches real health through Vite; text submission ends in 501 without state changes.

Planned: browser → STT → triage → Router Agent ↔ dialog state → policy → scenario engine
→ allowed tools ↔ knowledge/mock backend → response → TTS → browser. Each stage supplies
measured application-level traces, never hidden chain-of-thought. This pipeline is not wired yet.

## API and domain contracts

- `GET /health` → 200: status, service, mode=foundation and starter-kit counts.
- `POST /api/v1/turns/text`: UUID session_id, nonblank text up to 10,000 characters;
  valid input → 501 `{error: {code: not_implemented, message}}`; invalid input → 422.
- `WS /api/v1/voice`: start(UUID, sample_rate=24000, channels=1, pause_ms), PCM16
  binary frames; ready/activity/partial/committed/final/empty/error events. Origin
  restricted; two sessions per process. See `docs/VOICE_STREAMING_CONTRACT.md`.
- Voice code: `api/websocket/voice.py`, `speech/stt/endpointing.py`, frontend
  `components/voice/VoiceControls.tsx`, `public/pcm-worklet.js`. Replay test:
  `scripts/test_voice_backend.py`; results in ignored `work/voice/backend-stream/`.
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
optional STARTER_KIT_PATH. Root .env.example is placeholders only; root .env is optional/ignored.
Health, UI and offline tests need no credentials. Streaming STT needs OPENAI_API_KEY
and the backend voice extra (`pip install -e "./backend[dev,voice]"`). Live model is
`gpt-live-transcribe`, languages kk/ru. Startup and limits are in the voice contract.

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

Frontend (second terminal, repository root): `cd frontend`, `npm ci`, `npm run dev`.
Frontend checks: `npm run typecheck`, `npm run build`.
The evaluator needs real predictions from Router v1. Defaults: backend 127.0.0.1:8000,
frontend localhost:5173. Update Vite proxy if changing backend port.
Tested with Python 3.13 and Node 24.13; minimum Python 3.11.

## Skills and next step

Skills live in `.agents/skills/`; read only relevant ones: agents-sdk, agent-evals,
agent-debugging, security-review, demo-readiness. supabase-data is conditional on future
persistence; agri-rag-vision is irrelevant to current requirements.

Next: **Router v1 + evaluation on all 104 dev utterances**. Select a model and supply
credentials externally; connect a bounded SDK Runner, validate IDs/slots and measure
baseline routing before prompt optimization and integration with the voice bench.
