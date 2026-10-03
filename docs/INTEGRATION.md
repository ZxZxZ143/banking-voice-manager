# Platform integration handoff

Stage 6 adds server phone transports alongside these existing frontend boundaries.
Both gateways use current MessageService and SQLite; no historical phone analytics or
frontend runtime replaces the Stage 5B integration. See the phone contract below.

The frontend owns the session ID, conversation loop, text fallback, browser audio playback,
and trace display. The integrated MVP connects these two boundaries in real HTTP mode.

Stage 4 keeps voice pack-agnostic with five packs: `insurance_manager`, `product_promoter`
(deposit), `card_promoter`, `loan_promoter` and `fraud_security`. Omitted `scenario_mode` defaults to Insurance for a new session;
later turns continue the active pack. Explicit mode switches in the shared locked core.
The six base response fields remain; `risk` is optional/additive. `state`/`routing` are typed
per pack or a security-guidance projection; production uses manual selection only.
Insurance retains its flat state and `response_language`. Product exposes
`sales_lead`, shown `products` and complete `product_conditions`. The frontend must not
derive or rewrite business conditions.

The selector shows requested versus active mode, locks during processing/speech, keeps
history/UUID and follows authoritative `trace.scenario_pack_id`. Product selected before
Start calls `POST /api/conversation/start` with session_id/scenario_mode; selecting Product
while listening does the same immediately. Its branded assistant opener plays before
listening, without inserting an empty customer message. Insurance selection applies to the
next normal message. Optional `AgentClient.startScenario` keeps fixture clients compatible.

An out-of-domain turn stays with its selected assistant. No confirmation or speech forwards
it to another pack. Security advice similarly retains the business state/result and active
assistant. Operator/Fraud selection is explicit through the UI/API; it applies to the next
request, while all packs selected before Start receive their zero-model opener.
UI/STT/TTS never select a pack semantically.
Trace adds `pack_switch`, product category, shown/selected products, lead status and next
action; absent legacy fields still render. See `ARCHITECTURE.md` for isolation and rollback.

## Voice Input → ConversationRuntime

Product language-control responses add `routing.kind="language_control"` and typed
`state.preferred_response_language: "ru" | "kk" | null`. The UI must preserve final
`state.response_language`; model/trace/STT language is evidence, not a TTS override.
Existing runtime response-language precedence already satisfies this rule.

## Private browser speech API

`BackendTtsService` implements the existing `TtsService` contract. POST same-origin
`/api/speech/tts` with `{ "text": "...", "language": "ru" }` (`ru`, `kk`, `mixed`).
Only configured local origins are allowed. No credentials/model/provider settings come
from the browser. Strict limits: 20 KB JSON, 4,000 characters, 8 MB MP3/WAV response;
4000-character normalized text bound; 5 s body / 35 s endpoint deadline. Responses are
`no-store`; validation does not echo submitted speech. Errors: 403 origin, 415 content type,
413 body, 422 validation, 503 unavailable, 502 synthesis failure. Stop/reset aborts fetch
and active audio. The browser falls back on pre-playback errors and timeout; it never
repeats partially played backend speech. Playback completion still gates microphone resume.

Shared `TTS_PROVIDER=auto|openai|browser` selection uses OpenAI when configured, otherwise
browser fallback for web only. Defaults: `gpt-4o-mini-tts` / `cedar`, configurable model,
voice and RU/KK instructions. Silero/Piper TTS are evaluation-only until the listening gate
passes. Display text is unchanged while backend speech text expands rates/money/dates.
See `TTS_QUALITY_VALIDATION.md` for exact measurements, licenses and limitations.
Origin validation is not authentication: public phone ingress must route only signed
telephony endpoints, never this generic speech endpoint.

## Voice input lifecycle

`ConversationPanel` now attaches `VoiceControls` through `voiceRuntimeBridge.ts` before Start.
The runtime starts microphone capture, stops it for each turn and restarts it after TTS.
The one-utterance WebSocket is reopened for each turn with the **same runtime session ID**.
Only `utterance.final` is mapped into a runtime turn:

```ts
runtime.attachVoiceInput(controller); // connected by ConversationPanel
await runtime.startConversation();    // starts VoiceControls microphone capture
await runtime.handleTranscript({ text: 'Сәлеметсіз бе', language: 'kk', stt_ms: 310 }); // bridge callback
```

