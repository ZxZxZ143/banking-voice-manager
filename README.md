# Veyra — Banking Voice Platform

Modular financial conversational AI platform for Russian, Kazakh and mixed RU/KK speech.

Veyra combines:

- web and phone conversations;
- streaming speech recognition;
- dynamic RU / KK / mixed-language interaction;
- specialized assistants;
- persistent multi-turn context;
- structured speech recognition for sensitive identifiers;
- Fraud & Security and shared Risk Intelligence;
- backend TTS;
- persistent SQLite analytics;
- Customer Intent Journey;
- anomaly detection;
- Finance Supervisor Dashboard;
- real telephony integration through Vonage and Twilio adapters.

Insurance Manager, outbound sales assistants and Fraud & Security share the same application-level conversation infrastructure while preserving isolated business context.

The same `MessageService`, Risk Intelligence and analytics pipeline are used by both **web** and **phone** channels.

---

## Product idea

Veyra is designed for financial contact centers in Kazakhstan.

The main product idea is not only to answer customer requests, but also to transform conversations into structured business intelligence:

```text
Web / Phone
    ↓
Speech / Text
    ↓
Conversational AI
    ↓
Business Assistant
    ↓
Risk Intelligence
    ↓
Response
    ↓
Persistent Events
    ↓
Journey / Risk / Anomalies
    ↓
Finance Supervisor Dashboard
```

---

# What works

## RU / KK / mixed conversations

Veyra supports:

- Russian;
- Kazakh;
- mixed RU / KK speech;
- language switching during the same conversation;
- multi-turn context;
- short RU/KK confirmations and corrections;
- language-preserving wrap-up and closing behavior.

The customer is **not required to choose one language for the entire session**.

### Bilingual proactive opening

Before the customer has spoken, proactive assistants use the same bilingual greeting:

> Сәлеметсіз бе! Сізге қалай көмектесе аламын?  
> Здравствуйте! Чем я могу вам помочь?

Kazakh comes first, then Russian.

After the first customer utterance, Veyra follows the actual language of the dialogue dynamically.

A customer may continue in Kazakh, Russian or mixed RU/KK, and the assistant may switch when the customer's speech naturally switches.

---

## Assistants

The integrated project contains several isolated assistant packs:

- **Insurance Manager**
- **Fraud & Security**
- **Product Promoter**
- **Card Promoter**
- **Loan Promoter**

Each pack owns its own business state.

The web UI exposes a manual assistant selector for deterministic testing and competition demonstration.

This selector is a **demo/developer control**.

A phone customer does not manually choose an assistant through the frontend.

Assistants change only through explicit application/UI selection according to the current integrated contract.

Out-of-domain questions do not silently forward to another assistant.

See [Architecture](docs/ARCHITECTURE.md) and [Project Map](docs/PROJECT_MAP.md).

---

# Insurance Manager

Insurance uses the supplied fictional **Saqta Insurance** snapshot.

The assistant supports:

- natural RU/KK dialogue;
- persistent conversation context;
- new/existing policy context;
- wrap-up;
- normal conversation completion;
- source-grounded insurance explanations;
- policy / claim / payment lookups against synthetic demo data;
- safe human-review handoff where an insurer operation is required.

The current insurance catalog contains:

- 40 insurance scenarios;
- 3 system intents.

Supported topics include:

- ОГПО;
- КАСКО;
- travel insurance;
- property insurance;
- accident insurance;
- DMS package information;
- clinics;
- required documents;
- payment methods;
- policy status;
- claim status;
- payment lookups.

Actual policy issuance, renewal, cancellation, SMS/email delivery and real insurer write operations require external integrations and are never falsely reported as completed.

---

# Outbound Product Promoters

The synthetic **Merei Demo Bank** catalog contains:

- three deposits;
- three debit/payment cards;
- two loans.

The catalog reference date is **2026-10-01**.

The operator/demo configuration assigns the product campaign before the conversation:

- `product_promoter` — deposit;
- `card_promoter` — card;
- `loan_promoter` — loan.

The bot:

- offers the assigned product first;
- answers questions about conditions;
- adapts to explicit customer needs;
- records demo interest;
- records requested link/callback intent;
- handles objections;
- ends after repeated refusal.

A full standalone Loan Consultant is not implemented; the loan campaign explains catalog terms and records customer interest.

Actual product opening, real link delivery and real callback scheduling are outside the competition implementation.

---

# Fraud & Security

Fraud & Security provides brief RU/KK financial safety guidance.

