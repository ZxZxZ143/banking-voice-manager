# Veyra / Banking Voice Platform

Modular conversational platform for Russian, Kazakh and mixed speech. Insurance Manager, three outbound sales campaigns and Fraud & Security share sessions, streaming transcription, backend speech synthesis and supervisor traces. Each assistant owns its isolated business context. Shared Risk Intelligence adds advisory safety guidance without switching assistants. Insurance separates Router, Decision Policy, grounded business logic and a pack-local LLM Conversation Composer.

Insurance uses the supplied **fictional Saqta Insurance** snapshot. The outbound bots use eight synthetic **Merei Demo Bank** products: three deposits, three debit/payment cards and two loans. Both catalogs have reference date **2026-10-01**. Security guidance is a synthetic demo policy dated **2026-10-02**. A full Loan Consultant remains unimplemented; the loan sales campaign only explains catalog terms and records interest.

`ScenarioRegistry` selects Insurance Manager by default; later turns continue the active
pack. The web assistant selector is an operator/demo/developer control for deterministic
testing, not a choice presented to a telephone customer. It opens a selected sales campaign
immediately during listening and applies Insurance on the next request, preserving history
and session ID. Assistants change only through explicit UI/API selection. PhoneRuntime uses
the same backend core with Insurance as its default; automatic cross-assistant switching
and phone campaign assignment/dialing are not implemented by the adapters.
Out-of-domain questions never invoke or forward to another pack. Insurance briefly answers
small talk and identity enquiries, explains its scope for unrelated/banking questions, and
retains the current insurance goal. Suspended packs resume their own context and result.
See [the architecture](docs/ARCHITECTURE.md).

## What works

- Sensitive spoken identifiers require full read-back and explicit confirmation. Natural
  RU/KK partial corrections update only an unambiguous digit/letter/region, then repeat
  the full value. Correction/repair attempts are bounded; keyboard input or specialist
  handoff remains available. A fast STT candidate can start read-back without admission.
  Browser voice prewarms input during Cedar playback, uses adaptive local endpointing and
  a bounded RAM-only near-end buffer with echo protection. See
  [correction, latency and release evidence](docs/VOICE_LATENCY_AND_CORRECTION_VALIDATION.md).
- Expected fields configure RU/KK/mixed normalization. Region `ноль два` maps to Almaty
  pricing; 01 to Astana, 03–20 to other. Earlier synthetic canonical accuracy was 62%;
  ASR errors are why the current [precision gate](docs/STRUCTURED_SPEECH_PRECISION_GATE.md)
  requires confirmation for every sensitive field.
- Product language continuity is application-owned. Explicit «ответь на русском» /
  «қазақша жауап беріңіз» persists and repeats the pending question without advancing sales.
  Browser and phone use the same authorized response language for speech.
- Browser speech uses private backend TTS first, then SpeechSynthesis fallback. Configure
  `TTS_PROVIDER=auto|openai|browser`, `BACKEND_TTS_MODEL` (default `gpt-4o-mini-tts`),
  `BACKEND_TTS_VOICE` (default `cedar`), optional `BACKEND_TTS_VOICE_RU/KK` overrides
  and `BACKEND_TTS_INSTRUCTIONS_RU/KK`. The user's listening preference is cedar;
  feminine presentation has not been approved. Five RU/KK voice comparisons and an
  isolated streaming playback prototype are measured in the validation report.
  OpenAI uses the existing server-only key. No backend provider means browser fallback for
  web and unavailable speech for phone. Local Silero/Piper RU+KK prototypes were measured
  on Windows/Linux but still require human listening before becoming the default.
  See [measured TTS quality and language validation](docs/TTS_QUALITY_VALIDATION.md).

