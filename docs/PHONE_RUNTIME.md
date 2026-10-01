# Veyra backend phone runtime

Only **web** and **phone** are supported user channels. Both use the same Agent intelligence.
The current domain data is still the Saqta Insurance demo; finance intelligence is owned by
another workstream and is not implemented by this feature.

```text
Web → browser ConversationRuntime → /api/message → MessageService → browser TTS / UI
Phone → backend telephony adapter → normalization → shared STT → MessageService
                                                        ↓ response
                               caller ← telephony output ← backend TTS

Web ConversationEvents ──┐
                        ├→ shared Analytics/Event API (future)
Phone ConversationEvents┘
```

**Browser TTS and Phone TTS are different output adapters for the same Agent response.**
Phone audio never passes through React or Browser Web Speech API. All new Veyra frontend UI
must use **shadcn/ui** as its primary component/design system, including supervisor, live
call, risk/fraud, anomaly, journey and analytics views. This task adds no UI or UI migration.

## Implementation and composition

`backend/app/telephony/runtime.py` provides a dependency-injected `PhoneRuntime`. It is not
a second Agent API, Router or intelligence layer. FastAPI now composes the Twilio gateway
when `TWILIO_ENABLED=true` and all required settings are present. Unconfigured/disabled
phone endpoints return 503 / reject WS admission while web remains available. Composition:

```python
runtime = PhoneRuntime(
    services.messages,     # existing MessageService from build_services()
    streaming_stt,         # OpenAIStreamingSTT with an explicit server key, or test fixture
    backend_tts,           # existing TTSProvider (e.g. explicitly configured OpenAITTSProvider)
    telephony_provider,    # implements TelephonyProvider
)
await runtime.handle_event(CallStarted(provider_call_id, synthetic_metadata))
# Feed IncomingAudio events; CallEnded and ProviderError terminate only their own call.
# At gateway/application shutdown: await runtime.shutdown()
```

The local bench is explicit mock mode, never a fallback after an HTTP/provider failure.
The Twilio SDK generates TwiML and validates signatures; PyAV provides actual codec/rate
conversion. The existing server TTS protocol and OpenAI TTS adapter are reused. All fixture
identifiers/audio are synthetic; no credentials or real customers are committed.

## Call identity and lifecycle

`ActiveCallRegistry` creates a UUID Agent `session_id` for each new `call_id`. Repeated start
notifications for an active call reuse that exact session and do not duplicate its start
event. Different calls get different IDs. The provider must supply unique, stable call IDs
within its configured runtime; IDs are bounded to 128 characters. Metadata is copied.

`PhoneSession` tracks call_id, session_id, channel=phone, UTC started_at, status, optional
language, provider metadata, last Agent conversation status, and a safe error code.

Normal lifecycle: `active → transcribing → processing → speaking → active`.
Terminal lifecycle: `handoff`, `ended`, `cancelled`, or `error`, then removal from the active
registry. Last Agent status is separate from transport status. Admission occurs before any
await; overlapping finals are rejected rather than queued. Supplied STT item IDs are deduped
within a call (up to 1,000); finals without IDs rely on a source delivering once per utterance.

The runtime is half duplex. Incoming frames received during Agent processing, TTS generation
or outgoing playback are discarded. The provider must acknowledge **playback completion**,
not merely upload/queue acceptance, before `send_audio()` returns. It must drop buffered
playback echo at the source and stop pending output on close. There is no acoustic echo
cancellation or barge-in implementation in this feature.

End/cancel/error first removes the active call, then cancels its STT and turn tasks, hangs up
when locally initiated, and closes provider resources. `CallEnded` releases resources without
sending another hangup. Handoff/ended Agent replies are played once, then the phone
call is hung up and cleaned up. **No real operator transfer is implemented or claimed.**
A provider-specific transfer workflow will need a separate transport implementation later.
Late Agent/TTS results cannot reinsert the call or send new audio. Dependencies must cooperate
with cancellation; a late result from a dependency that suppresses cancellation is discarded.
Provider close is responsible for cancelling audio already queued inside the provider.

