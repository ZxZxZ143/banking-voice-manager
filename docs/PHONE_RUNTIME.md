# Integrated backend phone runtime — Stage 6

This is a selective integration of the teammate's implementation, most recently at
`642aebf8ab28746644c6109301a5660b1ec9cb4e`, onto Stage 5B main `48da4bb`.
Both providers are **disabled by default**. Live PSTN status: **pending_credentials**.
The inherited outbound trial trigger and its SDK dependencies are intentionally excluded.

The final interaction polish retains phone half-duplex and its existing endpoint setting.
Browser prewarm, near-end buffering and keyboard fallback do not change phone playback.
Shared structured STT now races to a pending full read-back; sensitive values still need
explicit confirmation. RU/KK corrections edit private pending state and read the full
corrected value again. Exhausted phone corrections prepare specialist handoff, with no
business lookup on a recognition failure. See
[voice release validation](VOICE_LATENCY_AND_CORRECTION_VALIDATION.md).
**Twilio LIVE PSTN = NOT RUN / pending_credentials; Vonage LIVE PSTN = NOT RUN / pending_credentials.**

## One application core

```text
Browser → ConversationRuntime → /api/message → current MessageService → shared backend TTS
        → browser audio (SpeechSynthesis fallback)
Phone → signed provider gateway → canonical PCM → shared STT → PhoneRuntime
      → AgentBridge → same current MessageService → backend TTS → provider playback
Both → current EventRecorder → SQLiteEventStore → /api/analytics/* → dashboard
```

`main.py` composes one optional gateway/runtime instance per provider with the same
`services.messages`. There is one PhoneRuntime/AgentBridge implementation, no phone Router,
Risk engine or prompt. The shared registry selects Insurance by default and retains the
selected pack. Pack changes remain explicit application choices, never provider metadata.
Phone starts listening; it does not automatically invoke the browser's assistant opener.

`AgentBridge` calls `process(session_id, text, channel="voice")` directly. It validates the
existing response envelope and matching session ID, retaining additive fields in memory.
`PhoneSession.channel` and persisted analytics use canonical `voice`; there is no public
`phone` enum. Reply language follows current browser semantics: Risk guidance uses routing
language first, other replies use state first, then transcript language/Russian fallback.

## Identity, admission and cleanup

ActiveCallRegistry allocates an opaque application UUID per provider call. Phone numbers
are never identities. Provider CallSid/StreamSid/Vonage UUID remain transport correlation
only; signed callback phone allowlists are not business identity verification.
Repeated active starts reuse the session; closed IDs cannot reopen within that process.

`active → transcribing → processing → speaking → active` is half duplex. Audio/finals
received during processing/TTS/playback are rejected. Final IDs are deduplicated; without
an ID the STT source must deliver one final per capture. There is no barge-in or acoustic
echo cancellation. Providers acknowledge playback, not merely upload completion.

Terminal/error/disconnect invalidates the call before cancelling tasks and closing output.
An ended/handoff reply is played before cleanup; no human is connected by this adapter.
Late Agent/TTS responses cannot send audio or reopen the transport. Dependencies must
cooperate with cancellation. Current MessageService.end_session finalizes an already
committed conversation without adding a turn; existing handoff stays handoff.

| Resource | Bound |
| --- | --- |
| Runtime registry, per provider | 100 active / 1,000 distinct calls per process |
| Final IDs / turns per call | 1,000 IDs; 1,000 turns even when no ID supplied |
| Audio queue | 16 canonical frames |
| Vonage blocked audio admission | 45 seconds; close/capture completion interrupts wait |
| Generic/Twilio full queue | Immediate safe call failure, inherited behavior |
| Turn / STT overall | 180 seconds / 150 seconds |
| STT audio / silence / final wait | 120 seconds / 15 seconds / 30 seconds |
| WebSocket initial / idle receive | 10 seconds / 300 seconds |
| Cleanup operation/task wait | 1 second each by default |
| Pending signed admission | 100 entries / 120 seconds |
| HTTP body / control JSON | 16 KiB / 8 KiB |
| TTS request / decoded container | 4,000 characters / 25 MB input |
| Twilio output / acknowledgement | 120 seconds decoded audio / 120 seconds ack |
| Vonage output / acknowledgement | 60 seconds decoded audio / 90 seconds ack |