- Stages 5A/5B: privacy-safe structured conversation events persist in SQLite; read-only
  `/api/analytics/events`, `/api/analytics/sessions/{session_id}` and
  `/api/analytics/summary` and additive dashboard APIs support the integrated Finance
  Supervisor Dashboard. `EVENT_DB_PATH` defaults
  to `data/runtime/veyra_events.db`; Docker uses the `analytics_data` named volume.
  Normal `docker compose down`/`up` retains events. Conversation state still resets.
  See the
  [integration contract](docs/ANALYTICS_API_CONTRACT.md) and
  [storage validation](docs/STAGE5A_STORAGE_VALIDATION.md).
  Seed safely with `python scripts/seed_analytics_demo.py` in the installed backend
  environment; `--reset` replaces only synthetic demo events.

- Stage 6 integration: the teammate's PhoneRuntime, Twilio and Vonage adapters call the
  current MessageService and shared Risk, with `voice` events in the same SQLite store.
  Telephony is disabled by default; no provider secrets are needed for web/dashboard startup.
  Offline fixtures are verified; live PSTN remains **pending_credentials**. No outbound
  dial command or real operator transfer is included. See [PhoneRuntime](docs/PHONE_RUNTIME.md),
  [integration validation](docs/STAGE6_TELEPHONY_INTEGRATION_VALIDATION.md) and the
  [future live checklist](docs/STAGE6_LIVE_TELEPHONY_CHECKLIST.md).

- Manually selected `fraud_security`: brief RU/KK security guidance, safe yes/no incident
  questions and `FraudCaseResult` for human review. It never asks for OTP/PIN/CVV/password,
  confirms fraud, blocks accounts or changes transactions.
- Shared Risk Intelligence: a deterministic candidate gate skips the model on ordinary
  turns. A single bounded structured call examines a masked utterance and security-only
  context. A detected concern produces source-based advice while preserving the selected
  sales/Insurance state and result. The UI shows Risk Intelligence separately.
  Model failures are visible as unavailable assessment with precautionary advice where
  applicable. See [Stage 4 validation](docs/STAGE4_FRAUD_RISK_VALIDATION.md).

- Web proactive openings use the shared Kazakh-first, Russian-second greeting:
  «Сәлеметсіз бе! Сізге қалай көмектесе аламын? Здравствуйте! Чем я могу вам помочь?»
  The bot does not ask the customer to choose a language. RU/KK/mixed speech is handled
  dynamically; conversations can switch naturally between Russian and Kazakh, with
  continuity for short replies and persistent explicit Product language preferences.
  Product adds its Merei Demo Bank brand/campaign content after the shared opening. Currency and
  amounts are understood and spoken naturally: «50 тысяч тенге», «100 долларов США».
  Full conditions remain available in a separate disclosure.
- Insurance starts with only the shared bilingual help greeting before listening;
  its replies use the fictional Saqta Insurance catalog.
  Its Composer uses bounded history, the previous question and the authorized next step
  to acknowledge partial answers and ask one useful follow-up. Facts are immutable server
  blocks; only acknowledgement and question wording come from the Composer.
  Valid requested identifiers continue the flow and reset misunderstanding counters.
- Outbound sales: the caller assigns deposit/card/loan before the call. The bot offers the
  assigned product first, gives short direct answers and opening steps, and adapts to explicit
  needs. Full conditions remain in the UI. One soft refusal gets one follow-up; the next ends
  the call. Deterministic matching, comparisons and objections produce `SalesLeadResult`.
  Interest, requested link and callback are
  recorded as demo next actions; no product opens, link sends or callback schedules.
- Pack selector, visible active pack, switch notice, SalesLeadResult view and product/switch
  supervisor fields. Interest completes the lead while keeping conversation active;
  a final refusal ends the global call. New sales campaigns require a reset in the demo UI.
- The existing catalog: 40 insurance scenarios and three system intents. Natural wording, independent multi-intent requests, clarification, topic switching and same-session continuation.
- Source-based quotes for ОГПО, standard КАСКО, travel, property and accident insurance; DMS package information, clinics, documents, payment methods and owned policy/claim/payment lookups.
- Application and servicing flows collect the catalog's required information and transfer the prepared conversation to an operator when an insurer operation is needed.
- Explicit operator request: **«Конечно, передаю диалог оператору.»**, `conversation_status=handoff`. Goodbye produces `ended`. Both preserve history and trace and stop the automatic microphone loop.
- A completed Insurance answer enters `wrap_up` and asks whether more help is needed in RU/KK.
  Acknowledgements keep that offer; declining ends the conversation; a direct new request routes
  immediately. Typed new/existing policy context survives short answers and temporary Risk
  guidance. Scenario slot snapshots prevent old car/trip information from contaminating later requests.
