# Streaming voice test bench

Implemented: browser microphone or phone recording -> `/api/v1/voice` -> OpenAI
`gpt-live-transcribe`, with concurrent audio upload and transcript events. Russian,
Kazakh and mixed speech are enabled. The frontend now passes final transcripts to
ConversationRuntime and the real Agent Core `/api/message` endpoint.

## Run locally

From the repository root, install `./.venv/Scripts/python.exe -m pip install -c
backend/requirements.lock -e "./backend[dev,voice]"` (one line). Set OPENAI_API_KEY
in the ignored root `.env`. Start the backend:

```powershell
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --ws-max-size 8192 --ws-max-queue 16
```

In another terminal: `cd frontend`, `npm ci`, keep `VITE_USE_MOCK_AGENT=false`, then
`npm run dev`. Open http://127.0.0.1:5173. Click «Начать разговор», permit the microphone,
wait for «Говорите», then speak. Runtime prepares input during TTS and activates
transmission after playback finishes. With backend HTMLAudio, a protected near-end
RAM buffer can preserve an answer beginning in the last 400 ms of playback.
Each WebSocket run handles one utterance and uses the same conversation session ID.
Alternatively choose an M4A recording and click «Проверить файл». File replay is
paced in real time and appends synthetic silence (configured pause + 1 second).
The JSON download includes source name, transcript and measured timings.

## Transport

First browser message:

```json
{"type":"start","session_id":"<UUID>","sample_rate":24000,"channels":1}
```

Omitted/null `pause_ms` selects the server's expected-context adaptive profile. An
explicit integer 500–5000 retains manual silence selection. Wait for `ready` **and
runtime activation after TTS**, then send mono signed little-endian PCM16 frames at 24 kHz,
up to 100 ms / 4,800 bytes each. AudioContext performs rate conversion; an
AudioWorklet emits microphone frames. Never relabel a 48 kHz stream or send WebM
fragments as PCM. `finish` manually commits; `cancel` or disconnect stops the session.

Server events:

- `ready`: provider connected, selected `pause_ms`; adaptive mode adds `endpoint_profile`.
- `activity`: speech, has_speech, silence_ms, audio_ms from local Silero VAD.
- `speech.started`: first local speech detection in adaptive browser mode.
- `transcript.partial`: append delta to this utterance; includes provider item_id.
- `committed`: stop sending audio, await final transcript; adaptive mode adds `silence_ms`.
- `utterance.final`: text, item_id, language=null, stt_after_commit_ms,
  endpoint_silence_ms, audio_ms and `timing` with nullable `realtime_final_ms` /
  `bounded_final_ms` measured from commit/second-pass launch, respectively.
- `empty`: no speech detected; no client turn is created.
- `error`: safe code/message, without API credentials or provider headers.

The final transcript populates the voice text field and calls
`ConversationRuntime.handleTranscript()` once. It does not call the old text endpoint,
which still returns 501. Partials never trigger runtime turns. The provider does not
return detected language labels; `language: null` is omitted at the runtime boundary.

## Structured recognition and confirmation

Structured expected-slot turns additionally emit safe `recognition` metadata and an opaque,
one-use `recognition_id` forwarded to `/api/message`. Sensitive fields launch a bounded
transcription at `committed`, in parallel with the Realtime final. The first unique valid
whole-field result returns `confirmation_required` immediately; it cannot update business
slots. Invalid first results wait for the other recognizer. An unfinished loser is cancelled;
a completed loser can corroborate metadata but cannot replace the value being read back.
The same conversation reply asks for full read-back confirmation or bounded segmented repair.
Each segment has two customer turns: initial recognition plus one repeat or short segment
confirmation. Agreement stores a private draft; one unique result with no corroboration
requires a segment yes; conflict/unusable evidence repeats only that part. Exhaustion offers
browser keyboard input or phone handoff. Full assembly still requires its own final read-back
and yes. Domestic 8 is spoken back as 8; detected national ten-digit phones use 3+3+4 parts.
Natural RU/KK minimal corrections repeat the entire corrected value and still require
explicit confirmation. Correction context contains only field kind, never private values.
Confirmation/correction replies need no second transcription. Region codes retain low-risk
schema acceptance. Added metadata: `outcome`, `risk`, `consensus`, `verification_method`,
`second_pass_wait_ms`, `candidate_ready_ms`, `realtime_final_ms`, `bounded_final_ms`,
`readback_source`, `loser_cancelled` and allowlisted `segment_evidence`; no candidate value
or alternate transcript is in metadata. Raw `text` is the winning transcript (Realtime or bounded), bound to the private
receipt. See [precision gate](STRUCTURED_SPEECH_PRECISION_GATE.md) and
[correction/latency validation](VOICE_LATENCY_AND_CORRECTION_VALIDATION.md), plus
[segment validation](SEGMENTED_IDENTIFIER_CAPTURE_VALIDATION.md).