It can ask safe incident questions and produce a `FraudCaseResult` for human review.

It never asks the customer for:

- OTP;
- PIN;
- CVV;
- password.

It does not:

- confirm fraud as a proven fact;
- block accounts;
- cancel transactions;
- modify financial records.

---

# Risk Intelligence

Shared Risk Intelligence runs alongside the selected assistant.

It can detect structured safety concerns while preserving the current assistant context.

Examples:

- suspicious transaction;
- customer denies a payment;
- third party asks for SMS / OTP code;
- credential-recovery risk;
- suspicious banking impersonation;
- unusual security-sensitive behavior.

Risk output is advisory.

Veyra does **not** automatically declare fraud or sanction the customer because of an AI signal.

If the existing deterministic/business review policy requires human handling, the conversation can transition to:

```text
handoff
```

This policy is language-independent.

Equivalent RU and KK situations use the same review rules.

High risk alone does not automatically force handoff unless the configured policy requires review.

See [Fraud/Risk validation](docs/STAGE4_FRAUD_RISK_VALIDATION.md).

---

# Structured speech recognition

Sensitive spoken identifiers use a confirmation-first flow.

Supported structured speech fields include:

- phone number;
- IIN;
- insurance policy number;
- support/request number;
- vehicle registration number;
- region code.

Current flow:

```text
speech
→ STT
→ structured speech receipt
→ read-back
→ explicit confirmation / correction
→ normalization
```

The system supports:

- full read-back;
- RU/KK partial corrections;
- correction of individual digits;
- correction of individual letters;
- region corrections;
- collection of a value in several parts;
- bounded repair attempts.

For phone numbers, a value spoken in domestic `8...` form remains in that form during read-back and is normalized to `+7...` only after confirmation.

Sensitive values are not exposed in public routing context or supervisor traces.

See:

- [Voice latency and correction validation](docs/VOICE_LATENCY_AND_CORRECTION_VALIDATION.md)
- [Structured speech precision gate](docs/STRUCTURED_SPEECH_PRECISION_GATE.md)

---

# TTS

Browser speech uses private backend TTS first.

Current configuration supports:

```text
TTS_PROVIDER=auto|openai|browser
BACKEND_TTS_MODEL=gpt-4o-mini-tts
BACKEND_TTS_VOICE=cedar
```

Optional RU/KK voice and instruction overrides are also supported by the backend configuration.

Current primary integrated voice is **OpenAI Cedar**.

For web:

```text
backend TTS
→ browser playback
→ SpeechSynthesis fallback if needed
```

For phone:

```text
backend TTS
→ provider-specific audio conversion
→ phone media stream
```

Browser TTS is never used as the phone-call speech engine.

See [TTS quality validation](docs/TTS_QUALITY_VALIDATION.md).

---

# Voice runtime

Browser voice uses:

- streaming transcription;
- local Silero VAD;
- adaptive endpointing;
- protected playback/listening lifecycle;
- bounded RAM-only near-end buffering;
- echo protection.

Only final utterances reach Agent Core.

Partial transcripts remain diagnostic only.

The runtime prevents the microphone from listening to the assistant's own speech.

Normal lifecycle:

```text
Listening
→ Processing
→ Speaking
→ Listening
```

`handoff` and `ended` stop the automatic microphone loop.

Reset invalidates stale asynchronous callbacks.

Recoverable Agent failures return the browser runtime to a safe retry state.

---

# Architecture

```text
                    ┌───────────────────┐
                    │      Web UI       │
                    └─────────┬─────────┘
                              │
                    Browser Mic / Text
                              │
                              ▼
                     Streaming STT
                              │
                              │
Phone ── Telephony ── Audio ──┤
                              ▼
                       MessageService
                              │
                 ┌────────────┼────────────┐
                 ▼            ▼            ▼
             Insurance      Fraud       Product
              Manager      & Security   Promoters
                 │            │            │
                 └────────────┼────────────┘
                              ▼
                      Risk Intelligence
                              │
                              ▼
                         Response
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
                  Web TTS            Phone TTS
```

Analytics path:

```text
Conversation Events
        ↓
SQLite Event Store
        ↓
Session Analytics
        ↓
 ┌────────────┬──────────────┬─────────────┐
 ▼            ▼              ▼             ▼
Risk       Journey        Anomalies     Latency
 └────────────┴──────────────┴─────────────┘
                      ↓
          Finance Supervisor Dashboard
```

---

# Product channels

Veyra currently has exactly two user channels:

```text
web
phone
```