At the lifetime call budget new calls are refused rather than evicting replay tombstones.
Restart resets transient ownership; no multi-worker routing or durable replay cache is
implemented. SQLite histories survive restart, but active conversations cannot resume.

## Speech and provider protocols

Browser and both gateways now receive the same configured `speech/tts/factory.py` provider
instance from application startup. `TTS_PROVIDER=auto|openai` uses configured OpenAI;
`browser` or missing backend credentials yields no phone speech provider and enabled
gateways remain unavailable. Phone never uses a silent mock or browser fallback in
production. `BACKEND_TTS_MODEL`, `BACKEND_TTS_VOICE`, and RU/KK delivery instructions remain
server-side configuration. Defaults: `gpt-4o-mini-tts` / `cedar`. Normalization preserves
numeric facts and returns the existing MP3 contract; codecs and acknowledgement flow
are unchanged. Forty generated RU/KK MP3 samples passed both actual conversion adapters.
Silero/Piper TTS are evaluation-only pending listening; this does not change Silero VAD.
Details: `TTS_QUALITY_VALIDATION.md`.

The new private `/api/speech/tts` is for the browser, not a phone webhook. Future public
ingress must expose only signed telephony routes. It must not forward generic app,
analytics or speech routes. Runtime generated audio is memory-only and never persisted.

Canonical audio: signed PCM16 **little-endian**, mono, 24 kHz, even nonempty frames ≤4,800
bytes. The browser relay and OpenAIStreamingSTT share `speech/stt/streaming.py`, Silero VAD
and the existing RU/KK transcription settings. Browser wire/origin/connection guards remain.
Phone pause defaults to 1,200 ms, bounded by `PHONE_ENDPOINT_SILENCE_MS` 800–5,000 ms;
browser pause remains independently configured. STT releases after final admission.

Twilio reuses official SDK TwiML/signature validation. `POST /api/v1/telephony/twilio/voice`
admits a signed account/call and returns Connect/Stream then Hangup. The signed `/media`
WebSocket requires connected/start sequencing and matching account, CallSid, StreamSid.
Inbound raw mu-law 8 kHz decodes/resamples to 24 kHz. Outbound MP3/WAV decodes to mu-law
8 kHz with mark acknowledgement and clear/close isolation. URLs are pinned to configured
HTTPS origin, not forwarded headers.

Vonage reuses signed `POST /api/v1/telephony/vonage/answer`, `/events` and WebSocket `/media`.
It validates HS256 issuer/account/iat/jti and optional application binding. Stage 6 additionally
requires a matching SHA-256 payload hash for HTTP bodies; WebSocket JWT has no HTTP body.
JWT age is limited to 300 seconds with 30-second clock tolerance. No global one-use jti
cache is claimed; call tombstones and stream admission provide process-local replay isolation.
Answer from/to must exactly match configured digit-only `VONAGE_TEST_*_NUMBER` values.
NCCO requests native signed WebSocket authorization. Binary L16 little-endian mono 16 kHz
resamples to 24 kHz; replies use raw L16 16 kHz and notify/clear acknowledgements. Text
controls may interleave with binary frames. The teammate's bounded startup backpressure
fix `5c90895` is retained; see `VONAGE_WEBSOCKET_INVESTIGATION.md`.

PyAV 16.1.0 wheels supply codec libraries on tested Windows/Linux images; no additional
system FFmpeg package was needed. Backend TTS uses the existing OpenAITTSProvider and
never browser SpeechSynthesis. Silent fixture WAVs are not real RU/KK speech synthesis.

## Persistent analytics and privacy

