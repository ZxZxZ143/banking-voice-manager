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
when `TWILIO_ENABLED=true` or `VONAGE_ENABLED=true` and their required settings are present. Unconfigured/disabled
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
The Twilio SDK generates TwiML and validates signatures; the Voice-only Vonage SDK creates
one outbound trial call with application JWT auth. PyAV provides actual codec/rate
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
performs real mu-law decoding and 8kHz → 24kHz resampling before this boundary. Vonage
accepts raw L16 little-endian mono 16kHz and resamples it to the same 24kHz boundary. A-law and
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
Twilio supplies provider, call_sid and stream_sid; Vonage supplies provider and call_uuid. Supplied scenarios are recorded
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

Real `OpenAITTSProvider` returns MP3 from explicitly configured model/voice. The shared
`speech/conversion.py` PyAV helper demuxes MP3 (also WAV for offline fixtures), decodes, downmixes/resamples to mono 8kHz, and encodes
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

## Vonage outbound trial provider (current demo path; live call unverified)

Twilio remains implemented and tested. Vonage adds a separate opt-in gateway/provider;
PhoneRuntime, shared STT/Silero, MessageService, Agent business logic, TTS and events stay
provider-neutral. There is no second Agent or STT engine, public dialer endpoint, frontend
change or new product channel. Exactly web/phone remain; new frontend UI must use shadcn/ui.

Production path: `one explicit CLI call → Vonage application JWT Voice API → developer's
verified signup phone answers → signed answer POST → connect NCCO → signed WSS → binary
L16 16k → real PCM16LE 24k resampling → shared STT final → MessageService → OpenAI TTS MP3 →
real decode/downmix/resample → raw L16 16k binary → Vonage → caller`.

### Trial call trigger and NCCO

`scripts/start_vonage_call.py` calls `telephony/vonage_calls.py` once. It accepts no destination
argument and only dials `VONAGE_TEST_TO_NUMBER`, which must be the developer's verified signup
number. Digits-only international numbers are validated (8–15 digits, no `+`). FROM defaults
to documented trial caller ID `123456789`; `VONAGE_TEST_FROM_NUMBER` may configure it. No
rented virtual number, purchase, account upgrade, payment card or inbound number is needed.
Trial eligibility/reachability must still be confirmed by a genuine call; successful Dashboard
test calling alone does not validate our WebSocket/AI path.

The official lightweight `vonage-voice`/`vonage-http-client` SDK uses application ID and local
RSA private key to sign the outbound request JWT. It never needs/passes API secret to Voice
auth. Timeout is 10s; both HTTP retry configuration and the SDK's separate connection retry
loop are limited to one attempt. An ambiguous failure says to inspect Dashboard before
retrying. One invocation has one phone destination, 45s ringing and a 600s call length cap.
Output contains only acceptance and call UUID. The script does not print private key, token,
API secret or destination. Key files are ignored (`private.key`, `*.pem`); prefer keeping the
actual key outside the checkout. Other `*.key` names are ignored too. Relative key paths resolve against repository root.

The outbound request sets explicit POST answer/event URLs, avoiding dependence on a rented
number. The application's Voice capability and signed webhooks must be enabled. The signed
answer verifies configured FROM/TO and admits Call UUID for 120s before returning:

```json
[
  {
    "action": "connect",
    "endpoint": [
      {
        "type": "websocket",
        "uri": "wss://YOUR_PUBLIC_HOST/api/v1/telephony/vonage/media",
        "content-type": "audio/l16;rate=16000",
        "headers": {"call_uuid": "CALL_UUID_FROM_SIGNED_ANSWER"},
        "authorization": {"type": "vonage"}
      }
    ]
  }
]
```

`headers.call_uuid` is application metadata echoed in the initial `websocket:connected`
JSON, not an undocumented native field. One admitted UUID binds one socket and Agent UUID;
repeated turns reuse it. Active duplicates, closed-call replay and unadmitted connections
are rejected. Admission/closed-ID limits are 100 pending / 1,000 known calls; one worker only.

### Formats and playback

The NCCO reference explicitly lists L16 8/16k; the broader WebSocket guide also lists 24k.
We chose **16kHz**, supported by both, rather than assuming 24k support. No live 24k trial
was performed. Voice WebSocket L16 is **signed little-endian PCM**, mono; despite the MIME
name it is not treated as network-order big-endian PCM.

