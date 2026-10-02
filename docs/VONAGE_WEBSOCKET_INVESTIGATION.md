# Vonage WebSocket startup and diagnostics

User-confirmed live evidence: FROM `12345678901` rings and answers on this account;
signed answer/events succeed, and the media WebSocket upgrades with HTTP 101. The call
then ends before any STT final or reply. The caller implementation and local `.env`
were left unchanged. A successful full live voice conversation remains unverified.

The initial-text hypothesis is ruled out by the current code and regression tests:
`serve()` already used `socket.receive()`, dispatched `text` through the control model,
validated `websocket:connected`/content type/admission, started the session and kept
receiving. It never used `receive_bytes()` for all inbound messages. The reported
`vonage started` line is emitted after that successful initialization.

The exact **reproduced code failure** is STT startup queue overflow:

1. A connected call starts receiving 20ms L16 packets.
2. STT starts on the first normalized audio frame, but its VAD initialization and
   upstream connect/session configuration occur before it consumes the audio queue.
3. The existing queue holds 16 frames (~320ms at this packet cadence).
4. The 17th frame hits `put_nowait()` → `asyncio.QueueFull` → `audio_input_failed` →
   runtime hangup/provider cleanup. There was no exception-class log for this path.
5. The gateway then logged only `vonage closed`; no STT final/Agent/TTS was required.

The deterministic delayed-STT test failed on the original code with precisely this
error and removed registry session. The ordinary initial-text/interleaved-control test
passed before the fix. The old live logs do not prove whether the actual call hit this
overflow or a different STT failure; the next real call must establish that distinction.

After the fix, Vonage opts into `feed_audio(..., wait_for_capacity=True)`. The same
16-frame queue applies bounded backpressure (45s maximum for a blocked admission),
allowing STT startup to finish before more audio is admitted. Closing the runtime or
ending capture interrupts this wait. A permanently stalled stream fails with a logged
`TimeoutError`, rather than buffering without bounds. Generic/Twilio callers retain the
default immediate admission/failure behavior; the runtime architecture and STT engine
are unchanged. Receive-side backpressure can delay controls/disconnect observation
during stalled STT setup, up to the admission bound; signed terminal events can still
close the runtime independently.

The gateway explicitly continues after connected initialization. Binary audio still
uses the existing 16k L16 → 24k PCM conversion and shared STT → Agent → TTS → outbound
16k L16 path. Documented Voice controls `websocket:notify`, `websocket:cleared`, and
`websocket:dtmf` remain supported between audio frames. Unknown/malformed controls,
unsupported content types and unadmitted/duplicate connections still fail closed.
Authentication was not weakened. The NCCO is unchanged: one `connect` action with a
signed WebSocket endpoint, no following action or immediate-stop property.

Protocol reference: [official Vonage Voice WebSocket guide](https://developer.vonage.com/en/voice/voice-api/concepts/websockets).

Verification: **65 Vonage tests, 60 dedicated Twilio tests, 471 full backend tests**;
Vonage and Twilio offline smoke scripts; backend lint/format and diff checks all passed.
Added nine test cases cover:

- Initial TEXT initialization, multiple binary packets, interleaved notify/clear/DTMF,
  and disconnect cleanup.
- A signed FastAPI WebSocket through normalized STT input, final/Agent/TTS and outbound
  L16; first activity is logged once per capture, without transcript logging.
- Delayed STT consuming all 21 queued test packets after startup without closing.
- Malformed JSON, receive exceptions, and STT exceptions: safe class/phase/message
  logging and cleanup, with secret-like exception text excluded.
- Peer close-code reporting with its untrusted reason excluded.
- Bounded backpressure timeout and terminal-event cleanup while admission waits.

Expected next-call log templates (UUIDs/session IDs and counts vary; 640 bytes is a
typical 20ms binary frame):

```text
INFO app.api.routes.vonage vonage websocket_accepted
INFO app.telephony.vonage_gateway vonage control event=websocket:connected call_uuid=<uuid>
INFO app.telephony.vonage_gateway vonage started call_uuid=<uuid> session_id=<session> content_type=audio/l16;rate=16000
INFO app.telephony.vonage_gateway vonage first_binary_audio call_uuid=<uuid> frame_bytes=640 audio_frames=1
INFO app.telephony.runtime phone stt_stream_started call_id=<uuid>
INFO app.telephony.runtime phone stt_activity call_id=<uuid>
INFO app.telephony.runtime phone stt_final call_id=<uuid> session_id=<session>
```

`stt_stream_started` means the shared STT method was entered. `stt_activity` means it
emitted an actual audio-activity event after processing input. A final requires speech
and endpoint detection. During startup, this optional line may precede activity:

```text
INFO app.telephony.runtime phone audio_backpressure call_id=<uuid> queued_frames=16 message=waiting_for_stt_capacity
```

At close, expect a summary such as:

```text
INFO app.telephony.vonage_gateway vonage closed call_uuid=<uuid> audio_frames=<count> close_code=1000 close_reason=peer_disconnect
```

Failures identify classes and static safe messages; raw exception/peer-reason strings
are deliberately excluded because they may contain secrets or conversation content:

```text
WARNING app.telephony.vonage_gateway vonage protocol_or_transport_error call_uuid=<uuid> phase=control_validation exception_type=ValidationError message=websocket_receive_processing_failed
WARNING app.telephony.runtime phone stt_failed call_id=<uuid> exception_type=<class> message=streaming_stt_failed
WARNING app.telephony.runtime phone audio_input_failed call_id=<uuid> exception_type=TimeoutError message=audio_admission_failed
WARNING app.telephony.runtime phone turn_failed call_id=<uuid> exception_type=<class> message=phone_turn_failed
```

For a runtime failure, the close summary names `stt_failed`, `audio_input_failed` or
`phone_turn_failed` rather than just `closed`. Protocol errors use close code 1008;
peer disconnect summaries preserve the observed code and use a static reason label.
No raw audio, JWTs, credentials, key material, phone numbers or conversation text are
added to these logs.