`language` may be `ru`, `kk`, or `mixed`, and `stt_ms` is optional. The runtime passes the
language as a fallback; TTS first uses Agent Core `state.response_language`, then routing
response_language. Security guard replies use routing first, preserving the business-state
language separately. Browser TTS uses `ru-RU` for `mixed` or an absent hint. The current STT
final event normally has `language: null`, so the bridge omits
the hint. Its `stt_after_commit_ms` becomes `stt_ms` when valid; this excludes endpointing
silence and connection setup. Partials, empty results and errors never create user turns.
Call `runtime.attachVoiceInput(null)` after the controller is stopped/removed.
Text input uses the same turn path through `runtime.sendText(text)`.

## ConversationRuntime → Agent Core

`HttpAgentClient` sends `POST ${VITE_API_BASE_URL}/api/message` (or `/api/message` through
the Vite proxy when the base URL is empty):

```json
{ "session_id": "one-UUID-for-the-conversation", "text": "Сәлеметсіз бе" }
```

The response must have a nonblank `response_text` and one valid `conversation_status`:

```json
{
  "response_text": "Чем я могу помочь?",
  "conversation_status": "awaiting_user",
  "routing": {},
  "state": {},
  "trace": { "latency_ms": { "router": 287 } }
}
```

Valid statuses: `active`, `awaiting_user`, `awaiting_confirmation`, `handoff`, `ended`.
`routing`, `state`, `trace`, and extra fields are optional; the UI handles partial data.
Agent Core owns all routing and business decisions. The backend serves this endpoint;
HTTP mode shows real failures rather than switching to mock replies. The frontend timeout
is 60 seconds. Risk candidates add at most the configured Risk deadline (eight seconds by
default); normal business limits remain unchanged. No selector model is called.

## Stage 4 risk and case views

Risk candidates can receive a source safety cue through `/api/security/precaution` while
the authoritative message is pending. The cue does not append a turn or select a pack.
Browser `Safety first audio` timing measures onset from the user turn; Risk precheck/agent
timings describe the backend call. Already-spoken source text is removed only from the
remaining TTS audio, leaving the canonical response/history intact.

Voice HTTP turns include `channel=voice`; ordinary text retains the existing request shape.
The runtime masks volunteered authentication values before history/API calls. Partials
remain diagnostic-only and their visible text is masked. Authentication collection is
prohibited; ordinary Insurance phone/IIN identification still works.

`risk` includes `analysis_status`, nullable `risk_relevant`, `level`, `signals`,
`recommended_action`, safe enum-derived `reason` and policy `guidance_shown`. Absent risk
means skipped analysis; unavailable analysis must never be displayed as confirmed low
risk. `routing.kind=security_guidance` does not change `trace.scenario_pack_id` or the
retained `state.sales_lead`/Insurance state. The separate Risk panel allowlists levels,
signals and actions; it never calculates a score or reads arbitrary model fields.

`fraud_security` is consultative, not a sales campaign. Its `state.fraud_case` contains
`case_type`, `case_status`, stable facts, safe transaction kind, risk and guidance history,
plus existing status/completed/handoff fields. `FraudCasePanel` only renders this pack's
result. Manual selection keeps session/history but isolated business contexts.
Risk precheck/agent durations are optional `trace.latency_ms` fields.

## Lifecycle and timing

`Listening → Processing → Speaking → Listening`. Processing first stops the voice input,
then sends the request. Speaking awaits browser TTS playback. `handoff` and `ended` stop
the loop after playback. They remain successful terminal states even if playback fails or
times out; queued/stale microphone starts cannot reopen them. Reset stops TTS and listening,
discards stale responses, and creates
a new session ID. The supervisor trace uses Agent Core timing values first; `stt_ms` and
browser TTS first-audio timing fill only missing STT/TTS fields.

## Configuration and final check

Docker serves the same frontend through Nginx; `/api/` proxies HTTP and WebSocket Upgrade
to `backend:8000`, and `/health` is also proxied. Start with `docker compose up --build`.

In `frontend/.env.local`, set `VITE_API_BASE_URL` to the backend origin or leave it empty for
the existing Vite proxy to `127.0.0.1:8000`. Keep `VITE_USE_MOCK_AGENT=false` for real HTTP;
set it to `true` only for labeled fixtures in Vite development. Run from `frontend`:
`npm run dev`, `npm run build`, `npm run test:runtime`, `npm run test:tts`,
`npm run test:trace`, `npm run test:integration`, `npm run test:voice-bridge`, and `npm run test:packs`.

