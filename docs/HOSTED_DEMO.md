# Hosted Veyra demo

`deploy/Dockerfile` builds the existing Vite application and the real Python backend
into one container. FastAPI serves the built frontend after the existing API routes.
The browser, HTTP APIs, analytics, TTS and voice WebSocket share one HTTPS origin;
no frontend API URL overrides or additional WebSocket proxy are needed.
The original local Docker Compose workflow remains the default.

## Service settings

- Repository build context: root (`.`).
- Dockerfile: `deploy/Dockerfile`.
- Next-deployment branch: `codex/analytics-demo-autoload`, based on
  `origin/deploy/hosted-demo-20261019` at `a844ed8` (includes main `58fa498`).
  Select that branch, or merge it into the existing hosting branch before deploying.
- Health check: `GET /health`.
- One instance and one Python worker: active conversation state and voice recognition
  receipts are process-local. Do not enable horizontal scaling without shared state.
- Container defaults to `0.0.0.0`; platform `PORT` is used when `BACKEND_PORT` is absent.
- On Render, the automatic `RENDER_EXTERNAL_URL` supplies the exact frontend origin
  when `FRONTEND_ORIGIN` is absent. Do not copy the local `.env` into a cloud deployment.
  On another host, set `FRONTEND_ORIGIN` to the exact HTTPS site URL, with no trailing slash.
- Docker enables `STATIC_FRONTEND_DIR=/app/frontend/dist` and includes all canonical
  starter-kit, sales and security data required by the backend.
- Set `ANALYTICS_DEMO_DATA_ENABLED=true` for this demo (also the hosting image default).
  Keep `EVENT_DB_PATH=/app/data/runtime/veyra_events.db`. No pre-deploy command, shell,
  one-off job, external database or build-time secrets are required for demo analytics.

## Runtime secrets and provider configuration

Set secrets through the hosting service's environment settings, never build arguments,
Git, frontend variables, URLs, screenshots or logs:

| Name | Purpose |
|---|---|
| `DEMO_ACCESS_PASSWORD` | Shared demo login password, at least 16 bytes; use a generated value |
| `DEMO_SESSION_SECRET` | Independent random signing secret, at least 32 bytes |
| `OPENAI_API_KEY` | Real server-only provider credential for routing, STT and backend TTS |
| `OPENAI_ROUTER_MODEL` | Explicit model used for routing; current measured configuration is `gpt-4.1-mini` |

Optional provider settings remain those in the main README. Twilio and Vonage stay
disabled unless separately configured. Hosting does not include OpenAI usage credits.
Missing provider credentials produce the existing visible error; no mock bot is enabled.

## Demo access

When both demo secrets are configured, `/login` shows a password form. A successful
same-origin submission issues a 12-hour HMAC-signed HttpOnly, Secure, SameSite=Strict
cookie. The ASGI gate protects HTTP routes, static files and WebSocket handshakes.
State-changing HTTP requests and WebSockets require the configured Origin. Login
attempts are bounded in memory. Rotating either secret invalidates existing cookies.
`POST /logout` from the same origin clears the browser cookie.

Unauthenticated `GET /health` exposes only `{"status":"ok"}` for the host probe.
Authenticated health retains the complete frontend compatibility contract. A health
response proves application startup, not successful access to the OpenAI models.
This is shared access for a demo, not per-user roles or production banking authentication.

## Storage and free hosting limits

The event database remains SQLite at `/app/data/runtime/veyra_events.db`, writable by
the non-root application user. Canonical synthetic data is packaged as backend JSON,
not as a working DB. At startup the application automatically installs/repairs the
versioned 144-session / 688-event demo in the same store used by analytics. It completes
before requests. Five-minute request-driven refresh keeps demo dates recent without
new identities; the UI labels the rolling period. No `scripts/` directory is needed
in the image. `.dockerignore` excludes secrets and DB/WAL/SHM; fixtures are included
as Python package data. `ANALYTICS_DEMO_DATA_ENABLED=false` disables automatic loading
and refresh without deleting stored rows. Routing/STT/TTS remain real integrations.

[Render Free](https://render.com/docs/free) has an ephemeral filesystem, no persistent
disk, no service shell or one-off jobs. Restart, redeploy or spin-down can lose the
working DB. After restart an empty DB automatically regains the packaged demo;
runtime events lost with the filesystem cannot be recovered by this mechanism.
Preservation of runtime rows is guaranteed only during dataset operations in an
existing database, not across filesystem loss. A durable volume or external database
would be required for that separate guarantee. Free Render Postgres has a limited
lifetime and is not introduced here. Active conversations always reset on process
restart. Free-service cold-start latency still applies.

The change preserves the hosting branch's login gate, HTTPS origin handling, single
worker, static assets, voice routes and runtime-only secret configuration. Keep existing
`DEMO_ACCESS_PASSWORD`, `DEMO_SESSION_SECRET`, `OPENAI_API_KEY` and provider/model settings
in Render environment settings. Do not replace them with local development values.

## Focused verification

```bash
npm --prefix frontend ci
npm --prefix frontend run build
python -m pytest backend/tests/integration/test_deployment.py \
  backend/tests/integration/test_demo_data.py \
  backend/tests/integration/test_api.py backend/tests/integration/test_tts_api.py \
  backend/tests/integration/test_voice_stream.py -q
```

After deployment, check the public login and minimal health, unauthenticated API/WS
denial, correct-password login, dashboard health, assistant opener, then a real text
turn and microphone/STT/TTS turn. The latter require a configured provider key.
Before provider calls, confirm 144 synthetic sessions, Journey details, anomalies,
zero demo-only measured latency and zero active demo calls. Actual validation and
Docker restart/recreation evidence: `ANALYTICS_DEMO_VALIDATION.md`.