Bounds: 100 active calls, 1,000 distinct call IDs per runtime by default. Closed-ID tombstones
prevent a replay from reopening the same physical call. At the total-call budget, new calls
are refused instead of evicting identity mappings. Restart/recreate the runtime to reset this
MVP budget. These mappings and events are process-local; production multi-worker/distributed
call ownership is deferred. Turn deadline is 180s; cleanup waits are bounded (1s per provider
operation/task wait by default). A dependency that ignores cancellation may finish later, but
cannot reopen a call. STT queues hold 16 frames; overflow closes that call with a safe error.

## Shared STT and canonical audio

The existing WebSocket relay was extracted to `backend/app/speech/stt/streaming.py`.
It accepts transport-neutral `StreamInput(audio | finish | cancel)` values and emits the same
ready/activity/partial/commit/final/empty semantics at the browser boundary. Both web and
phone use the same relay, existing Silero `SpeechEndDetector`, OpenAI streaming transcription
configuration, RU/KK languages, and endpointing. The WebSocket URL, input/output contract,
origin guard and connection limits are unchanged. See `VOICE_STREAMING_CONTRACT.md`.

`streaming_provider.py` contains shared configuration/handshake and `OpenAIStreamingSTT`
for backend phone use. Each utterance opens a bounded streaming transcription connection,
as the browser already does. `pause_ms` is 500–5,000 (default 2,500), audio limit 120s,
silence-only limit 15s, final-after-commit deadline 30s, overall STT timeout 150s.
STT is released immediately after final admission; it does not wait for Agent/TTS completion.
Partials and empty utterances never invoke the Agent or create `transcript.final` events.

Canonical audio is defined in `backend/app/speech/audio.py`:

- mono signed **PCM16 little-endian**, **24,000 Hz**;
- nonempty even-length frames up to **4,800 bytes / 100ms**;
- 48,000 bytes per second.

`ProviderAudio → AudioNormalizer.normalize() → canonical PCM → shared STT` is the explicit
input boundary. `PcmPassThroughNormalizer` validates canonical PCM. The Twilio adapter
performs real mu-law decoding and 8kHz → 24kHz resampling before this boundary. A-law and
compressed caller input are unsupported; outbound MP3/WAV decoding is implemented.

## Agent and backend TTS boundaries

`AgentBridge` calls the **same** `MessageService.process(session_id, text)` as `/api/message`,
without loopback HTTP. The channel never supplies routing/risk decisions or prompt logic.
The minimal response envelope requires nonblank response_text and a known existing
conversation_status. Optional session_id is checked if supplied. Risk/routing/state/trace
can be absent, null, partial or additive. Backend MessageResult models are dumped to JSON;
no Agent Core or API response schema is changed.

Reply language uses supplied state.response_language, then routing.response_language,
then the last supplied valid transcript language, with Russian as the adapter fallback.
This is output-adapter selection, not a classifier. Future Core contract should retain explicit
response_language for predictable RU/KZ output; no RiskSignal contract is imposed here.

Existing `TTSProvider.synthesize(text, language)` returns `SpeechResult` bytes, content_type,
requested language and optional first-audio timing. The provider receives this result through
`send_audio`. Its outgoing conversion boundary must accept or explicitly reject the returned
format; the existing OpenAI adapter returns MP3. SpeechRequest caps text at 4,000 characters;
longer Agent replies fail visibly at the phone turn boundary. Long-reply chunking, streaming
playback and live Kazakh voice quality remain unverified/deferred.

## Canonical server events

`backend/app/events/` defines a JSON envelope compatible with the frontend ConversationEvent:
required id/session_id/timestamp/event_type/channel, the same seven event types, and optional
language/text/scenario/action/confidence/status/clarification/handoff/risk/routing/state/trace/
latency/metadata. Risk and other Agent payloads remain JSON values, not a duplicated finance
schema. All phone events carry channel=phone, metadata.call_id and copied provider metadata.
Twilio supplies only provider, call_sid and stream_sid. Supplied scenarios are recorded
in original order from trace.scenarios,
then routing.scenarios or routing.selections. This does not imply policy acceptance/execution.
Clarification/handoff semantics match the frontend; awaiting_user alone implies neither.
Closure includes transport status/reason and preserves any supplied Agent status.

