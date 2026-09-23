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
  separate opt-in `/dev` manual stand. Existing data, health and production UI shell remain.
- **Verified offline:** API conversations and concurrency, actual installed SDK HTTP
  transport with fixtures (one request even on provider failure), and official evaluator
  integration. Live 104-case before/after measurements are recorded in `ROUTER_EVALUATION.md`;
  offline fixture checks are not model-accuracy measurements.
- **Still incomplete:** business writes/confirmation, actual identity verification, full
  business answers, real operator transfer, production UI merge and supervisor feed.
  Legacy `/api/v1/turns/text` remains 501; voice remains unavailable. Existing speech
  adapters are unchanged and unused. Live routing uses the locally configured model/key.
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
| `frontend/src/main.tsx`, `App.tsx` | UI startup, live health, conversation/voice/trace areas |
| `frontend/src/api/`, `hooks/`, `types/`, `components/` | Client, health hook, contracts and UI modules |
| `frontend/vite.config.ts` | Local /health and /api proxy to backend port 8000 |
| `data/starter_kit/` | One canonical copy of business/evaluation inputs |
| `docs/ARCHITECTURE.md` | Detailed boundaries, contracts and parallel ownership |
| `docs/AGENT_CORE_3H_PLAN.md` | Supplied implementation plan, preserved unchanged |
| `docs/ROUTER_EVALUATION.md` | Live measurements, failures, general prompt changes and remaining errors |
| `scripts/` | Live API/runtime smoke checks and saved evaluation comparison |

Backend paths in this table are relative to `backend/app/` where abbreviated.

## Actual and planned flow

Startup loads seven JSON files once, checks shapes/references and constructs local services.
The browser fetches real health through Vite; its legacy text submission still ends in 501.

Implemented text API: request validation → per-session lock → prior-state snapshot → one
Router Agent structured call → validation/policy → context transition → deterministic
read-only lookup/slot/system reply → state + trace → wait for next turn. No second LLM,
LLM tools, RAG, agent handoffs or provider-side conversation storage.
The SDK uses `max_turns=1`, no SDK/client retries, 45-second timeout and disabled SDK tracing.

Planned: browser → STT → triage → Router Agent ↔ dialog state → policy → scenario engine
→ allowed tools ↔ knowledge/mock backend → response → TTS → browser. Each stage supplies
measured application-level traces, never hidden chain-of-thought. The business/voice stages
of this future pipeline are not wired yet.

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
- `WS /api/v1/voice`: accepts, sends the same not-implemented error, closes 1013.
- `agent/schemas.py`: RouterDecision has language, response_language (ru/kk), segments, selections,
  alternatives, slots, optional clarification_question and continuation. SDK transport uses a named-slot list for closed JSON
  schema; `to_decision()` restores the slots object. Dependencies use earlier zero-based indices.
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

## Configuration and commands

Names: OPENAI_API_KEY, OPENAI_ROUTER_MODEL, ROUTER_TIMEOUT_SECONDS (45),
ROUTER_MAX_OUTPUT_TOKENS (2500), BACKEND_HOST, BACKEND_PORT, FRONTEND_ORIGIN,
ROUTER_ACCEPT_THRESHOLD (.75), ROUTER_LOW_THRESHOLD (.45), ROUTER_HANDOFF_AFTER (2),
ROUTER_MAX_UNCLEAR_TURNS (3), ENABLE_DEV_STAND (false), optional STARTER_KIT_PATH.
Root .env.example contains no credentials; .env is ignored.
Health, UI and offline tests need no credentials. Live routing/evaluation needs an explicit
Responses/structured-output-compatible model and key. Local .env has a verified key and
`gpt-4.1-mini`; the model remains configurable, with no implicit production default.

PowerShell from repository root:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -c backend/requirements.lock -e './backend[dev]'
./.venv/Scripts/python.exe -m app.main
./.venv/Scripts/python.exe -m pytest backend/tests -q
./.venv/Scripts/ruff.exe check backend/app backend/tests
./.venv/Scripts/ruff.exe format --check backend/app backend/tests
./.venv/Scripts/python.exe -X utf8 -m app.evaluation --check-data
./.venv/Scripts/python.exe -X utf8 -m app.evaluation --run --output predictions.json --concurrency 1 --min-interval-seconds 4 --continue-on-error
./.venv/Scripts/python.exe -X utf8 scripts/smoke_agent_core.py --interval-seconds 4
node scripts/smoke_teammate_runtime.mjs origin/feature/conversation-runtime http://127.0.0.1:8000
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/message -ContentType 'application/json; charset=utf-8' -Body '{"session_id":"abc123","text":"Сколько стоит страховка на машину?"}'
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

`git fetch origin` inspected teammate `origin/feature/conversation-runtime` at
`876b038ae8b2b61283e7899eac60f598333b3ba4` without checking out or editing that branch.
Its HttpAgentClient/ConversationRuntime consume the new contract; the compatibility smoke
imports their exact Git blobs without overwriting the working frontend. Transcript language
and STT timing stay on the runtime side; only session_id/text cross this API boundary.
Production follow-ups: raise runtime's 20s default client timeout above the backend's 45s
budget, and use `state.response_language` for TTS rather than the input transcript language.
The production UI has not been merged into this dirty branch; `/dev` is intentionally separate.

Next: resolve remaining measured routing errors, improve full RU/KK business wording, add
explicit preview/confirmation for one business workflow, then integrate production UI/voice.
Multi-intent confidence policy still uses the minimum selected confidence; independent urgent
acceptance with secondary clarification remains a follow-up. No DB or extra agent was added.