- Invalid structured routing output produces a safe clarification; repeated uncertainty ends in handoff. Provider outages remain visible errors.

Actual policy issuance, renewal, changes, cancellation, SMS/email delivery and contact-center transfer require external integrations. They are never reported as completed here. Identifier lookup against the synthetic snapshot is not real authentication.

## Quick Start — Docker

Requirements: Docker Engine (Docker Desktop with its Linux engine on Windows/macOS),
Docker Compose and Internet access for image/dependency downloads. Live conversations
require an OpenAI API key with access to the configured routing, transcription and backend
TTS models. Startup, analytics reads and offline checks do not require provider credentials.

From the repository root, prepare `.env` once, only if it does not already exist.
macOS/Linux:

```sh
cp -n .env.example .env
```

Windows PowerShell:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
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

## Optional local Insurance demo profile

Add `DEMO_TEST_PHONE` to the ignored local `.env`, then restart the backend. Complete
Kazakhstan international `+7`, domestic `8` and full ten-digit numbers without a country
code are accepted and normalized to `+7`. A shorter suffix still needs the operator/area
code; missing digits are never guessed. No canonical file is
rewritten and no overlay file or extra mount is required; Compose already reads `.env`
at runtime. Blank configuration leaves the canonical backend intact.

The generated client has one active OGPO policy, one successful payment with no issued
policy attached, and one claim under review. Every field except the supplied phone is
fictional. Print only this profile with:

In the installed, activated backend environment:

```sh
python -X utf8 scripts/show_demo_profile.py
```

Do not publish this command's personal phone output. It prints no API key or unrelated
clients. Literal phones are removed from Router input; requested identifiers are parsed
locally. Composer and supervisor traces mask identifiers too. Voice uses external STT.

After an unknown valid identifier, Insurance offers one alternative lookup. A correction
can use that second lookup; two unsuccessful attempts lead to useful context collection
and specialist handoff for identity-dependent work. General knowledge/quotes stay available.

`backend/app/packs/insurance_manager/tools/capabilities.py` declares grounded read-only support. Unavailable writes and
delivery actions collect the scenario's useful required fields, perform available checks,
then hand off with a safe `manager_summary` (field/action names, no identifier values).
The UI supervisor panel shows that summary. No policy, claim, callback or SMS is fabricated.

## Environment

Start with the root [.env.example](.env.example); settings are implemented in
[backend config](backend/app/core/config.py). Keep credentials in ignored local `.env`,
never in frontend settings. These are the main configuration groups:

| Group | Current settings and defaults |
|---|---|
| Core / OpenAI | `OPENAI_API_KEY` (live routing/STT/TTS), `OPENAI_ROUTER_MODEL=gpt-4.1-mini`; optional `OPENAI_RESPONSE_MODEL` falls back to Router. `ROUTER_TEMPERATURE=0`, routing timeout 45 s, Risk timeout 8 s. Thresholds/output limits are in `.env.example`. |
| Speech / STT | `STREAMING_STT_MODEL=gpt-live-transcribe`, `STRUCTURED_STT_MODEL=gpt-transcribe`; native microphone streaming needs the backend `voice` extra (Silero VAD). |
| Speech / TTS | `TTS_PROVIDER=auto\|openai\|browser`, `BACKEND_TTS_MODEL` (default `gpt-4o-mini-tts`), `BACKEND_TTS_VOICE` (default `cedar`); optional `_RU` / `_KK` voice and instruction settings. `PHONE_ENDPOINT_SILENCE_MS=1200` (800–5000) controls phone endpointing. |
| Analytics / SQLite | `EVENT_DB_PATH=data/runtime/veyra_events.db`; Compose overrides it to `/app/data/runtime/veyra_events.db` in `analytics_data`. `ANALYTICS_WINDOW_SECONDS=3600`, `ANALYTICS_BASELINE_WINDOWS=6`, `ANALYTICS_MIN_VOLUME=5`, `ANALYTICS_ANOMALY_MULTIPLIER=3`. Analytics is always wired: there is no analytics enable flag or analytics API token/auth setting in this implementation. |
| Telephony | `TWILIO_ENABLED=false`, `VONAGE_ENABLED=false`; each provider needs its own server credentials/configuration and `PUBLIC_BASE_URL` (HTTPS origin without a path/query). Exact names, signed callbacks and external private-key mounts are in the [live checklist](docs/STAGE6_LIVE_TELEPHONY_CHECKLIST.md). |
| Local runtime / data | `BACKEND_HOST=127.0.0.1`, `BACKEND_PORT=8000`, `FRONTEND_ORIGIN=http://localhost:5173`; data paths `STARTER_KIT_PATH`, `PRODUCT_CATALOG_PATH`, `SECURITY_POLICY_PATH`. Compose overrides host/data paths. `ENABLE_DEV_STAND=false`; optional `DEMO_TEST_PHONE` is private local demo configuration. |
| Frontend demo | [frontend/.env.example](frontend/.env.example): blank `VITE_API_BASE_URL` uses same-origin `/api` and `/health` proxying. `VITE_USE_MOCK_AGENT=false`; labelled fixtures are available only in Vite development, never production Docker. |

Details: [speech protocol](docs/VOICE_STREAMING_CONTRACT.md),
[TTS configuration/evidence](docs/TTS_QUALITY_VALIDATION.md),
[dashboard/data intelligence](docs/FINANCE_DASHBOARD.md),
[analytics API](docs/ANALYTICS_API_CONTRACT.md), [PhoneRuntime](docs/PHONE_RUNTIME.md).

## API and voice

`GET /health` confirms startup and loaded dataset counts; it does not test OpenAI availability.

`POST /api/message` accepts `{ "session_id": "a-stable-id", "text": "..." }` and optional
`scenario_mode=insurance_manager|product_promoter|card_promoter|loan_promoter|fraud_security`. Reuse the ID across turns. Optional `channel=text|voice` defaults to text.
Normal Product turns call their agent once. Normal Insurance turns call Router and Composer.
Automatic natural switching is disabled. Only explicit `scenario_mode` or the UI selector changes the active assistant; the original question is never forwarded.
Policy status is brief: «Сейчас ваш полис действует». An explicit end-date question returns
the recorded date in ordinary words, without a policy number or a generic follow-up offer.

`POST /api/conversation/start` accepts `{session_id, scenario_mode}` and initiates Insurance
or an assigned sales campaign or Fraud & Security with zero model calls and no fabricated customer turn. TTS finishes before listening.
Before an outbound call, the caller's system assigns `product_promoter` (deposit),
`card_promoter` (card) or `loan_promoter` (loan). The local demo offers the same pre-call
operator setting. Customer speech cannot choose another campaign. Target scoring and
actual outbound telephony are external integrations and are not simulated as completed.
The bot offers its product first, explains conditions/opening and adapts to explicit needs.
One soft refusal receives one follow-up; a second refusal ends the call. An explicit request
to stop sales/calls ends it immediately. See [outbound sales validation](docs/OUTBOUND_SALES_VALIDATION.md).

Unregistered packs return 422 before any model call. All responses retain the six base fields:
`session_id`, `response_text`, `routing`, `state`, `trace`, `conversation_status`. Insurance
adds conversation metadata and a Router conversation signal to its existing state/schema.
Public Insurance identifiers, source references and transcripts are masked; actual values
remain in the pack's private business state. Product state exposes `sales_lead` and the
actually displayed catalog records; legacy platform wire variants remain for compatibility and are not emitted by manual-only switching.
An optional `risk` object is additive; an omitted field means no analysis was needed.
`POST /api/security/precaution` returns one source-based safety sentence with zero model
calls and no session mutation. The frontend uses it only on security candidates and
speaks it while the single authoritative `/api/message` request runs. It creates no
additional user/assistant turn; repeated source text is not spoken twice.
Security guidance turns use `routing.kind=security_guidance` and the same safe business
state projection. Fraud returns its own `fraud_case`. OpenAPI declares these variants.
The latest InsuranceResult, SalesLeadResult and FraudCaseResult
remain in their own internal entries. Trace includes pack, mode, lifecycle and safe switch/product metadata.