There is no separate mobile channel.

---

# Persistent analytics

Privacy-safe structured conversation events persist in SQLite.

Default native database:

```text
data/runtime/veyra_events.db
```

Docker uses the `analytics_data` named volume.

Normal:

```text
docker compose down
docker compose up
```

retains analytics events.

Conversation runtime state itself remains process-local.

Analytics can expose:

- sessions;
- assistant/scenario;
- channel;
- risk;
- handoff;
- clarification;
- completion;
- latency;
- journey;
- anomalies.

A clean clone starts with its own local SQLite database.

Another developer's local database is **not** transferred through Git.

See:

- [Analytics API Contract](docs/ANALYTICS_API_CONTRACT.md)
- [Storage validation](docs/STAGE5A_STORAGE_VALIDATION.md)
- [Data Intelligence](docs/DATA_INTELLIGENCE.md)

---

# Customer Intent Journey

Journey is derived from actual conversation events.

Example:

```text
LOGIN_PROBLEM
→ SUSPICIOUS_TRANSACTION
→ CARD_BLOCK
→ HANDOFF
```

Veyra does not invent a scenario transition that was not observed.

Repeated identical consecutive stages can be collapsed for readability.

Journey is an analytics foundation, not a full enterprise CJM editor.

---

# Anomaly Detection

Anomaly detection is deterministic and explainable.

It does not require another LLM call.

Concept:

```text
historical baseline
vs
current activity
→ abnormal increase
```

Example:

```text
baseline: 4 events/hour
current: 12 events/hour
→ abnormal increase
```

Veyra reports:

- unusual volume;
- abnormal increase;
- deviation from baseline.

It does not automatically claim:

- confirmed fraud campaign;
- confirmed attack;
- confirmed malicious cause.

---

# Finance Supervisor Dashboard

The integrated shadcn/ui dashboard contains:

- **Overview**
- **Live Calls**
- **Sessions**
- **Risk & Fraud**
- **Anomalies**
- **Journeys**
- **Conversation Demo**

The dashboard reads persistent SQLite analytics.

## Live Calls

`Live Calls` is based on recent event activity.

It does not guarantee that a provider socket is currently connected.

Historical demo data may be visible in Sessions while not appearing in Live Calls.

For a Live Calls demo, create fresh voice activity.

---

# Quick Start — Docker

## Requirements

- Docker Desktop with Linux engine;
- Docker Compose;
- Internet access;
- OpenAI API key with access to configured routing, transcription and speech models.

Create `.env` from the example.

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

### macOS / Linux

```bash
cp .env.example .env
```

Set at minimum:

```text
OPENAI_API_KEY
```

Recommended measured Router configuration:

```text
OPENAI_ROUTER_MODEL=gpt-4.1-mini
ROUTER_TEMPERATURE=0
```

Never overwrite an already configured `.env`.

Start:

```bash
docker compose up --build
```

Open:

- Application: http://127.0.0.1:5173
- Backend health: http://127.0.0.1:8000/health
- Proxied health: http://127.0.0.1:5173/health

Useful commands:

```bash
docker compose ps
docker compose logs backend --tail 30
docker compose down
```

The backend runs FastAPI as a non-root user.

The frontend serves the built React application through Nginx and proxies HTTP / voice WebSocket traffic to the backend.

`.env` is supplied at runtime and excluded from Git and Docker build context.

The frontend never receives server API keys.

---

# Native development

Tested with Python 3.13 and Node 24.x.

Run from repository root.

## Windows

```powershell
python -m venv .venv

./.venv/Scripts/python.exe -m pip install -c backend/requirements.lock -e './backend[dev,voice]'

./.venv/Scripts/python.exe -m app.main
```

Frontend:

```powershell
cd frontend
npm ci
npm run dev
```

---

## macOS / Linux