`EventStore` supports append, get_by_session, and list filtered by session/channel/event_type/
limit. `InMemoryEventStore` keeps the latest 5,000 events by append order (including tied or
older timestamps), returns deep copies, and survives call cleanup while referenced. Events
are best effort; store exceptions produce static warnings without provider payloads and do
not fail a conversation. The MVP synchronous store is cheap; a persistent replacement should
move I/O off the turn path. Frontend store is retained. There is no web-event ingestion API,
server dashboard feed, database or analytics consumer yet.

## Local bench and verification

From repository root, after installing `backend[dev]`:

```powershell
./.venv/Scripts/python.exe scripts/smoke_phone_runtime.py
./.venv/Scripts/python.exe -m pytest backend/tests -q
./.venv/Scripts/ruff.exe check backend/app backend/tests scripts/smoke_phone_runtime.py
./.venv/Scripts/ruff.exe format --check backend/app backend/tests scripts/smoke_phone_runtime.py
```

The smoke script uses a fixture Agent, scripted STT, silent 100ms WAV fake TTS, and
MockTelephonyProvider. It exercises normalized audio/manual finish, two final inputs under
one Agent session, captured outgoing audio, ordered events and cleanup. It labels all outputs
MOCK and makes no network calls. Fake TTS is **silent WAV**, not synthesized RU/KZ speech.

Tests include a real MessageService with a scripted Router, phone streaming via the extracted
relay/configuration with fixture upstream/VAD, normalization/limits, lifecycle, event shape/
order/copies, partial Agent replies, half-duplex admission, terminal behavior, failure
isolation, cancellation-resistant late Agent/TTS results and caller cancellation.
Run existing frontend tests, TypeScript and production build as described in PROJECT_MAP.

Verified on 2026-10-01 with bundled Node 24.19.0 and temporary Python 3.12.14 using the
existing locked dependencies: **346 backend tests** (307 existing + 39 new), **37 frontend
tests** (36 existing + 1 new), TypeScript, production Vite build, Ruff check/format, offline
phone smoke bench and `git diff --check` passed. Tests use no live network integrations.

## Twilio inbound provider (implemented, live call unverified)

Production path:

`Phone → Twilio → Connect/Stream → signed WSS → Twilio adapter → mu-law 8kHz decode /
resample → PCM16LE 24kHz → shared STT → existing MessageService → backend OpenAI TTS MP3 →
MP3 decode / mono 8kHz resample / raw mu-law encode → Twilio → caller`.

Core telephony remains provider-neutral. Only web/phone channels exist. Browser TTS stays
web-only; phone audio never uses React or browser speech APIs. Frontend presentation is
unchanged; shadcn/ui remains the required design system.

### Routes and identities

- `POST /api/v1/telephony/twilio/voice`: official SDK signature validation over the configured
  external HTTPS URL and every form field; returns SDK-generated
  `<Response><Connect><Stream url="wss://.../api/v1/telephony/twilio/media"/></Connect><Hangup/></Response>`.
- `WS /api/v1/telephony/twilio/media`: validates `X-Twilio-Signature` before accept, using
  the configured external HTTPS upgrade / WSS URL and documented trailing-slash variants.
  Host and forwarded headers cannot choose signature URLs. Queries are rejected; signatures
  cannot be disabled. TLS is terminated by the production proxy/tunnel.
- A signed webhook admits one CallSid for 120s. A validated start consumes that admission,
  verifies AccountSid, assigns CallSid as physical call ID and StreamSid as socket identity,
  then creates one UUID Agent session. Active duplicate calls, stream swaps and closed-call
  reopen attempts fail safely. Single process only: admission and runtime state are local.
- `connected`, `start`, `media`, `mark`, `stop`, `dtmf` have bounded, typed validation.
  Connected precedes start; subsequent sequence numbers must be contiguous. Stream/account/
  call identity and increasing media chunk/timestamps are checked. DTMF is accepted and
  ignored; keypad scenarios are deferred. Unknown/malformed events close only that socket.
