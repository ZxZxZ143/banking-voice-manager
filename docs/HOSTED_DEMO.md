# Hosted Veyra demo

`deploy/Dockerfile` builds the existing Vite application and the real Python backend
into one container. FastAPI serves the built frontend after the existing API routes.
The browser, HTTP APIs, analytics, TTS and voice WebSocket share one HTTPS origin;
no frontend API URL overrides or additional WebSocket proxy are needed.
The original local Docker Compose workflow remains the default.

## Service settings

- Repository build context: root (`.`).
- Dockerfile: `deploy/Dockerfile`.
- Health check: `GET /health`.
- One instance and one Python worker: active conversation state and voice recognition
  receipts are process-local. Do not enable horizontal scaling without shared state.
- Container defaults to `0.0.0.0`; platform `PORT` is used when `BACKEND_PORT` is absent.
- On Render, the automatic `RENDER_EXTERNAL_URL` supplies the exact frontend origin
  when `FRONTEND_ORIGIN` is absent. Do not copy the local `.env` into a cloud deployment.
  On another host, set `FRONTEND_ORIGIN` to the exact HTTPS site URL, with no trailing slash.
- Docker enables `STATIC_FRONTEND_DIR=/app/frontend/dist` and includes all canonical
  starter-kit, sales and security data required by the backend.

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

The event database remains SQLite at `/app/data/runtime/veyra_events.db`. Mount a
durable writable volume on `/app/data/runtime` to preserve analytics through recreation.
On a free host with only ephemeral disk, analytics and seed changes can be lost on
restart or redeploy. Active conversations reset on every process restart even when
SQLite is on durable storage. Free hosts can sleep; wake-up latency is platform-dependent.

## Focused verification

```bash
npm --prefix frontend ci
npm --prefix frontend run build
python -m pytest backend/tests/integration/test_deployment.py \
  backend/tests/integration/test_api.py backend/tests/integration/test_tts_api.py \
  backend/tests/integration/test_voice_stream.py -q
```

After deployment, check the public login and minimal health, unauthenticated API/WS
denial, correct-password login, dashboard health, assistant opener, then a real text
turn and microphone/STT/TTS turn. The latter require a configured provider key.