```bash
python3 -m venv .venv

./.venv/bin/python -m pip install -c backend/requirements.lock -e './backend[dev,voice]'

./.venv/bin/python -m app.main
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Verify backend:

```bash
curl http://127.0.0.1:8000/health
```

Example:

```json
{
  "status": "ok",
  "service": "voice-router",
  "analytics": {
    "status": "ok",
    "backend": "sqlite"
  }
}
```

When Vonage is configured:

```json
{
  "telephony": {
    "twilio": "disabled",
    "vonage": "ready"
  }
}
```

Stop native services before using Docker on the same ports.

---

# Environment

The exact supported configuration is documented in `.env.example`.

Never commit `.env`.

## Core / OpenAI

| Variable | Meaning |
|---|---|
| `OPENAI_API_KEY` | Server-only OpenAI secret |
| `OPENAI_ROUTER_MODEL` | Structured routing model; measured with `gpt-4.1-mini` |
| `OPENAI_RESPONSE_MODEL` | Optional response/composer model; blank may reuse Router |
| `ROUTER_TEMPERATURE` | Routing temperature; measured configuration uses `0` |
| `ROUTER_TIMEOUT_SECONDS` | Routing timeout |
| `RISK_TIMEOUT_SECONDS` | Risk Intelligence timeout |
| `ROUTER_MAX_OUTPUT_TOKENS` | Router output budget |
| `ROUTER_ACCEPT_THRESHOLD` | Accept confidence threshold |
| `ROUTER_LOW_THRESHOLD` | Low-confidence threshold |

---

## Speech

Typical speech configuration includes:

```text
TTS_PROVIDER
BACKEND_TTS_MODEL
BACKEND_TTS_VOICE
BACKEND_TTS_VOICE_RU
BACKEND_TTS_VOICE_KK
BACKEND_TTS_INSTRUCTIONS_RU
BACKEND_TTS_INSTRUCTIONS_KK
PHONE_ENDPOINT_SILENCE_MS
```

Streaming STT uses the existing server-only OpenAI configuration.

---

## Analytics / persistence

Important storage setting:

```text
EVENT_DB_PATH
```

Default native path:

```text
data/runtime/veyra_events.db
```

Docker uses its persistent analytics volume.

See:

- `docs/ANALYTICS_API_CONTRACT.md`
- `docs/STAGE5A_STORAGE_VALIDATION.md`
- `docs/FINANCE_DASHBOARD.md`

---

## Telephony

Common:

```text
PUBLIC_BASE_URL
```

### Vonage

Configuration includes:

```text
VONAGE_ENABLED
VONAGE_APPLICATION_ID
VONAGE_PRIVATE_KEY_PATH
VONAGE_API_KEY
VONAGE_API_SECRET
VONAGE_SIGNATURE_SECRET
VONAGE_TEST_FROM_NUMBER
VONAGE_TEST_TO_NUMBER
```

### Twilio

Configuration includes the corresponding account SID, auth token and phone settings.

Provider credentials must remain backend-only.

See:

- [Phone Runtime](docs/PHONE_RUNTIME.md)
- [Stage 6 integration validation](docs/STAGE6_TELEPHONY_INTEGRATION_VALIDATION.md)
- [Stage 6 live checklist](docs/STAGE6_LIVE_TELEPHONY_CHECKLIST.md)

---

# API

## Health

```http
GET /health
```

Confirms:

- service startup;
- starter-kit loading;
- analytics health;
- configured telephony provider state.

It does not guarantee OpenAI availability.

---

## Conversation message

```http
POST /api/message
```

Basic request:

```json
{
  "session_id": "stable-session-id",
  "text": "..."
}
```

Optional fields include:

```text
scenario_mode
channel
```

Supported assistant modes include:

```text
insurance_manager
product_promoter
card_promoter
loan_promoter
fraud_security
```

Reuse the same `session_id` across turns.

Base response retains:

```text
session_id
response_text
routing
state
trace
conversation_status
```

An optional `risk` object is additive.

Missing `risk` means no assessment was required for that turn.

---

## Conversation start

```http
POST /api/conversation/start
```

Conceptual request:

```json
{
  "session_id": "...",
  "scenario_mode": "insurance_manager"
}
```

It creates the assistant-initiated opening without fabricating a customer turn.

TTS finishes before browser listening begins.

---

# Browser voice

Voice WebSocket:

```text
ws://127.0.0.1:5173/api/v1/voice
```

Internal browser audio:

```text
PCM16
mono
24 kHz
```

Only `utterance.final` reaches Agent Core.

Partial transcripts remain diagnostic.

---

# Telephony

The project includes provider-neutral phone runtime plus adapters for:

- Vonage;
- Twilio.

Phone architecture:

```text
PSTN
→ provider
→ signed callback / WSS
→ audio normalization
→ shared STT
→ MessageService
→ Risk
→ backend TTS
→ provider audio
→ caller
```

---

# Live Vonage validation

## Status: LIVE VERIFIED

A real Vonage PSTN call has been successfully completed end-to-end against the integrated Veyra application.

Verified path:

```text
Real phone
→ Vonage Voice API
→ signed answer callback
→ secure WebSocket
→ binary L16 audio
→ shared STT
→ MessageService
→ assistant + Risk Intelligence
→ backend OpenAI TTS
→ audio returned over Vonage
→ real caller
```

The live test confirmed:

- outbound PSTN call reached a real phone;
- call was answered;
- signed answer callback reached Veyra;
- secure WebSocket connected;
- incoming binary audio reached STT;
- final utterances were produced;
- Agent processing completed;
- backend TTS generated speech;
- response audio returned to the real phone;
- playback completion was acknowledged;
- multi-turn conversation worked;
- the same application session was reused across turns;
- call cleanup completed normally.

This is separate from offline fixture validation.

### Current limitations

The repository does not expose unrestricted outbound campaign dialing as a general production feature.

Provider-side call initiation, account billing and authorization remain operational concerns.

`handoff` means human review / handling is required.

It does not automatically establish a PSTN transfer to a real operator.

---

# Twilio

A Twilio adapter is implemented and covered by automated/offline tests.

The current live-verified competition provider is **Vonage**.

Do not claim a live Twilio PSTN test unless one is performed separately.

---

# Phone offline validation

Current deterministic phone smoke tests:

```bash
python -X utf8 scripts/smoke_phone_runtime.py

