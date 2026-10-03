# Vonage startup backpressure — teammate evidence retained in Stage 6

Source: teammate commit `5c90895` on `feature/vonage-telephony-provider`, retained through
`642aebf`. The teammate reported an earlier call reaching authenticated answer/media and
then closing before STT final. That historical report does **not** validate a Stage 6 live
call; the current integration has no provider credentials and PSTN remains NOT RUN.

The reproduced code failure was a 16-frame STT startup queue overflow: 20 ms L16 packets
arrived while VAD/upstream initialization ran, and frame 17 hit `put_nowait()` before the
consumer started. Initial text dispatch was already correct; the gateway handled
`websocket:connected` then continued receiving interleaved text controls/binary audio.
Historical live logs alone did not establish that queue overflow was the actual live cause.

The teammate's fix is preserved: Vonage calls `feed_audio(..., wait_for_capacity=True)`.
The queue stays at 16; blocked admission waits at most 45 seconds, rechecking whether the
call/capture remains current. End/cancel invalidation interrupts admission. A permanently
stalled setup fails safely, without unbounded buffering. Twilio retains default immediate
admission behavior. No auth or protocol validation was removed.

Receive-side backpressure can delay observing socket controls/disconnect for up to that
bound; an independently received signed terminal HTTP callback can close the runtime.
Regression fixtures cover 21 frames with delayed STT consumption, bounded timeout,
terminal callback while blocked, initial TEXT plus several binary frames, interleaved
notify/clear/DTMF, malformed frames, STT exceptions and cleanup.

Expected safe stages: `vonage websocket_accepted`, `vonage started`, `first_binary_audio`,
`phone stt_stream_started`, optional `audio_backpressure`, `stt_activity`, `stt_final`,
`agent_response`, `tts_ready`, provider playback completion, `turn_complete`, `vonage closed`.
The stream-start log only means entry into STT, not successful transcription. Timing logs
use monotonic stage durations; speech-end is the last VAD-positive processing time, not an
exact acoustic timestamp. UUID correlation and static class/phase/error codes stay in
operational logs; transcripts, raw exception text, phone numbers and credentials do not.
These timing logs are not persisted dashboard metrics.

Current test counts and Docker results are recorded in
`STAGE6_TELEPHONY_INTEGRATION_VALIDATION.md`; earlier branch test counts are historical only.
Protocol: [official Vonage Voice WebSocket guide](https://developer.vonage.com/en/voice/voice-api/concepts/websockets).
