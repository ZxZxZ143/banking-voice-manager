# Banking Voice Platform

Modular conversational platform for Russian, Kazakh and mixed speech. Insurance Manager, three outbound sales campaigns and Fraud & Security share sessions, streaming transcription, browser speech synthesis and supervisor traces. Each assistant owns its isolated business context. Shared Risk Intelligence adds advisory safety guidance without switching assistants. Insurance separates Router, Decision Policy, grounded business logic and a pack-local LLM Conversation Composer.

Insurance uses the supplied **fictional Saqta Insurance** snapshot. The outbound bots use eight synthetic **Merei Demo Bank** products: three deposits, three debit/payment cards and two loans. Both catalogs have reference date **2026-10-01**. Security guidance is a synthetic demo policy dated **2026-10-02**. A full Loan Consultant remains unimplemented; the loan sales campaign only explains catalog terms and records interest.

`ScenarioRegistry` selects the default Insurance Manager for a new session; later turns
continue the active pack. The UI selector opens Product immediately during listening and applies Insurance on the next request, preserving
history and session ID. Assistants change only through explicit UI/API selection.
Out-of-domain questions never invoke or forward to another pack. Insurance briefly answers
small talk and identity enquiries, explains its scope for unrelated/banking questions, and
retains the current insurance goal. Suspended packs resume their own context and result.
See [the architecture](docs/ARCHITECTURE.md).

## What works

- Insurance expected fields now configure streaming STT by type, with deterministic
  RU/KK/mixed identifiers and one conditional audio second pass. Region `ноль два`
  maps to Almaty pricing; 01 to Astana, 03–20 to other. Recognition repair is bounded
  separately from lookup memory. Synthetic canonical accuracy was 62% versus balanced
  43%; five wrong accepted plates leave the production precision gate unmet.
  See [structured speech evidence](docs/STRUCTURED_SPEECH_RECOGNITION_VALIDATION.md).
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

- Product starts with a branded Merei Demo Bank greeting before listening. Currency and
  amounts are understood and spoken naturally: «50 тысяч тенге», «100 долларов США».
  Full conditions remain available in a separate disclosure.
- Insurance also starts with an assistant-only Saqta Insurance greeting before listening.
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

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/show_demo_profile.py
```

Do not publish this command's personal phone output. It prints no API key or unrelated
clients. Literal phones are removed from Router input; requested identifiers are parsed
locally. Composer and supervisor traces mask identifiers too. Voice uses external STT.

After an unknown valid identifier, Insurance offers one alternative lookup. A correction
can use that second lookup; two unsuccessful attempts lead to useful context collection
and specialist handoff for identity-dependent work. General knowledge/quotes stay available.

`tools/capabilities.py` declares actual grounded read-only support. Unavailable writes and
delivery actions collect the scenario's useful required fields, perform available checks,
then hand off with a safe `manager_summary` (field/action names, no identifier values).
The UI supervisor panel shows that summary. No policy, claim, callback or SMS is fabricated.

## Environment

| Variable | Meaning |
|---|---|
| `OPENAI_API_KEY` | Server-only local secret; required for live routing/STT |
| `OPENAI_ROUTER_MODEL` | Explicit structured-output model; measured with `gpt-4.1-mini` |
| `OPENAI_RESPONSE_MODEL` | Optional Insurance Composer model; blank reuses Router model |
| `DEMO_TEST_PHONE` | Optional personal phone for a runtime-only fictional Insurance profile; keep in ignored `.env` |
| `ROUTER_TEMPERATURE` | Optional model setting; example uses `0` |
| `ROUTER_TIMEOUT_SECONDS` | 45 seconds; no automatic routing retry |
| `RISK_TIMEOUT_SECONDS` | 8 seconds by default; one tool-free call, no retry |
| `ROUTER_MAX_OUTPUT_TOKENS` | 2500 |
| `ROUTER_ACCEPT_THRESHOLD` / `ROUTER_LOW_THRESHOLD` | `0.75` / `0.45` |
| `ROUTER_HANDOFF_AFTER` / `ROUTER_MAX_UNCLEAR_TURNS` | Two very low-confidence turns / three unresolved clarifications |
| `BACKEND_HOST` / `BACKEND_PORT` | Native defaults `127.0.0.1:8000`; Docker overrides host to `0.0.0.0` |
| `FRONTEND_ORIGIN` | `http://localhost:5173`; voice also accepts the loopback frontend origin |
| `STARTER_KIT_PATH` | Native `data/starter_kit`; Docker `/app/data/starter_kit` |
| `PRODUCT_CATALOG_PATH` | Native `data/product_promoter/catalog.json`; Docker `/app/data/product_promoter/catalog.json` |
| `SECURITY_POLICY_PATH` | Native `data/security/policy.json`; Docker `/app/data/security/policy.json` |
| `ENABLE_DEV_STAND` | Optional `/dev` text debugger, off by default |

