# Frontend integration handoff

The frontend already owns the session ID, conversation loop, text fallback, browser TTS,
and trace display. Attach the future modules at these two boundaries.

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
language through to TTS without detecting it. Browser TTS uses `ru-RU` for `mixed` or an
absent hint. The current STT final event normally has `language: null`, so the bridge omits
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
`npm run test:trace`, `npm run test:integration`, and `npm run test:voice-bridge`.

For this Voice Input integration stage, set `VITE_USE_MOCK_AGENT=true`. The STT backend
still needs `OPENAI_API_KEY`; see `docs/VOICE_STREAMING_CONTRACT.md` for backend startup.

In the browser: Start Conversation, allow the mic, wait for “Говорите”, speak twice and
check that each final transcript creates one message, TTS completes before mic resumes,
and the session ID stays fixed. Reset during capture and verify old callbacks are ignored.
When Agent Core arrives, set mock mode to false and verify `/api/message`, terminal states,
errors and trace timings in HTTP mode.
