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
wait for «Говорите», then speak. Runtime resumes capture after browser TTS finishes.
Each WebSocket run handles one utterance and uses the same conversation session ID.
Alternatively choose an M4A recording and click «Проверить файл». File replay is
paced in real time and appends synthetic silence (configured pause + 1 second).
The JSON download includes source name, transcript and measured timings.

## Transport

First browser message:

```json
{"type":"start","session_id":"<UUID>","sample_rate":24000,"channels":1,"pause_ms":2500}
```

Wait for `ready`, then send mono signed little-endian PCM16 binary frames at 24 kHz,
up to 100 ms / 4,800 bytes each. AudioContext performs rate conversion; an
AudioWorklet emits microphone frames. Never relabel a 48 kHz stream or send WebM
fragments as PCM. `finish` manually commits; `cancel` or disconnect stops the session.

Server events:

- `ready`: provider connected, selected pause_ms.
- `activity`: speech, has_speech, silence_ms, audio_ms from local Silero VAD.
- `transcript.partial`: append delta to this utterance; includes provider item_id.
- `committed`: stop sending audio, await final transcript.
- `utterance.final`: text, item_id, language=null, stt_after_commit_ms,
  endpoint_silence_ms and audio_ms.
- `empty`: no speech detected; no client turn is created.
- `error`: safe code/message, without API credentials or provider headers.

The final transcript populates the voice text field and calls
`ConversationRuntime.handleTranscript()` once. It does not call the old text endpoint,
which still returns 501. Partials never trigger runtime turns. The provider does not
return detected language labels; `language: null` is omitted at the runtime boundary.

## Automatic end of utterance

Silero VAD runs locally using the small ONNX model shipped with faster-whisper;
no Whisper transcription model is loaded. After speech is detected, continued
silence for 2,500 ms commits the utterance. Resumed speech resets that timer.
The UI permits 500–5,000 ms. This is acoustic endpointing, not semantic proof of
completion: longer hesitations can still be cut off and background speech can
prolong capture. OpenAI turn_detection is null because this model requires
application-side commit. Silence alone returns empty after 15 seconds or manual finish.

## Latency and validation

`stt_after_commit_ms` measures final transcript receipt minus commit time.
`endpoint_silence_ms` is VAD silence measured on the audio timeline; neither includes
LLM/TTS. Connection setup is also separate. Do not describe STT alone as agent latency.

Live checks on 2026-09-23:
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