Voice WebSocket: `ws://127.0.0.1:5173/api/v1/voice`. Start with a UUID `session_id`, 24 kHz mono PCM16, then send binary frames. Only `utterance.final` reaches Agent Core; partial text remains in voice diagnostics. See [the streaming protocol](docs/VOICE_STREAMING_CONTRACT.md).

The runtime stops capture before routing/TTS. Normal playback resumes listening; `handoff` and `ended` keep it stopped. Reset invalidates stale callbacks. Backend audio is currently buffered before browser playback; its measured first chunk is not browser onset. Browser fallback prefers stable Natural/Neural/Online voices within the requested locale and reports missing locale voices. Runtime audio is not stored. Only signed telephony routes may be exposed through a future public tunnel; generic speech, app and analytics APIs stay private.

The supervisor panel displays the returned transcript, scenarios/confidence, alternatives, concise reason, slots, active/pending/stack context, clarification, actions, status and timings. It does not calculate routing or display hidden chain-of-thought.

## Native development

Use Python 3.11+ (the recorded dependency snapshot was tested with Python 3.13) and Node
24 (recorded frontend validation used 24.13). Install them with your preferred installer;
Homebrew is not required. Run from the repository root and prepare/configure `.env` as
in Quick Start. A blank key permits startup/offline checks, not live model or speech calls.

macOS/Linux:

```sh
cp -n .env.example .env
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -c backend/requirements.lock -e './backend[dev,voice]'
python -m app.main
```

Windows PowerShell:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -c backend/requirements.lock -e './backend[dev,voice]'
python -m app.main
```

If PowerShell policy prevents activation, use `./.venv/Scripts/python.exe` in place of
`python`; macOS/Linux can similarly use `./.venv/bin/python` without activation.

In a second terminal on either platform:

```sh
cd frontend
npm install
npm run dev
```

For a clean install from the committed lockfile use `npm ci` instead of `npm install`.
Open [the app](http://127.0.0.1:5173). In another terminal, check backend health:

```sh
# macOS/Linux
curl --fail http://127.0.0.1:8000/health
```

```powershell
# Windows PowerShell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expect `status=ok`, loaded starter-kit counts and `analytics.status=ok`.
Telephony is normally `disabled`. Health confirms local startup/storage, not model access
or live provider reachability. Stop native services before using Docker on the same ports.

## Final technical check

Use the installed backend environment above. In each new check terminal, activate `.venv`
(`. .venv/bin/activate` on macOS/Linux, `.\.venv\Scripts\Activate.ps1` in PowerShell),
or use the explicit Python executable described above. Run from the repository root:

```sh
python -m pytest backend/tests -q
python -m ruff check backend/app backend/tests
python -m ruff format --check backend/app backend/tests
python -X utf8 -m app.evaluation --check-data
```

With backend/frontend running, verify backend and proxied health using `curl --fail` or
`Invoke-RestMethod` at `http://127.0.0.1:8000/health` and
`http://127.0.0.1:5173/health`. Follow the web demo below for live acceptance; green health
alone does not prove a working OpenAI call, microphone transcription or audible TTS.

In a separate terminal:

```sh
cd frontend
npm ci
npm test
npm run typecheck
npm run build
npm run format:dashboard
```

`npm test` is the canonical full frontend suite, including dashboard TS/TSX tests.

### Offline phone / core / analytics checks

From the repository root in the installed backend environment:

```sh
python -X utf8 scripts/smoke_phone_runtime.py
python -X utf8 scripts/smoke_twilio_runtime.py
python -X utf8 scripts/smoke_vonage_runtime.py
python -X utf8 scripts/smoke_stage6_integration.py
```

