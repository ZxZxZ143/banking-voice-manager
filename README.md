# Insurance Manager

Conversational insurance assistant for Russian, Kazakh and mixed speech. The application combines one OpenAI Agents SDK Router, deterministic insurance replies, a shared conversation runtime, streaming transcription, browser speech synthesis and a supervisor trace.

Business information comes from the supplied **fictional Saqta Insurance** snapshot dated **2026-10-01**. Prices, customers, policies and payments are demonstration data. Future banking scenario packs are outside Stage 1.

## What works

- The existing catalog: 40 insurance scenarios and three system intents. Natural wording, independent multi-intent requests, clarification, topic switching and same-session continuation.
- Source-based quotes for ОГПО, standard КАСКО, travel, property and accident insurance; DMS package information, clinics, documents, payment methods and owned policy/claim/payment lookups.
- Application and servicing flows collect the catalog's required information and transfer the prepared conversation to an operator when an insurer operation is needed.
- Explicit operator request: **«Конечно, передаю диалог оператору.»**, `conversation_status=handoff`. Goodbye produces `ended`. Both preserve history and trace and stop the automatic microphone loop.
- A completed information request stays in the conversation. Scenario slot snapshots prevent old car/trip information from contaminating later requests.
- Invalid structured routing output produces a safe clarification; repeated uncertainty ends in handoff. Provider outages remain visible errors.

Actual policy issuance, renewal, changes, cancellation, SMS/email delivery and contact-center transfer require external integrations. They are never reported as completed here. Identifier lookup against the synthetic snapshot is not real authentication.

## Quick Start — Docker

Requirements: Docker Desktop with a running Linux engine, Docker Compose, Internet access and an OpenAI API key with access to the routing and transcription models.

From the repository root in PowerShell, prepare `.env` once:

```powershell
Copy-Item .env.example .env
```

Set `OPENAI_API_KEY` locally. Keep `OPENAI_ROUTER_MODEL=gpt-4.1-mini` and `ROUTER_TEMPERATURE=0` for the measured configuration. Do not overwrite an existing configured `.env`.

```powershell
docker compose up --build
```