Frontend defaults to same-origin `/api` and `/health` proxying. Its optional `frontend/.env.example` uses `VITE_API_BASE_URL` and `VITE_USE_MOCK_AGENT`. Mock replies are explicitly labelled and available only in Vite development mode; production Docker uses the real backend.

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
./.venv/Scripts/python.exe -X utf8 scripts/stage3_smoke.py --output work/new-stage3-e2e.json
./.venv/Scripts/python.exe -X utf8 scripts/evaluate_product_promoter.py --output work/evals/new-product-run.json
./.venv/Scripts/python.exe -X utf8 scripts/evaluate_insurance_conversation.py --output work/evals/new-dialogue-run.json
./.venv/Scripts/python.exe -X utf8 scripts/evaluate_insurance_conversation.py --dataset data/insurance_conversation/completion_cases.json --output work/evals/new-completion-run.json
./.venv/Scripts/python.exe -X utf8 scripts/evaluate_fraud_risk.py --output work/evals/new-fraud-risk.json
./.venv/Scripts/python.exe -X utf8 scripts/stage4_risk_smoke.py --output work/new-stage4-state.json
./.venv/Scripts/python.exe -X utf8 scripts/stage3_1_voice_smoke.py --audio-directory work/voice-stage31 --output work/new-stage31-voice.json
```

Live evaluation and API smoke call OpenAI. Evaluation output must be a new path; all failed calls count as wrong. In `frontend`:

The voice smoke expects `voice-phone.wav`, `voice-iin.wav` and `voice-existing.wav`
in the supplied directory: synthetic/test audio, PCM16 mono at 24 kHz. Audio evidence stays
in ignored `work/`; it is not distributed with the repository.

```powershell
npm run typecheck
npm run build
node --experimental-transform-types --test tests/*.test.mjs
```

Stage 4 results, measured timeouts, advisory limitations and the presenter sequence are in
[Fraud/Risk validation](docs/STAGE4_FRAUD_RISK_VALIDATION.md). For saved early evaluation
artifacts, `evaluate_fraud_risk.py --rescore INPUT --output NEW_OUTPUT` recomputes unavailable
assessments as unknown without making model calls. New runs apply that rule directly.
Stage 3.2 results are in [Manager validation](docs/STAGE3_2_MANAGER_VALIDATION.md).
Current results and limitations are in
[Completion/context validation](docs/CONVERSATION_COMPLETION_VALIDATION.md).
Earlier [Conversation validation](docs/STAGE3_1_CONVERSATION_VALIDATION.md) covers Stage 3.1;
foundation evidence is in
[Stage 3 validation](docs/STAGE3_VALIDATION.md),
with the architecture baseline in [Stage 2 validation](docs/STAGE2_VALIDATION.md)
and the original baseline retained in [Stage 1 validation](docs/STAGE1_VALIDATION.md).
Offline fixtures establish contract/state behavior, not model accuracy.

## Demo flows

Start a conversation. Uncheck «Голосовой ввод» for text-only testing with the same runtime and browser TTS.

Before Start select «Продажа депозита». The bot names Merei Demo Bank and offers a deposit
without asking the customer to choose a category. Answer «Расскажите о ставке», then
«Как его открыть?»; only explicit application interest produces a local sales lead.
For refusal testing, answer «Сейчас неинтересно», then «Нет, я уверен»: one follow-up, then
the call ends. Reset before choosing «Продажа карты» or «Продажа кредита». An operator can
explicitly switch to Insurance; customer speech never changes the assigned campaign.
An operator request still answers **«Конечно, передаю диалог оператору.»**

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


## Finance Supervisor Dashboard

Stage 5B integrates the teammate Veyra dashboard with persistent SQLite analytics:
Overview, recent voice sessions, Sessions/detail, Risk & Fraud, Anomalies, Journeys and
the current Conversation Demo. Startup remains `docker compose up --build`; open
`http://127.0.0.1:5173`. Populate its actual Docker volume in PowerShell:

```powershell
Get-Content -Raw scripts/seed_analytics_demo.py | docker compose exec -T backend python - --with-anomaly
```

The original 640-event seed remains compatible. The optional extension creates hourly
baseline/current patterns, all explicitly labelled synthetic_demo. Runtime data is separate;
source filters and badges make the scope visible. Persisted analytics survives backend
restart and Compose down/up without `-v`. Conversation state remains in memory.
The dashboard does not restore private transcripts, identifiers, provider metadata or
free-text risk reasoning; excluded latency metrics remain unavailable. Anomalies are
deterministic advisory volume increases with cold-start protection, without model calls.

Runbook: [FINANCE_DASHBOARD](docs/FINANCE_DASHBOARD.md). Final API:
[ANALYTICS_API_CONTRACT](docs/ANALYTICS_API_CONTRACT.md). Evidence and outstanding checks:
[STAGE5B_DASHBOARD_INTEGRATION_VALIDATION](docs/STAGE5B_DASHBOARD_INTEGRATION_VALIDATION.md).
Frontend checks: `npm test`, `npm run build`, `npm run format:dashboard`.
