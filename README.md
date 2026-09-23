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
a working voice test bench, and an empty supervisor panel. Sending text displays the
backend's explicit `501 not_implemented` error. No conversation or trace is fabricated.

Vite dev/preview proxies target `127.0.0.1:8000`; update `frontend/vite.config.ts`
if you change the backend port. Run one backend process while state is in memory.

## Configuration

No credentials are required for startup or offline tests. `.env.example` contains
empty placeholders; the backend can read an optional, Git-ignored root `.env`.
Never commit credentials or place them in frontend environment variables.

Configuration names: `OPENAI_API_KEY`, `OPENAI_ROUTER_MODEL`, `BACKEND_HOST`,
`BACKEND_PORT`, `FRONTEND_ORIGIN`, optional `STARTER_KIT_PATH`. Empty values use
application defaults. OPENAI_API_KEY also enables the streaming voice test bench. Install the voice extra
with `pip install -c backend/requirements.lock -e "./backend[dev,voice]"`. See
[the voice setup and contract](docs/VOICE_STREAMING_CONTRACT.md) for startup, automatic
end-of-utterance detection, file replay and latency measurements.

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

## Starter kit and next module

The original synthetic dataset lives only in `data/starter_kit/`, including seven JSON
files, three READMEs and unmodified `evaluate.py`. There are 40 business scenarios and
three system intents. Reference date: **2026-10-01**. Company, insurance and client
data are fictional.

Next: **Router v1 + evaluation on all 104 dev utterances**. The adapter in
`backend/app/evaluation/runner.py` accepts a Router and produces the exact
`{utterance_id: [scenario_id, ...]}` prediction format. Once real predictions exist,
run from the repository root:

```powershell
./.venv/Scripts/python.exe data/starter_kit/evaluate.py predictions.json data/starter_kit/dev_utterances.json
```

Routing execution, full scenario workflows, response generation and browser TTS
remain unimplemented. Browser streaming STT is implemented and live-tested with
OpenAI, using local Silero VAD to finish utterances automatically after a configurable
pause (default 2.5 seconds). The result populates the text field; routing is separate.

Start future tasks with `AGENTS.md` and [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md).
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) documents module ownership and contracts.