- Application: [http://127.0.0.1:5173](http://127.0.0.1:5173)
- Backend health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- Proxied health: [http://127.0.0.1:5173/health](http://127.0.0.1:5173/health)

`backend` runs FastAPI as a non-root user. `frontend` serves the built React app through Nginx and proxies HTTP and voice WebSocket traffic to `backend:8000`. Health checks gate frontend startup. Both host ports bind to loopback.

```powershell
docker compose ps
docker compose logs backend --tail 30
docker compose down
```

Stopping/recreating the backend clears its in-memory conversations and traces. `.env` is supplied at runtime and excluded from Git and Docker build context. The frontend never receives the API key.

## Environment

| Variable | Meaning |
|---|---|
| `OPENAI_API_KEY` | Server-only local secret; required for live routing/STT |
| `OPENAI_ROUTER_MODEL` | Explicit structured-output model; measured with `gpt-4.1-mini` |
| `ROUTER_TEMPERATURE` | Optional model setting; example uses `0` |
| `ROUTER_TIMEOUT_SECONDS` | 45 seconds; no automatic routing retry |
| `ROUTER_MAX_OUTPUT_TOKENS` | 2500 |
| `ROUTER_ACCEPT_THRESHOLD` / `ROUTER_LOW_THRESHOLD` | `0.75` / `0.45` |
| `ROUTER_HANDOFF_AFTER` / `ROUTER_MAX_UNCLEAR_TURNS` | Two very low-confidence turns / three unresolved clarifications |
| `BACKEND_HOST` / `BACKEND_PORT` | Native defaults `127.0.0.1:8000`; Docker overrides host to `0.0.0.0` |
| `FRONTEND_ORIGIN` | `http://localhost:5173`; voice also accepts the loopback frontend origin |
| `STARTER_KIT_PATH` | Native `data/starter_kit`; Docker `/app/data/starter_kit` |
| `ENABLE_DEV_STAND` | Optional `/dev` text debugger, off by default |

Frontend defaults to same-origin `/api` and `/health` proxying. Its optional `frontend/.env.example` uses `VITE_API_BASE_URL` and `VITE_USE_MOCK_AGENT`. Mock replies are explicitly labelled and available only in Vite development mode; production Docker uses the real backend.

## API and voice

`GET /health` confirms startup and loaded dataset counts; it does not test OpenAI availability.

`POST /api/message` accepts `{ "session_id": "a-stable-id", "text": "..." }`. Reuse the ID across turns. It returns `response_text`, `routing`, `state`, `trace` and `conversation_status`. One request is one user turn and one routing call. Terminal sessions reject further turns with 409; reset creates a new session. Invalid input is 422, missing model/key 503, provider outage 502 and timeout 504.

Voice WebSocket: `ws://127.0.0.1:5173/api/v1/voice`. Start with a UUID `session_id`, 24 kHz mono PCM16, then send binary frames. Only `utterance.final` reaches Agent Core; partial text remains in voice diagnostics. See [the streaming protocol](docs/VOICE_STREAMING_CONTRACT.md).

The runtime stops capture before routing/TTS. Normal playback resumes listening; `handoff` and `ended` keep it stopped. Reset invalidates stale callbacks. Browser TTS waits for playback completion and bounds stalled playback. Installed Russian/Kazakh voices determine audible language quality; the browser default is used when a matching voice is absent.

The supervisor panel displays the returned transcript, scenarios/confidence, alternatives, concise reason, slots, active/pending/stack context, clarification, actions, status and timings. It does not calculate routing or display hidden chain-of-thought.

## Native development

Tested with Python 3.13 and Node 24.13. Run from the repository root:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -c backend/requirements.lock -e './backend[dev,voice]'
./.venv/Scripts/python.exe -m app.main
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Stop the native services before starting Docker on the same ports.

## Verification

```powershell
./.venv/Scripts/python.exe -m pytest backend/tests -q --basetemp=work/pytest-check
./.venv/Scripts/python.exe -m ruff check backend/app backend/tests
./.venv/Scripts/python.exe -m ruff format --check backend/app backend/tests
./.venv/Scripts/python.exe -X utf8 -m app.evaluation --check-data
./.venv/Scripts/python.exe -X utf8 -m app.evaluation --run --output work/evals/new-run.json --concurrency 2 --min-interval-seconds 1 --continue-on-error
./.venv/Scripts/python.exe -X utf8 scripts/stage1_smoke.py
```

Live evaluation and API smoke call OpenAI. Evaluation output must be a new path; all failed calls count as wrong. In `frontend`:

```powershell
npm run typecheck
npm run build
node --experimental-transform-types --test tests/*.test.mjs
```

Current evidence and limitations are in [Stage 1 validation](docs/STAGE1_VALIDATION.md). Offline fixtures establish contract/state behavior, not model accuracy.

## Demo flows

Start a conversation. Uncheck «Голосовой ввод» for text-only testing with the same runtime and browser TTS.

1. RU: «Я оплатил страховку, но полис не появился.» — collects payment details.
2. KK: «Маған саяхат сақтандыруы керек.» then «Екі аптаға.» — same travel scenario and session.
3. Mixed: «Маған полис керек, сколько это стоит?» — clarifies the product.
4. «Хочу продлить ОГПО и добавить туда сына.» — retains renewal and driver addition.
5. «У меня проблема с полисом.» — asks a targeted question.
6. «Рассчитайте КАСКО: машина 2024 года, стоимость 10000000 тенге.» — source quote 400000 тенге; conversation remains active.
7. «Соедините меня с оператором.» — friendly handoff and stopped listening.
8. Reset, then «Спасибо, до свидания.» — ended and stopped listening.

For real microphone testing, allow microphone access and speak an insurance question; wait for the reply and listening to resume. Then request an operator and check that listening stays stopped. Reset and repeat with goodbye. Voice diagnostics also accept a WAV/audio fixture.

## Troubleshooting and limits

- Docker cannot connect: start Docker Desktop's Linux engine. A Docker Hub TLS/network timeout is a build/download problem; retry after connectivity returns.
- Ports occupied: stop the native backend/Vite processes before starting Compose.
- Health is green but a request fails: verify the local key/model and outbound OpenAI connectivity. No simulated reply replaces a provider outage.
- No speech/audio: check microphone permission, installed TTS voices and the voice diagnostics. The voice image includes local Silero VAD; streaming STT still needs OpenAI connectivity.
- A new `.env` value needs backend recreation. Do not print the full expanded Compose configuration because it contains runtime secrets.
- Conversation state is bounded, in-memory and single-process. There is no authentication or production insurer integration; keep this stand local.
- Routing is measured, not perfect. Consult the validation report for actual confusion pairs and invalid-output counts.

Architecture/navigation: [PROJECT_MAP](docs/PROJECT_MAP.md), [ARCHITECTURE](docs/ARCHITECTURE.md), [INTEGRATION](docs/INTEGRATION.md). The older three-hour implementation plan and earlier evaluation reports are historical references.