`providers/vonage_audio.py` uses a per-listening-interval PyAV AudioResampler, 16k → canonical
24k PCM16LE. Input must be nonempty/even and ≤3,200 bytes (100ms); outputs split at the
existing 4,800-byte limit. Input during processing/TTS/playback is dropped, and resampler
state is reset before listening resumes. Existing Silero endpointing and final-only turn
admission remain unchanged.

Shared `speech/conversion.py` decodes actual MP3/WAV containers, downmixes/resamples to mono
s16; Vonage output is 16k raw PCM with **no MP3/WAV headers**. Twilio uses the same bounded
decoder before its unchanged G.711 output encoding. Vonage sends binary 640-byte/20ms
packets, pads only the final packet with silence, and caps replies at 60s to fit the documented
3072-packet buffer. Output conversion runs off the event loop.

After each reply the adapter sends native `{"action":"notify","payload":{"reply_id":"UNIQUE_ID"}}`.
Only the matching `websocket:notify` on that socket completes playback; timeout is 90s.
It does not resume listening on socket-send completion or guessed sleep duration. Native
`clear` cancels pending notifications before transmission. `websocket:cleared` is observed,
not treated as reply completion or allowed to cancel a later reply. DTMF is accepted/ignored.
Ended/handoff replies drain once, then the socket closes; the sole connect NCCO finishes and
normal NCCO execution ends the call. Handoff is not a real operator transfer. Barge-in,
streaming TTS and acoustic echo cancellation remain deferred.

### Public routes and authenticity

- POST `/api/v1/telephony/vonage/answer`: JSON signed callback → validated trial call NCCO.
- POST `/api/v1/telephony/vonage/events`: signed lifecycle events, safe UUID/status logging;
  completed/cancelled/etc close only their call; failures record a provider error. Rejections
  before call creation can omit UUID. Native error events are accepted without raw error logs.
- WS `/api/v1/telephony/vonage/media`: validates Vonage's Authorization Bearer JWT **before**
  accept; then connected/control JSON and binary frames. Disconnect/error/terminal cleanup
  is idempotent. No-event deadline 300s; connection/start deadline 10s; JSON limit 8KB.

Signed callbacks use the account's **Dashboard signature secret**, distinct from API secret.
PyJWT verifies HS256 only, issuer Vonage, API key and optional application ID, iat/jti and
bounded token age (5min / 30s skew); optional exp is verified. If Vonage includes payload_hash,
the documented SHA-256 body hash is checked. Hash presence is optional under HTTPS as in the
official guide. HTTP bodies are capped at 16KB. No signature bypass/dev exception is exposed.
Public URL is a configured HTTPS origin, no path/query/credentials; WSS derives from it.
Host/X-Forwarded headers cannot select destinations. Queries are rejected.

Events reuse channel=phone and metadata.provider=vonage / call_uuid. Agent risk/routing/
state/trace remain optional opaque values. Logs omit raw audio/transcripts, bearer tokens and
keys. There is no new analytics schema, persistent storage or supervisor endpoint.

### Exact live demo procedure (no purchase)

**No real Vonage call was placed or claimed in this task.** Offline mocks prove mechanics,
not trial permission, PSTN routing, network/audio quality or live model output.

1. Copy root `.env.example` to ignored `.env` if it does not already exist; preserve existing
   keys when updating it. Set `VONAGE_ENABLED=true` and normally `TWILIO_ENABLED=false` for
   this demo (both providers can coexist).
2. Set `VONAGE_APPLICATION_ID`, `VONAGE_PRIVATE_KEY_PATH` to the downloaded key,
   `VONAGE_TEST_TO_NUMBER` to the verified signup destination (digits only), and
   `VONAGE_TEST_FROM_NUMBER=123456789`. Do not buy/link a virtual number.
3. Set `VONAGE_API_KEY` and `VONAGE_SIGNATURE_SECRET` from the matching Dashboard account.
   `VONAGE_API_SECRET` is supported as an optional setting but unused by this Voice flow.
   In Application → Voice → advanced features, enable **Use signed webhooks** if not enabled.
4. Reuse `OPENAI_API_KEY`, `OPENAI_ROUTER_MODEL`, `BACKEND_TTS_MODEL`, `BACKEND_TTS_VOICE`.
   Choose account-supported model/voice; live STT needs the existing voice extra.