Current MessageService emits conversation/business/Risk events after committing state.
There is no phone EventStore and no historical `app/events` import. EventRecorder maps
only current allowlisted schema fields. Transport closure adds a safe deduplicated terminal
event; an uncommitted/empty call has no fabricated turn or conversation in analytics.
No transcript, assistant response, phone/IIN/authentication value, raw audio, provider ID,
whole state/trace/result or arbitrary provider metadata enters SQLite.

Persistence is best effort: a failure leaves speech successful and health degraded; there
is no durable outbox. Transport finalization has a bounded wait and may be incomplete if
core dependencies ignore cancellation or storage fails. The dashboard renders `voice`
sessions through the existing safe APIs. Recency is a heuristic, not provider presence;
provider identity and latency remain unavailable in persisted analytics.

## Configuration and offline checks

Use the empty names in root `.env.example`. Enabled but incomplete providers report
`unavailable`; disabled providers report `disabled`. HTTP endpoints return 503 and media
upgrades reject admission. Health contains status labels only. Gateway `ready` means local
composition succeeded, not credentials/account/model/live reachability validation.
Vonage additionally requires a readable RSA private key (≥2048 bits, ≤16 KiB) at composition;
the key is not used to dial anything. Keep it outside the repository/build context.

```powershell
./.venv/Scripts/python.exe -m pip install -c backend/requirements.lock -e './backend[dev,voice]'
./.venv/Scripts/python.exe -X utf8 scripts/smoke_phone_runtime.py
./.venv/Scripts/python.exe -X utf8 scripts/smoke_twilio_runtime.py
./.venv/Scripts/python.exe -X utf8 scripts/smoke_vonage_runtime.py
./.venv/Scripts/python.exe -X utf8 scripts/smoke_stage6_integration.py
./.venv/Scripts/python.exe -m pytest backend/tests -q --basetemp=work/stage6-tests
docker compose up --build -d
```

The first three scripts use explicit mock Agent/STT/TTS/provider boundaries. The Stage 6
smoke uses current MessageService, Insurance, shared Risk and SQLite with external model,
STT and silent TTS fixtures. It verifies current analytics APIs and exact history after a
fresh application start. Its `runtime` events are confined to a temporary DB and never
inserted into the persistent demo volume. No fixture is an automatic failure fallback.

See `STAGE6_LIVE_TELEPHONY_CHECKLIST.md` for the later credentials/live gate.

## Structured speech update (2026-10-03)

PhoneRuntime obtains expected-slot context from current MessageService. Twilio/Vonage
still decode to PCM24; shared streaming STT applies context, the deterministic parser
and optional single bounded second pass. No provider-specific parser exists.
OpenAIStreamingSTT.run_with_context adds context/receipts; run-only fixture adapters
remain supported. AgentBridge forwards a receipt to the same voice-channel core turn.

STREAMING_STT_MODEL defaults to gpt-live-transcribe; STRUCTURED_STT_MODEL to gpt-transcribe.
Ordinary delay stays medium; structured delay is high. Prompts contain formats/prefixes
only. PCM keeps the 120-second bound, remains memory-only and clears on final/cancellation.
A valid first candidate skips the second call. Recognition failure does not consume a
business lookup attempt: one RU/KK repair, then an alternative or prepared handoff.
Phone replies never offer keyboard input. Source formats/synthetic IIN policy are unchanged.

BACKEND_TTS_VOICE_RU/KK optionally override BACKEND_TTS_VOICE; unknown/mixed language
retains the legacy choice. Buffered MP3 still feeds existing phone conversion/acknowledgement;
streaming playback remains an isolated browser experiment.

Offline codec→PCM→STT fixture→parser→core tests and all four Stage 6 smokes were run.
Provider admission, SQLite and Risk remain covered. The 112-case synthetic cloud STT
benchmark is transport-neutral, not a PSTN test. Five wrong accepted plates and low mixed
accuracy leave the production precision gate unmet. Live PSTN stays pending credentials;
no credential change/activation occurred. See `STRUCTURED_SPEECH_RECOGNITION_VALIDATION.md`.