## Automatic end of utterance (VAD)

Silero VAD runs locally using the small ONNX model shipped with faster-whisper;
no Whisper transcription model is loaded. After speech is detected, continued
silence for the selected profile commits the utterance. Browser defaults: confirmation
750 ms, recognized correction 900 ms, segment 800 ms, region 900 ms, whole sensitive
identifier 1300 ms and ordinary dialogue 1600 ms. A complete normalized partial stable for at least 400 ms can
shorten these to 650/800/650/750/1100 ms respectively, always with local VAD silence.
A transient valid regex match alone cannot commit. Resumed speech resets the timer.
The UI also permits a manual 500–5,000 ms. This is acoustic endpointing, not semantic proof of
completion: longer hesitations can still be cut off and background speech can
prolong capture. OpenAI turn_detection is null because this model requires
application-side commit. Silence alone returns empty after 15 seconds or manual finish.

## Latency and validation

Current browser measurements, prewarm/echo bounds, synthetic overlap limitations and
release checks are in [the 2026-10-04 report](VOICE_LATENCY_AND_CORRECTION_VALIDATION.md).
`voiceTiming.ts` emits bounded content-free monotonic browser events. The prepared mic
does not send PCM; the 400 ms ring is memory only and clears per turn/cancel. Tracks fully
stop on disable/end/reset/dispose, including cancellation during a pending handshake.

`stt_after_commit_ms` measures final transcript receipt minus commit time.
`endpoint_silence_ms` is VAD silence measured on the audio timeline; neither includes
LLM/TTS. Connection setup is also separate. Do not describe STT alone as agent latency.

Historical checks on 2026-09-23 (fixed 2500 ms profile):
- A20_ru_pause_20 through the backend and Vite WS proxy: final transcript,
  endpoint silence 2,592 ms, STT after commit 912 ms.
- A23_mixed_pause through the browser file picker: final transcript,
  endpoint silence 2,528 ms, STT after commit 589 ms. Kazakh recognition errors remain.
- A25_silence through the backend: empty, no invented final turn.
- Offline tests cover pause reset, 2-second hesitation, short speech and pure silence.
These are small smoke checks, not a completed 27-recording accuracy evaluation.

`python scripts/test_voice_backend.py <recording.m4a>` replays through the local
frontend WS proxy and saves events in ignored `work/voice/backend-stream/`.
It appends four seconds of labeled synthetic silence. Running a live check sends
selected audio to OpenAI and uses the billable API.

The independent `scripts/test_openai_stream.py` probe commits at file end and does
not test automatic endpointing. Eight original probe recordings succeeded with
median post-commit latency about 675 ms. Results: `work/voice/openai-stream/`.

## Bounds and credentials

The key stays in server environment/.env, never in frontend code or WS messages.
Origin is restricted to the configured frontend and local port 5173. This is a
loopback-only test bench; public deployment needs authenticated sessions and quotas.
Limits: two simultaneous sessions per process, 120 seconds of PCM, 150 seconds
per session, 30 seconds waiting for a final transcript, bounded frames and queues.
Browser file input is limited to 10 MB / 110 seconds. Slow upload fails explicitly.

References:
- https://developers.openai.com/api/docs/guides/realtime-transcription
- https://developers.openai.com/api/docs/guides/voice-websockets?api=realtime