- Stop ends the call; disconnect cancels; protocol/conversion failures record a safe error.
  Runtime shutdown cancels active calls. After the media socket closes, TwiML proceeds to
  Hangup. No REST operator transfer or outbound-call API was added.

### Audio and playback

`providers/twilio_audio.py` uses PyAV's real `pcm_mulaw` decoder and one stateful mono s16
24kHz AudioResampler per listening interval. Validated base64 mu-law packets (≤800 bytes,
100ms) become even PCM frames ≤4,800 bytes for existing STT. Busy input is discarded;
resampler state is reset before listening resumes, avoiding echo retained across replies.
The existing Silero endpoint detector controls utterance finalization. Partials never route.

Real `OpenAITTSProvider` returns MP3 from explicitly configured model/voice. PyAV demuxes
MP3 (also WAV for offline fixtures), decodes, downmixes/resamples to mono 8kHz, and encodes
raw mu-law. Output is bounded to 25MB input / 120s duration, split into ≤800-byte base64
`media` messages with the bound StreamSid. It contains no WAV/container header. Codec work
for outgoing speech runs off the event loop. PyAV wheels bundle FFmpeg libraries; no system
ffmpeg executable is required for the verified macOS wheel.

A unique `reply-<UUID>` mark follows each reply. `send_audio` waits for the matching incoming
mark, not for socket send completion. Wrong, stale or cross-stream marks cannot complete
playback. Clear invalidates pending marks **before** sending the clear event: Twilio's
cleared-mark echoes cannot masquerade as successful playback. Timeout (120s), stop,
disconnect, cancellation and terminal states invalidate work and release stream resources.
Ended/handoff replies play once before terminal cleanup. Handoff is a bot state followed by
hangup, not a live operator transfer. Input during Agent/TTS/playback is dropped: barge-in
is deferred. The server synthesizes a whole reply before playback; streaming TTS is deferred.

Events use the existing seven-type schema/store with safe provider/call_sid/stream_sid
metadata. INFO logs contain SIDs, session UUID, lifecycle, Agent/TTS/turn timings, conversion
failures, marks and clears. They omit raw audio, credentials and transcript/reply text.
The in-memory EventStore does hold transcripts/Agent evidence; it has no public analytics
endpoint and is not persistent. Limits: webhook 16KB/100 fields, WS 8KB, pre-start timeout
10s, no-event timeout 300s, existing 16-frame STT queue, 100 active / 1,000 unique calls.
At the unique-call budget restart the process only after active calls end.

### Live call checklist

**No real Twilio call was tested in this task.** The developer reported a ready number/tunnel and saved settings, but the expected root
`.env` did not exist in the workspace at the readiness check. App startup succeeds with
phone disabled; live verification needs the configuration file visible to this backend.
Offline fixtures validate conversion/protocol mechanics, not live recognition, RU/KK voice
quality, network connectivity or PSTN playback.

1. Install from repository root (PowerShell):

   ```powershell
   python -m venv .venv
   ./.venv/Scripts/python.exe -m pip install -c backend/requirements.lock -e './backend[dev,voice]'
   ```

2. Set these names in ignored root `.env` (never frontend Vite settings):
   `TWILIO_ENABLED=true`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
   `TWILIO_PHONE_NUMBER` (your inbound number; Console metadata, no outbound dialing),
   `OPENAI_API_KEY`, `OPENAI_ROUTER_MODEL`, `BACKEND_TTS_MODEL`, `BACKEND_TTS_VOICE`.
   Choose model/voice supported by your account. No implicit phone TTS default.
3. Expose backend port 8000 with an HTTPS/WSS-capable tunnel or trusted TLS reverse proxy.
   For example `ngrok http 8000` if installed. Set `PUBLIC_BASE_URL` to its exact HTTPS
   origin, with no path/query/credentials. Do not commit the generated URL. Changing the
   tunnel URL requires updating `.env`, restarting the backend and updating Console.
4. Start **one worker**: `./.venv/Scripts/python.exe -m app.main`. The voice extra is required
   for existing Silero endpointing. Check `/health`; verify no `twilio unavailable` warning.
