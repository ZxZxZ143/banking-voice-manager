# Frontend integration handoff

The frontend already owns the session ID, conversation loop, text fallback, browser TTS,
and trace display. Attach the future modules at these two boundaries.

## Voice Input → ConversationRuntime

Attach one controller before starting the conversation. Its methods may return `void` or a
promise; resolve only after listening has actually started or stopped. Send final transcripts:

```ts
runtime.attachVoiceInput(controller); // startListening(), stopListening()
await runtime.startConversation();
await runtime.handleTranscript({ text: 'Сәлеметсіз бе', language: 'kk', stt_ms: 310 });
```

`language` may be `ru`, `kk`, or `mixed`, and `stt_ms` is optional. The runtime passes the
language through to TTS without detecting it. Browser TTS uses `ru-RU` for `mixed` or an
absent hint. Call `runtime.attachVoiceInput(null)` after the controller is stopped/removed.
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
Agent Core owns all routing and business decisions. The existing backend does not yet serve
this endpoint; HTTP mode shows its real error rather than switching to mock replies.

## Lifecycle and timing

`Listening → Processing → Speaking → Listening`. Processing first stops the voice input,
then sends the request. Speaking awaits browser TTS playback. `handoff` and `ended` stop
the loop after playback. Reset stops TTS and listening, discards stale responses, and creates
a new session ID. The supervisor trace uses Agent Core timing values first; `stt_ms` and
browser TTS first-audio timing fill only missing STT/TTS fields.

## Configuration and final check

In `frontend/.env.local`, set `VITE_API_BASE_URL` to the backend origin or leave it empty for
the existing Vite proxy to `127.0.0.1:8000`. Keep `VITE_USE_MOCK_AGENT=false` for real HTTP;
set it to `true` only for labeled fixtures in Vite development. Run from `frontend`:
`npm run dev`, `npm run build`, `npm run test:runtime`, `npm run test:tts`,
`npm run test:trace`, and `npm run test:integration`.

When both teammate modules arrive, attach their controller, verify `/api/message` with the
same session ID on two turns, check `ru`/`kk`/`mixed`, reset during an in-flight turn, and
confirm that `handoff`/`ended` do not restart listening. Check errors and timing in HTTP mode.