python -X utf8 scripts/smoke_twilio_runtime.py

python -X utf8 scripts/smoke_vonage_runtime.py

python -X utf8 scripts/smoke_stage6_integration.py
```

These validate internal phone architecture without requiring a paid PSTN call.

Historical voice smoke scripts remain in the repository for regression/reference purposes but are not the canonical validation for the current structured voice-confirmation flow.

---

# Finance Supervisor Dashboard

Dashboard sections:

```text
Overview
Live Calls
Sessions
Risk & Fraud
Anomalies
Journeys
Conversation Demo
```

The application opens on **Overview**.

---

# Web demo

1. Open the application.
2. Go to **Conversation Demo**.
3. Select the intended assistant.
4. Click **Начать разговор**.
5. Use microphone or text input.

For a continuation test, stay in the same session.

For an independent scenario, reset/start a new conversation.

---

## Insurance RU example

```text
У меня уже есть действующий страховой полис.
```

Continue naturally in the same session.

---

## Insurance KK example

```text
Маған саяхат сақтандыруы керек.
```

Then:

```text
Екі аптаға.
```

The same session should continue.

---

## Mixed example

```text
Маған полис керек, сколько это стоит?
```

The assistant should handle mixed language without requiring a language-selection step.

---

## Fraud / Risk example

Select **Fraud & Security**.

Say:

```text
Мне звонят из банка и просят SMS-код.
```

Then:

```text
Я этот код не называла. Что мне делать?
```

Verify:

- Risk Intelligence appears;
- safety guidance is provided;
- review/handoff policy behaves correctly;
- session appears in Dashboard;
- risk information is visible;
- journey is stored.

Kazakh example:

```text
Мен бұл төлемді жасаған жоқпын.
```

Then:

```text
Не істеуім керек?
```

Review/handoff policy must remain equivalent across RU and KK.

---

# Dashboard / SQLite verification

After creating a web conversation:

1. open **Sessions**;
2. find the session;
3. open the detail view;
4. inspect risk/journey;
5. restart backend;
6. refresh Dashboard.

The stored analytics session should remain after restart.

---

# Demo analytics seed

Synthetic demo analytics can be seeded with:

```bash
python scripts/seed_analytics_demo.py
```

Use supported options from the script, including anomaly generation where required.

Demo records are marked as synthetic.

Historical seed events may not appear in **Live Calls**, because Live Calls is based on recent activity rather than all stored sessions.

Native seed writes to the configured local SQLite database.

Docker seed writes into the persistent Docker analytics volume.

Example Docker PowerShell seed:

```powershell
Get-Content -Raw scripts/seed_analytics_demo.py |
  docker compose exec -T backend python - --with-anomaly
```

---

# Final technical check

## Backend

From repository root with the backend environment active:

```bash
python -m pytest backend/tests -q

python -m ruff check backend/app backend/tests

python -m ruff format --check backend/app backend/tests

python -X utf8 -m app.evaluation --check-data
```

Current final integrated validation:

```text
1,350 backend tests passing
```

---

## Frontend

From `frontend/`:

```bash
npm ci

npm test

npm run typecheck

npm run build