5. Twilio Console → Phone Numbers → your voice-enabled number → Voice Configuration:
   set **A call comes in → Webhook → POST** to
   `https://YOUR_PUBLIC_HOST/api/v1/telephony/twilio/voice`, then save.
   Use credentials matching the number's AccountSid (including subaccount if applicable).
6. Call the Twilio number from an allowed/verified trial caller. Expect `twilio started`
   with CallSid/StreamSid/session_id. There is no opening greeting: speak first, then pause
   about 2.5 seconds to commit the utterance. Try Russian, Kazakh and mixed speech.
7. Expect `phone stt_final` → `phone agent_response` → `phone tts_ready` →
   `twilio audio_sent` → `twilio playback_complete` → `phone turn_complete`.
   Caller should hear the spoken existing Agent reply. Speak a second turn after it ends;
   confirm the same session UUID. On goodbye/handoff, final reply precedes clear/closure.
8. Hang up; confirm `twilio closed`, no pending playback, and no further bot turns.
   Record call result and RU/KK audio quality before claiming the live demo passed.

| Symptom | Check |
| --- | --- |
| WS cannot connect | Public TLS/WSS reachability, proxy WS upgrade, tunnel port, route, Twilio debugger; webhook 503 means incomplete/disabled settings. |
| Signature 403 / WS 1008 | Exact public origin, POST URL/no query, matching account auth token, unchanged form fields; never disable validation. |
| No caller audio | Valid start audio/x-mulaw/8000/mono/inbound, base64/frame limits, Twilio media events; expected silence while bot speaks. |
| STT but no Agent reply | Final after pause, router model/key access, `phone_turn_failed`, turn deadline; partials are intentionally ignored. |
| Agent reply but silence | TTS model/voice access, voice extra, MP3 decode/conversion warning, media StreamSid, Twilio debugger. |
| Distorted audio | Raw mu-law mono/8k outbound (no WAV header), input mu-law/8k, PyAV install, phone line/audio quality. |
| Mark never returns | Correct StreamSid/name, socket reader still running, Twilio playback buffer; 120s timeout terminates safely. |
| Unexpected closure | Protocol/order errors, account/call mismatch, STT/provider errors, 4,000-char TTS limit, 180s turn / 300s no-event timeout, registry budget, terminal Agent status. |

### Offline verification

```powershell
./.venv/Scripts/python.exe -m pytest backend/tests -q
./.venv/Scripts/python.exe scripts/smoke_twilio_runtime.py
./.venv/Scripts/python.exe scripts/smoke_phone_runtime.py
./.venv/Scripts/ruff.exe check backend/app backend/tests scripts/smoke_twilio_runtime.py scripts/smoke_phone_runtime.py
./.venv/Scripts/ruff.exe format --check backend/app backend/tests scripts/smoke_twilio_runtime.py scripts/smoke_phone_runtime.py
```

Twilio tests exercise SDK signatures/TwiML/HTTP+WS admission, real known G.711/MP3/WAV
conversion, protocol/order/replay validation, call isolation, final-only routing, two turns
in one session, half duplex, reply marks/clear/timeouts, late Agent/TTS cancellation,
terminal/error cleanup and secret-free logs. Both smoke benches are explicitly MOCK.

Source contracts: [Twilio messages](https://www.twilio.com/docs/voice/media-streams/websocket-messages),
[Connect/Stream](https://www.twilio.com/docs/voice/twiml/stream),
[request validation](https://www.twilio.com/docs/usage/security),
[PyAV audio](https://pyav.org/docs/develop/api/audio.html).

Deferred: operator/PSTN transfer, outbound calls, barge-in, streaming TTS, multi-worker state,
persistence, supervisor authorization/feed, journey/anomaly detection and dashboards.

Verification on macOS / Python 3.12 / Node 24: **406 backend tests (60 new Twilio cases),
37 frontend tests**, TypeScript noEmit, Vite production build, Ruff lint/format,
both offline smoke scripts and git diff --check passed. No live network API was used by tests.
Security review covered signature pinning, account/call/stream isolation, admission/replay,
size/time limits, cancellation/clear semantics and credential/raw-content logging.