For the full stand keep `VITE_USE_MOCK_AGENT=false`. Backend needs `OPENAI_API_KEY` and
`OPENAI_ROUTER_MODEL`; install the voice extra and see `VOICE_STREAMING_CONTRACT.md` for startup.

In the browser: Start Conversation, allow the mic, wait for “Говорите”, speak twice and
check that each final transcript creates one message, TTS completes before mic resumes,
and the session ID stays fixed. Reset during capture and verify old callbacks are ignored.
Verify `/api/message`, terminal states, errors and trace timings in HTTP mode. Handoff
stops capture but truthfully reports no actual operator connection in this local demo.

## Product opening and currency speech

Select Product Promoter, press Start, and first hear the assistant identify Merei Demo Bank.
The conversation has an assistant-only opening event. Supply «50 тысяч тенге» or «100 долларов»;
normalized preferences use KZT/USD while replies/TTS use human names. Complete numeric
conditions stay in the backend-provided disclosure. A refusal stops the sales pitch;
recorded application interest does not open a real product. Switch to Insurance and back:
one UUID/history remains, but each pack sees only its own preferences/slots/result.

## Stage 5A backend handoff

Dashboard/frontend remains owned separately; Stage 5A adds no analytics UI and does not
merge or adapt teammate frontend files. Existing `/api/` proxy serves the new read-only
`/api/analytics/events`, `/api/analytics/summary` and
`/api/analytics/sessions/{session_id}`. No CORS changes are needed. OpenAPI is available
directly at backend `/openapi.json`; the frontend proxy does not forward that path.

Use `ANALYTICS_API_CONTRACT.md` as the integration specification: typed discriminated
events, enums, source filters, UTC timestamps, pagination (default 100/max 500), empty
states, count semantics, errors and the Stage 5B checklist. Seed with
`python scripts/seed_analytics_demo.py` in the backend environment; source=synthetic_demo
separates fixtures from runtime. Analytics persists through Docker down/up; in-memory
conversation state does not. Use new opaque conversation IDs after backend restart.


## Stage 5B dashboard integration

The teammate Veyra dashboard is now integrated with current persistent analytics. The
historical Stage 5A handoff above remains a record of that stage. See `FINANCE_DASHBOARD.md`
for the final seven-screen contract, same-origin local proxy boundary, unavailable fields,
source filters and polling. `/api/analytics/sessions/{id}/detail` adds richer detail while
the original event-page session endpoint remains backward compatible. No old backend,
PSTN provider metadata, token proxy or analytics LLM is imported.

Normal startup remains `docker compose up --build`. To populate Docker with the compatible
seed and current anomaly pattern in PowerShell:

```powershell
Get-Content -Raw scripts/seed_analytics_demo.py | docker compose exec -T backend python - --with-anomaly
```

The source selector distinguishes runtime/synthetic_demo. Overview shows actual source
counts and demo badges; session rows/details use their explicit source. The mounted
Conversation Demo preserves current Insurance/Sales/Fraud/Risk/voice/TTS functionality.
Check `ANALYTICS_API_CONTRACT.md` and backend OpenAPI for typed aggregate/page contracts;
run `npm test`, `npm run build` and backend pytest for the integration regressions.

## Stage 6 phone integration

The teammate's single PhoneRuntime implementation backs both optional server gateways.
AgentBridge calls the current MessageService directly with an application UUID and
`channel="voice"`. Same selected packs, Insurance lookup-memory and shared Risk; no
provider-side routing or transcript submission API. Partial STT never enters the core.
Backend TTS replies wait for provider mark/notify playback acknowledgement. Browser
ConversationRuntime/TTS stay intact; `/api/v1/voice` now wraps the shared extracted STT relay.

Current EventRecorder/SQLite remain the only production analytics source. Phone call
cleanup finalizes committed sessions idempotently without fabricating a customer turn.
No raw speech/reply/audio/identifiers/provider metadata enter events. Dashboard APIs and
schema are unchanged: voice includes browser and phone, and recent activity is not PSTN
presence. Phone fixture `runtime` events use a temporary DB, not the normal Docker volume.

`/health.telephony` reports each provider as `disabled`, `unavailable` or `ready` with no
config values. Disabled/partial config cannot open media connections; web keeps working.
See `PHONE_RUNTIME.md` for exact callback paths, bounds and protocol. Provenance/offline
evidence: `STAGE6_TELEPHONY_INTEGRATION_VALIDATION.md`. Live gate and future settings:
`STAGE6_LIVE_TELEPHONY_CHECKLIST.md`. No provider credentials, outbound calling command,
public tunnel or real operator transfer is added.
