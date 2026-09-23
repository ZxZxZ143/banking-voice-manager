# Voice Router

HackAlem contact-center simulation for fictional **Saqta Insurance**. The core task is
LLM scenario routing in Russian, Kazakh and mixed-language dialogue. This branch is
the runnable technical foundation, not a completed voice robot.

```text
Browser → STT → Triage → Router Agent ↔ Dialog State
                            ↓
                    Decision Policy → Scenario Engine → Tools
                                                         ↙  ↘
                                                 Knowledge  Mock Backend
                            ↓
                    Response → TTS → Browser
All stages → Trace Collector → Supervisor Panel
```

Backend: Python 3.11+, FastAPI, Pydantic, OpenAI Agents SDK. Frontend: React,
TypeScript, Vite. Tested with Python 3.13 and Node 24.13; frontend requires
Node 20.19+ on the 20.x line or Node 22.12+.

## Install and run (Windows PowerShell)

From the repository root:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -c backend/requirements.lock -e './backend[dev]'
./.venv/Scripts/python.exe -m app.main
```

Backend runs at `http://127.0.0.1:8000`; API documentation is at `/docs`.
`GET /health` reports real startup/data status and loaded counts. The server fails
startup if required starter-kit JSON is missing or invalid.

In a second terminal, from the repository root:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. The shell shows real backend health, a text field,
disabled voice controls, and an empty supervisor panel. Sending text displays the
backend's explicit `501 not_implemented` error. No conversation or trace is fabricated.

Vite dev/preview proxies target `127.0.0.1:8000`; update `frontend/vite.config.ts`
if you change the backend port. Run one backend process while state is in memory.

## Configuration

No credentials are required for startup or offline tests. `.env.example` contains
empty placeholders; the backend can read an optional, Git-ignored root `.env`.
Never commit credentials or place them in frontend environment variables.

Configuration names: `OPENAI_API_KEY`, `OPENAI_ROUTER_MODEL`, `BACKEND_HOST`,
`BACKEND_PORT`, `FRONTEND_ORIGIN`, optional `STARTER_KIT_PATH`. Empty values use
application defaults. Live `/api/message` and evaluation require both OpenAI settings;
there is no default model or mock fallback. Optional `ROUTER_TIMEOUT_SECONDS` defaults
to 45 and `ROUTER_MAX_OUTPUT_TOKENS` to 2500. Speech remains outside this milestone.

## Checks

From the repository root:

```powershell
./.venv/Scripts/python.exe -m pytest backend/tests -q
./.venv/Scripts/ruff.exe check backend/app backend/tests
./.venv/Scripts/ruff.exe format --check backend/app backend/tests
./.venv/Scripts/python.exe -m app.evaluation --check-data
cd frontend
npm run typecheck
npm run build
```

`backend/requirements.lock` records the tested dependency snapshot;
`frontend/package-lock.json` records npm dependencies. Tests cover data, contracts,
policy, state, transport errors and speech adapters using offline fixtures. They do
not measure live OpenAI quality or routing accuracy.

## Text routing and evaluation

`POST /api/message` accepts nonblank string `session_id` and `text`; reuse the same ID
to retain context. It returns `response_text`, `routing`, `state`, `trace` and
`conversation_status` plus the session ID. One agent makes one structured call per turn.
RU/KK/mixed, independent multi-intent requests, topic switching and slot continuation
are supported by the routing contract/prompt. API tests use explicitly scripted responses;
live measurements are recorded in `docs/ROUTER_EVALUATION.md`. The working production
shell still uses the legacy endpoint; teammate runtime compatibility is checked separately.

Replies ask a clarification/slot question, return a system response or use a small grounded
read-only slice (offices, payments, app help, owned demo policy/claim). No business writes or
actual operator transfer occur. Completed answers leave the conversation open; only goodbye
ends it. State/history/traces are bounded in-memory,
lost on restart; same-session requests are serialized. This local demo has no authentication.
Use a new ID after `ended`/`handoff`. Missing configuration returns 503, provider/output
errors 502, timeout 504, invalid input 422; failed turns do not advance state.

## Starter kit and next module

The original synthetic dataset lives only in `data/starter_kit/`, including seven JSON
files, three READMEs and unmodified `evaluate.py`. There are 40 business scenarios and
three system intents. Reference date: **2026-10-01**. Company, insurance and client
data are fictional.

**Live evaluation on all 104 dev utterances.** The adapter in
`backend/app/evaluation/runner.py` accepts a Router and produces the exact
`{utterance_id: [scenario_id, ...]}` prediction format. With model/key configured, run:

```powershell
./.venv/Scripts/python.exe -X utf8 -m app.evaluation --run --output predictions.json --concurrency 1 --min-interval-seconds 4 --continue-on-error
```

The CLI uses unchanged `evaluate.py` and creates sibling `.report.txt` and `.details.json`
files with metrics, timings and safe error metadata; it never overwrites a previous run.
Choose another output name on subsequent runs. `--limit N` selects a subset. Default mode
aborts on failure; explicit `--continue-on-error` counts failed calls as empty predictions.
Expected labels never enter the router. See `docs/ROUTER_EVALUATION.md` for before/after.

Full scenario workflows, complete localized business responses and browser voice transport
remain unimplemented. STT/TTS adapters exist but are not wired into the UI
and have not been tested against a live provider.

## Manual Agent Core stand

Set `ENABLE_DEV_STAND=true` in the ignored root `.env`, configure `OPENAI_API_KEY` and
`OPENAI_ROUTER_MODEL`, then run `./.venv/Scripts/python.exe -m app.main` from repository root.
Open `http://127.0.0.1:8000/dev`. Type a message, inspect reply/status/routing/state/trace,
then send another message without changing the session ID. Reload creates a new ID;
you can paste a prior ID while the same backend process is running. No npm build is needed.
Keep this unauthenticated synthetic-data stand bound to loopback; the route is off by default.

Configurable policy: `ROUTER_ACCEPT_THRESHOLD`, `ROUTER_LOW_THRESHOLD`,
`ROUTER_HANDOFF_AFTER`, `ROUTER_MAX_UNCLEAR_TURNS` (defaults .75/.45/2/3).
The optional smoke scripts make real, billable model calls, with no automatic retries:

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/smoke_agent_core.py --interval-seconds 4
node scripts/smoke_teammate_runtime.mjs origin/feature/conversation-runtime http://127.0.0.1:8000
```

The latter reads fetched teammate source without checking out or modifying its branch,
uses a 60-second client timeout and a visibly synthetic/silent TTS fixture, not real voice.

Start future tasks with `AGENTS.md` and [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md).
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) documents module ownership and contracts.