These are explicitly offline: scripted Agent/STT/TTS/provider fixtures, no paid model
calls, provider credentials or real dialing. The Stage 6 smoke exercises the current
MessageService, Risk, SQLite, analytics APIs and persistence after a fresh application
start, using a temporary database. Fixture success is not STT accuracy, audible speech
quality or live PSTN evidence.

For actual dashboard data, run the seed command for your environment below, then check
Sessions, source badges, Risk & Fraud and Anomalies. Optional live dashboard/restart checks
are documented in the [dashboard runbook](docs/FINANCE_DASHBOARD.md):
`stage5b_dashboard_smoke.py create` requires the running app, a fresh `--with-anomaly` seed,
a new manifest path and a live OpenAI call; `verify` reads the manifest after restart.
They are not part of the credential-free offline gate.

### Optional live evaluations and historical evidence

These evaluations call OpenAI; run only with the configured key/model. Use new output
paths; failed calls count as wrong, never as successful fixture responses.

```sh
python -X utf8 -m app.evaluation --run --output work/evals/new-run.json --concurrency 2 --min-interval-seconds 1 --continue-on-error
python -X utf8 scripts/evaluate_product_promoter.py --output work/evals/new-product-run.json
python -X utf8 scripts/evaluate_insurance_conversation.py --output work/evals/new-dialogue-run.json
python -X utf8 scripts/evaluate_insurance_conversation.py --dataset data/insurance_conversation/completion_cases.json --output work/evals/new-completion-run.json
python -X utf8 scripts/evaluate_fraud_risk.py --output work/evals/new-fraud-risk.json
```

Current behavior/evidence: [completion/context](docs/CONVERSATION_COMPLETION_VALIDATION.md),
[outbound sales](docs/OUTBOUND_SALES_VALIDATION.md),
[Fraud/Risk](docs/STAGE4_FRAUD_RISK_VALIDATION.md),
[segmented identifier capture](docs/SEGMENTED_IDENTIFIER_CAPTURE_VALIDATION.md).

**Historical / legacy validation:** `scripts/stage3_smoke.py` checks superseded natural
assistant switching, campaign and refusal behavior; `scripts/stage3_1_voice_smoke.py`
forwards STT as ordinary text and does not test the current structured receipt → read-back
→ explicit confirmation → accepted normalized identifier flow. Neither is final acceptance
for integrated main. Earlier [Stage 1](docs/STAGE1_VALIDATION.md),
[Stage 2](docs/STAGE2_VALIDATION.md), [Stage 3](docs/STAGE3_VALIDATION.md),
[Stage 3.1](docs/STAGE3_1_CONVERSATION_VALIDATION.md) and
[Manager](docs/STAGE3_2_MANAGER_VALIDATION.md) reports retain their original measured scope.

## Demo flows

