# Phone endpointing and turn latency

User-confirmed live baseline: Vonage/STT/Agent/TTS work end-to-end, Agent approximately
2.9–3.5s, TTS 2.0–3.2s, reported turns 8–12.7s. This task preserves that architecture,
models, prompts, half-duplex/session behavior and the Vonage startup backpressure fix.
The new endpoint threshold and latency benefit still require a live retest.

Previously both phone factories constructed `OpenAIStreamingSTT(api_key=key)` and
inherited its **2500ms** pause. They now pass `Settings.phone_endpoint_silence_ms`:

```dotenv
PHONE_ENDPOINT_SILENCE_MS=1200
```

Default **1200ms**, validated range **800–5000ms**. Restart the backend to apply it.
The ignored local `.env` was not edited; absent an override, the new default applies.
Browser `/api/v1/voice` and its frontend retain their **2500ms** defaults and existing
per-stream configuration. The reusable STT constructor's legacy default also remains
2500ms; the two phone composition factories explicitly choose the phone setting.

Silero's existing `PauseTracker` evaluates in 32ms steps: a 1200ms threshold is reached
at 1216ms, compared with 2528ms for 2500ms. A shorter pause followed by speech resets
the timer; no new utterance-splitting algorithm was introduced. Expected improvement is
approximately **1.3s less caller-perceived endpointing delay**, subject to VAD, buffering,
network and provider timing. Agent and TTS computation durations should remain similar.

Changed code paths:

- `core/config.py` and root `.env.example`: phone setting/bounds/example.
- `telephony/{vonage,twilio}_gateway.py`: pass that setting to the same STT engine.
- `speech/stt/streaming_provider.py` and `streaming.py`: opt-in phone timing signals;
  browser relay calls retain their existing event shapes and default behavior.
- `telephony/runtime.py`: numbered per-call turn timings from final admission through
  acknowledged playback, preserving final deduplication and the existing task sequence.
- `telephony/providers/{vonage,twilio}.py`: timing logs at first-frame send submission
  and native playback acknowledgements; audio conversion/transport behavior is unchanged.

Runtime timing log shape:

```text
phone latency stage=<stage> call_id=<id> session_id=<id> turn=1 monotonic_ms=<time> duration_ms=<duration> basis=<origin>
```

`monotonic_ms` is a process-monotonic timestamp, not UTC. Subtract timestamps from the
same process/call/turn. Durations use the following boundaries:

| Stage | Duration basis / meaning |
|---|---|
| `speech_end` | Last VAD-positive audio processing timestamp, logged after silence is detected; may repeat for non-final pauses |
| `endpointing_decision` | Elapsed since the latest speech-end observation, when available; a separate log gives detector audio `silence_ms` |
| `stt_final` | Actual final admission; elapsed since endpoint decision, when available |
| `agent_start` | Dispatch gap since final admission |
| `agent_done` | Agent call duration |
| `tts_start` | Gap after Agent completion, including existing response event recording |
| `tts_ready` | TTS call duration |
| `playback_start` | Runtime provider submission; gap since TTS ready |
| `playback_complete` | Provider call duration through acknowledged playback, including conversion/send/buffering/audio duration |
| `total_turn` | Latest speech-end observation → playback complete; falls back to final admission if no speech-end timestamp exists |

Speech-end is a VAD processing observation, not an exact acoustic end timestamp; queued
audio can affect its wall-clock interpretation. It is reset when speech resumes. Final,
Agent, TTS and provider submission timestamps are direct measurements. The provider's
additional `vonage playback_start` / `twilio playback_start` logs mark first-frame send
submission **after** conversion/lock acquisition and include `conversion_lock_ms`.
Native notify/mark acknowledgements include `monotonic_ms`. Neither send submission nor
acknowledgement measures when sound physically reaches the handset.

The existing `phone turn_complete total_ms` remains **final admission → playback
complete**, excluding endpointing/STT-final delay. Do not compare that value directly
with a new `total_turn basis=speech_end` duration, or expect it to drop by 1.3s solely
from a silence change. Compare matching boundaries across real calls.

No unnecessary sleeps were found or removed in final → Agent → TTS → playback.
The 10ms bounded-capacity poll protects Vonage startup; the 200ms relay loop watches a
final-transcript deadline concurrently and does not delay successful final dispatch.
Playback acknowledgement is required for half-duplex listening to resume safely.

Verification: **41 phone-runtime tests**, **65 Vonage**, **60 Twilio**, **13 browser
stream integration tests** (179 focused), **475 full backend**, **37 frontend** tests,
frontend typecheck, both phone offline smokes, backend lint/format and diff checks passed.
Regression cases use the real PauseTracker with explicit fixture speech/provider data:
no final at 1184ms, continuation resets the timer, one commit/final/Agent/TTS turn at
1216ms despite duplicate completion events, accurate ordered timing durations, secret-free
logs, configurable factory thresholds and unchanged omitted browser pause default.