npm run format:dashboard
```

Current integrated frontend validation:

```text
106 frontend tests passing
```

`npm test` is the canonical frontend test command.

The old raw Node test invocation is not the canonical full dashboard suite.

---

# Historical validation scripts

Earlier project-stage scripts such as:

```text
stage3_smoke.py
stage3_1_voice_smoke.py
```

remain historical regression artifacts.

They do **not** represent the complete final structured speech or assistant-selection contract and should not be used as the primary release acceptance path.

---

# Optional Insurance demo profile

Set the optional local:

```text
DEMO_TEST_PHONE
```

in ignored `.env`.

The generated profile contains fictional insurance data tied to that runtime test phone.

Do not publish personal phone output.

No API keys or unrelated client data are printed.

---

# Security

- `.env` is excluded from Git;
- private telephony keys must remain outside the repository;
- frontend never receives OpenAI / Vonage / Twilio secrets;
- signed telephony callbacks are validated;
- sensitive identifiers are masked outside private business state;
- raw runtime audio is not stored;
- demo data is synthetic;
- public tunnel exposure should be limited to required telephony callback paths.

Do not expose generic app, analytics or developer endpoints publicly for a competition tunnel unless explicitly required.

Rotate any credential that is accidentally exposed.

---

# Known limitations

The competition version intentionally does not include:

- real automatic PSTN transfer to a human operator;
- unrestricted production outbound campaign dialing;
- advanced phone barge-in;
- distributed/multi-node persistent state;
- production-grade RBAC for the Supervisor Dashboard;
- production public deployment hardening;
- guaranteed provider-socket occupancy semantics in Live Calls.

Conversation runtime state remains process-local.

Persistent analytics are stored in SQLite.

The project is a competition/demo implementation, not a production banking deployment.

---

# Troubleshooting

## Docker cannot connect

Start Docker Desktop / Linux engine.

A Docker Hub network/TLS error is a build/download issue rather than application logic.

---

## Ports occupied

Stop native backend/Vite processes before starting Docker.

---

## Health is green but Agent request fails

Check:

- API key;
- configured model;
- OpenAI connectivity.

No fake provider reply silently replaces a real outage.

---

## No browser speech

Check:

- microphone permission;
- backend TTS configuration;
- browser fallback availability;
- voice diagnostics.

---

## New `.env` value is ignored

Restart/recreate the backend.

Do not print expanded environment configuration because it may expose secrets.

---

## Telephony provider not ready

Check:

```text
/health
```

Provider state may be:

```text
disabled
ready
unavailable
```

Verify local credentials, public URL and provider account configuration.

---

# Documentation

Useful references:

- [Architecture](docs/ARCHITECTURE.md)
- [Project Map](docs/PROJECT_MAP.md)
- [Integration](docs/INTEGRATION.md)
- [Phone Runtime](docs/PHONE_RUNTIME.md)
- [Analytics API Contract](docs/ANALYTICS_API_CONTRACT.md)
- [Finance Dashboard](docs/FINANCE_DASHBOARD.md)
- [Stage 4 Fraud/Risk Validation](docs/STAGE4_FRAUD_RISK_VALIDATION.md)
- [Stage 5A Storage Validation](docs/STAGE5A_STORAGE_VALIDATION.md)
- [Stage 5B Dashboard Validation](docs/STAGE5B_DASHBOARD_INTEGRATION_VALIDATION.md)
- [Stage 6 Telephony Integration Validation](docs/STAGE6_TELEPHONY_INTEGRATION_VALIDATION.md)
- [Stage 6 Live Telephony Checklist](docs/STAGE6_LIVE_TELEPHONY_CHECKLIST.md)
- [Structured Speech Precision Gate](docs/STRUCTURED_SPEECH_PRECISION_GATE.md)
- [Voice Latency and Correction Validation](docs/VOICE_LATENCY_AND_CORRECTION_VALIDATION.md)
- [TTS Quality Validation](docs/TTS_QUALITY_VALIDATION.md)

---

# Competition demo sequence

Recommended short demo:

1. Open **Overview**.
2. Show persistent Dashboard analytics.
3. Open **Conversation Demo**.
4. Start an assistant.
5. Demonstrate the bilingual KK → RU opening.
6. Continue naturally in RU / KK / mixed speech.
7. Demonstrate structured voice input.
8. Demonstrate Fraud & Security.
9. Show Risk Intelligence.
10. Show review / handoff.
11. Open the stored session.
12. Show Customer Intent Journey.
13. Show Anomaly Detection.
14. Show SQLite persistence after restart.
15. Demonstrate or present the **live-verified Vonage phone flow**.

---

Veyra is ready for the competition demo and technical evaluation.