1. Open [the app](http://127.0.0.1:5173); it starts on **Overview**.
2. Go to **Conversation Demo**.
3. Select **Insurance Manager** (or the intended assistant/campaign) in «Бот и кампания звонка».
4. For text-only testing, uncheck «Голосовой ввод»; the same session/runtime and TTS remain.
   For voice, allow microphone access and leave it checked.
5. Click **«Начать разговор»**. Wait for the bilingual opener and, with voice enabled,
   listening before speaking. Wait for each complete reply before the next utterance.

Keep continuation tests in one session. Between independent cases click **«Сбросить»**,
select the intended assistant and click **«Начать разговор»** again. Handoff/ended sessions
need reset before another conversation. For an intentional manual switch, say which
assistant you select; customer speech never selects another assistant/campaign. Sales
switches open during listening, whereas Insurance selection applies on the next request.

### Insurance and voice

Run each independent case from a fresh Insurance session:

- RU: «Я оплатил страховку, но полис не появился.» — collects payment details.
- KK continuation: «Маған саяхат сақтандыруы керек.» then «Екі аптаға.» in the same
  session — retains the travel scenario. A later RU answer may naturally change reply language.
- Mixed: «Маған полис керек, сколько это стоит?» — clarifies the insurance product.
- Multi-intent: «Хочу продлить ОГПО и добавить туда сына.» — retains both requests.
- Quote: «Рассчитайте КАСКО: машина 2024 года, стоимость 10000000 тенге.» — source
  quote 400000 тенге; conversation stays active and offers further help.
- In a voice session, provide a requested synthetic identifier. Verify full read-back,
  explicit confirmation before lookup, and repeated full read-back after a correction.
  Recognition/repair is bounded; keyboard input or prepared handoff is the safe fallback.
- «Соедините меня с оператором.» — friendly `handoff` and stopped listening, without a
  real human connection. Reset; «Спасибо, до свидания.» — `ended` and stopped listening.

Voice diagnostics also accept WAV/audio fixtures. Diagnostic transcription alone does
not establish that the current identifier confirmation journey passed.

### Sales campaign

Reset, select **«Продажа депозита»**, then start. After the shared opener the bot names
Merei Demo Bank and offers the assigned deposit without asking for a category.
Answer «Расскажите о ставке», then «Как его открыть?»; explicit application interest
records a local `SalesLeadResult`, not an opened banking product.
In a separate session, answer «Сейчас неинтересно», then «Нет, я уверен»: one follow-up,
then the call ends. Reset before **«Продажа карты»** or **«Продажа кредита»**.

### Risk / Fraud and supervisor verification

In an active Insurance or sales session say **«Мне звонят из банка и просят SMS-код.»**
Use a synthetic incident, never an actual code. Verify safety advice and the separate
Risk Intelligence panel; the active business assistant stays selected. A high risk signal
alone does not force handoff. If assessment fails, the UI must show unavailable analysis
rather than a fabricated successful result.

For the dedicated incident flow, reset, manually select **Fraud & Security** and start.
Repeat the example, then answer the bot's question with the synthetic fact
«Да, я уже сообщил ему код.» Verify the case/review information and policy-required
`handoff`, with listening stopped. Do not equate advisory risk with confirmed fraud.

Note the session ID, then open **Sessions** with source **runtime** (or all sources).
Inspect its detail, journey and safe business/Risk events; check **Risk & Fraud** for an
analyzed signal. A freshly committed voice turn also makes the session eligible for
**Live Calls**. Persisted dashboard detail omits raw transcripts and identifiers.

## Phone / telephony

Twilio and Vonage signed adapters use PhoneRuntime → shared STT → the current
MessageService/packs/Risk → **backend TTS** → provider playback. Phone does not use browser
SpeechSynthesis. It starts listening without invoking the browser's unsolicited opener;
Insurance is the default assistant. Phone campaign selection/outbound dialing is not an
integrated feature. `handoff` prepares human handling and closes the automated flow;
it does not establish a live PSTN operator transfer.

`GET /health` exposes each provider as `disabled`, `unavailable` or `ready`. Disabled is
the default; enabled but incomplete configuration is unavailable. Ready confirms local
composition, not account credit, model access or successful real calling.
**Live Twilio/Vonage PSTN remains NOT RUN / pending_credentials; no new live validation
for final main is claimed.** Use the offline commands in Final technical check above.

Live activation needs provider accounts/credentials, credit where applicable, configured
signed callbacks and a separately provisioned HTTPS/WSS ingress exposing only the
telephony routes. See [PhoneRuntime](docs/PHONE_RUNTIME.md),
[Stage 6 integration evidence](docs/STAGE6_TELEPHONY_INTEGRATION_VALIDATION.md) and the
[separate live activation checklist](docs/STAGE6_LIVE_TELEPHONY_CHECKLIST.md).

## Troubleshooting and limits

- Docker cannot connect: start Docker Desktop's Linux engine. A Docker Hub TLS/network timeout is a build/download problem; retry after connectivity returns.
- Ports occupied: stop the native backend/Vite processes before starting Compose.
- Health is green but a request fails: verify the local key/model and outbound OpenAI connectivity. No simulated reply replaces a provider outage.
- No speech/audio: check microphone permission, installed TTS voices and the voice diagnostics. The voice image includes local Silero VAD; streaming STT still needs OpenAI connectivity.
- A new `.env` value needs backend recreation. Do not print the full expanded Compose configuration because it contains runtime secrets.
- Conversation state is bounded, in-memory and single-process; backend restart loses active
  conversations. SQLite analytics persists separately.
- The assistant selector is a demo/operator control. Live Calls shows recent voice activity,
  not guaranteed provider occupancy. There is no real human PSTN transfer or outbound dialer.
- Live PSTN requires provider credentials/configuration and separate live validation.
  Public production deployment/authentication requires additional hardening; keep the
  unauthenticated app, analytics and generic speech APIs local. Insurer writes remain external.
- Routing is measured, not perfect. Consult the validation report for actual confusion pairs and invalid-output counts.

Architecture/navigation: [PROJECT_MAP](docs/PROJECT_MAP.md), [ARCHITECTURE](docs/ARCHITECTURE.md), [INTEGRATION](docs/INTEGRATION.md). The older three-hour implementation plan and earlier evaluation reports are historical references.


## Finance Supervisor Dashboard

The integrated dashboard includes Overview, Live Calls, Sessions/detail, Risk & Fraud,
Anomalies, Journeys and Conversation Demo. Canonical analytics storage is **SQLite**, not
an in-memory phone store or a cloud database. Data survives backend restart at the same
`EVENT_DB_PATH`. Docker uses the `analytics_data` named volume, retained by ordinary
`docker compose down` / `up` (not `down -v`). Active conversation state remains in memory.

SQLite files are ignored by Git: another developer's local history does not arrive with a
clone. A clean environment creates its own database and has no historical events until
runtime activity or explicit seeding. Native and Docker stores are separate unless you
explicitly configure shared storage.

### Seed the environment you are showing

With Docker running, from the repository root on macOS/Linux:

```sh
cat scripts/seed_analytics_demo.py | docker compose exec -T backend python - --with-anomaly
```

Windows PowerShell:

```powershell
Get-Content -Raw scripts/seed_analytics_demo.py | docker compose exec -T backend python - --with-anomaly
```

For native backend development, from the repository root with `.venv` activated:

```sh
python scripts/seed_analytics_demo.py --with-anomaly
```

The Docker command writes to its configured persistent volume; the native command writes
to the local configured `EVENT_DB_PATH`. Neither calls a model/provider. Optional `--reset`
replaces only `source=synthetic_demo` events, preserving runtime events. `--as-of` accepts
a timezone-aware ISO timestamp for reproducible anomaly fixtures.

The base fixture has **120 sessions / 640 events** dated **2026-10-03 08:00–09:59 UTC**.
`--with-anomaly` adds 24 synthetic sessions / 48 events with six hourly baseline windows
and a current-window pattern (current UTC by default). Repeating the same explicit
`--as-of` is idempotent; rerunning without it adds a fresh pattern. All seed events carry
`synthetic_demo` source badges. Select that source or all sources to inspect seeded data;
use `runtime` for actual conversation activity.

**Live Calls** lists up to 100 voice sessions with activity in the last 30 minutes;
active is a five-minute nonterminal recency heuristic, not live provider occupancy.
Historical fixtures still appear in Sessions/analytics, but eventually leave the recent
window. Run a fresh browser voice conversation (or a separately activated real phone call)
to demonstrate current Live Calls. Anomaly patterns also expire as their rolling window
moves; no alert on old seed data is expected behavior.

Dashboard details/journeys contain safe structured events/results, not private transcripts,
identifiers, provider metadata or free-text risk reasoning. Excluded latency metrics stay
unavailable. Anomalies are deterministic advisory volume increases with cold-start
protection, without model calls or a confirmed-attack claim.

Runbook and data-intelligence policy: [FINANCE_DASHBOARD](docs/FINANCE_DASHBOARD.md).
API: [ANALYTICS_API_CONTRACT](docs/ANALYTICS_API_CONTRACT.md).
Evidence: [STAGE5B_DASHBOARD_INTEGRATION_VALIDATION](docs/STAGE5B_DASHBOARD_INTEGRATION_VALIDATION.md).