5. Expose backend port 8000 using an HTTPS/WSS tunnel (e.g. `ngrok http 8000` if installed).
   Set `PUBLIC_BASE_URL` to its HTTPS origin, then start/restart the backend. Tunnel vendor
   is not part of application code. Changing origin requires backend restart before dialing.
6. PowerShell, from repository root:

   ```powershell
   python -m venv .venv
   ./.venv/Scripts/python.exe -m pip install -c backend/requirements.lock -e './backend[dev,voice]'
   ./.venv/Scripts/python.exe -m app.main
   ```

   A second terminal initiates exactly one configured trial call:

   ```powershell
   ./.venv/Scripts/python.exe scripts/start_vonage_call.py
   ```

   macOS in the environment verified in this task:

   ```bash
   cd /Users/sofiyaserbina/PycharmProjects/banking_voice_manager
   /private/tmp/veyra-foundation-venv/bin/python -m app.main
   # Second terminal, same directory:
   /private/tmp/veyra-foundation-venv/bin/python scripts/start_vonage_call.py
   ```

7. Before dialing, check `/health` and confirm no `vonage unavailable` startup warning.
   The script supplies answer/event URLs; Application Dashboard URLs can also use the same
   POST paths. There is no inbound number webhook requirement.
8. Answer on the verified phone. Confirm call UUID → `vonage started` session UUID. There is
   no opening greeting: speak first, pause about 2.5s, then wait through Agent/TTS latency.
9. Expect `phone stt_final` → `phone agent_response` → `phone tts_ready` → `vonage audio_sent`
   → `vonage playback_complete` → `phone turn_complete`; hear the generated existing Agent reply.
10. Speak a second turn after playback. Confirm same session UUID. Hang up and confirm
    `vonage closed` / completed webhook and no remaining bot playback.

| Failure | Check |
| --- | --- |
| CLI credentials/key error | Root .env visibility, enabled flag, application UUID, readable matching RSA key, verified digit-only destination; never paste key contents. |
| Call rejected / outcome unknown | Trial verified signup number, FROM 123456789, application Voice capability, Dashboard call result and credit; inspect before retrying. |
| HTTP 403 / WS denied | Correct account API key/signature secret, signed webhooks enabled, fresh JWT/clock, authorization type vonage; no disable-validation workaround. |
| No WS / 503 answer | Public HTTPS/WSS tunnel and POST paths, backend configuration warning, proxy upgrade, 120s admission; no forwarded-host workaround. |
| No STT final | Binary L16 little-endian/16k, voice extra installed, OpenAI access, genuine speech followed by pause; busy input/partials are deliberately ignored. |
| Agent but no audio | TTS model/voice access, valid MP3/WAV, conversion warning, raw 16k PCM packets; watch playback notify timeout. |
| Distorted sound / long reply | Rate/mono/endian match and no container headers, phone line quality, 60s reply / 4,000-character limits. |
| Unexpected call close | Terminal Agent status, signed failure callback, malformed controls/frames, 180s turn / 90s playback / 300s no-event / 600s call cap. |

Offline check: `python scripts/smoke_vonage_runtime.py` simulates one accepted call → answer
NCCO → binary L16 → scripted STT → fixture Agent → silent WAV TTS → L16 → native notify →
second turn with same session → disconnect/cleanup. It makes no phone/network calls.
The generic and Twilio smoke benches remain working.

Sources: [trial caller identity](https://developer.vonage.com/en/voice/voice-api/getting-started),
[NCCO format/authorization](https://developer.vonage.com/en/voice/voice-api/ncco-reference),
[WebSocket audio/notify](https://developer.vonage.com/en/voice/voice-api/concepts/websockets),
[signed callbacks](https://developer.vonage.com/en/getting-started/concepts/webhooks),
[Voice SDK](https://github.com/Vonage/vonage-python-sdk).

Verified on macOS/Python 3.12/Node 24: **457 backend tests** (51 new Vonage / 60 Twilio),
**37 frontend tests**, TypeScript noEmit, Vite build, Ruff lint/format (114 files), all three
phone smoke scripts, pip check and git diff --check passed. The root .env was absent; no
local Vonage/OpenAI/tunnel configuration or live call was available. Security review covered
JWT claims/body hashes, key handling, bounded audio/notifications, call isolation/replay,
secret-free logs, trial destination restriction and SDK duplicate-request prevention.
