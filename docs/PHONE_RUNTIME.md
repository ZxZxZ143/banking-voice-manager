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
a second Agent API, Router or intelligence layer. A real provider is not configured on app
startup, and no phone/debug HTTP endpoint is exposed. To compose the future gateway:

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
No new dependencies, secrets, environment variables, real customers or provider SDKs were
added. The existing server TTS protocol and OpenAI TTS adapter are reused, not replaced.

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
sending another hangup. Handoff/ended Agent replies are played once, then the mock-era phone
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
input boundary. `PcmPassThroughNormalizer` only validates/passes canonical PCM. No mu-law,
A-law, MP3 input decoding, provider packet splitting or 8kHz resampling is claimed.
The next adapter must implement and test any required conversion before feeding frames.

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
schema. All phone events carry channel=phone and metadata.call_id; the start event includes
provider metadata. Supplied scenarios are recorded in original order from trace.scenarios,
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

## Next real-provider feature

Implement one adapter under `backend/app/telephony/providers/`:

1. Authenticate/validate incoming provider callbacks or streams; never expose the bench.
2. Translate start/audio/end/error into the typed TelephonyEvents with stable unique call IDs.
3. Normalize the provider codec/sample rate/framing into canonical PCM with bounded buffering.
4. Bind one application-owned PhoneRuntime using real MessageService and explicit server STT/TTS.
5. Convert SpeechResult audio to the provider format and await actual playback completion;
   mute/discard playback echo, and cancel queued output on hangup/close.
6. Implement idempotent hangup/close, provider disconnect/error handling, and gateway shutdown.
7. Verify live RU/KZ output, timeouts and codec quality; coordinate a genuine operator-transfer
   seam before claiming handoff works.

Provider selection/SDK, live calls, codec conversion, real transfer, persistence, analytics,
journey/anomaly detection, dashboard, streaming TTS and public deployment remain deferred.
No next feature branch is created by this task.
