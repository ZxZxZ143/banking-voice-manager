# Frontend integration handoff

The frontend already owns the session ID, conversation loop, text fallback, browser TTS,
and trace display. The integrated MVP connects these two boundaries in real HTTP mode.

Stage 3 keeps voice pack-agnostic and adds two registered packs: `insurance_manager`
and `product_promoter`. Omitted `scenario_mode` defaults to Insurance for a new session;
later turns continue the active pack. Explicit mode switches in the shared locked core.
The six response fields remain; `state`/`routing` are typed per pack, or a minimal platform
confirmation. Insurance retains its flat state and `response_language`. Product exposes
`sales_lead`, shown `products` and complete `product_conditions`. The frontend must not
derive or rewrite business conditions.

The selector shows requested versus active mode, locks during processing/speech, keeps
history/UUID and follows authoritative `trace.scenario_pack_id`. Product selected before
Start calls `POST /api/conversation/start` with session_id/scenario_mode; selecting Product
while listening does the same immediately. Its branded assistant opener plays before
listening, without inserting an empty customer message. Insurance selection applies to the
next normal message. Optional `AgentClient.startScenario` keeps fixture clients compatible.

An out-of-domain turn can return `awaiting_confirmation`; the next yes/no goes through
the ordinary message path. No switches preserve the current private context. Yes processes
the original question in the target. UI/STT/TTS never select a pack semantically.
Trace adds `pack_switch`, product category, shown/selected products, lead status and next
action; absent legacy fields still render. See `ARCHITECTURE.md` for isolation and rollback.

## Voice Input → ConversationRuntime

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
response_language. Browser TTS uses `ru-RU` for `mixed` or an absent hint. The current STT
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
is 60 seconds, above the 45-second per-call and 55-second conditional-selection deadlines.

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
