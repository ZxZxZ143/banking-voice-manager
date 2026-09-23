# Recorded audio transcription

Standalone offline STT test, separate from routing and the live microphone UI.
Original recordings remain in Downloads; they are not uploaded or committed.

From the repository root in PowerShell:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r scripts/requirements-voice.txt
./.venv/Scripts/python.exe scripts/transcribe_audio.py "$env:USERPROFILE/Downloads"
```

The runner requires one named recording for each A01 through A27, loads Whisper
once, and saves JSON after every file plus a final UTF-8 CSV in `work/voice/small/`.
Model downloads are stored in `work/models/`. Both are ignored by Git.
Use `--model large-v3-turbo --output work/voice/turbo` for a separate comparison.
The default is CPU/int8; CUDA requires suitable hardware and runtime libraries.

No language hints or reference transcripts are supplied to the model. Returned
language is the model's prediction, not a ground-truth or mixed-language label.
Model load/download time is separate. Per-file latency includes decoding, VAD and
fully consuming the transcription generator. The first file may include warmup.
These are offline timings, not microphone endpointing or end-to-end response latency.
Segment timestamps are model estimates, not manually verified pause annotations.

Review Kazakh/mixed speech, negations, phone numbers, IIN and plate values manually.
For A25/A26 the expected text is empty. Do not calculate WER against the recording
script until a human verifies what was actually spoken. Streaming replay is still
needed to test whether a bot interrupts A18-A24; TTS is outside this runner.

## Measured local/cloud runs (2026-09-23)

- CPU: Intel Core i5-8279U, four cores; Intel Iris Plus, no NVIDIA GPU.
- Whisper small/int8: 27 files, median offline processing 6,133.65 ms.
- Whisper large-v3/int8: 27 files, median offline processing 32,187.40 ms.
- OpenAI gpt-live-transcribe: eight real-time replays (A01, A02, A04, A11,
  A13, A15, A23, A24), all requests completed; median final-after-commit 674.945 ms.
  This excludes setup and audio replay, and is NOT the same metric as offline STT.
  Partial text was received while sending audio. Cloud tests are billable.

Cloud retained both languages in A11/A23 where large-v3 lost the Kazakh part, but
introduced "массаж" before "терапевтке" compared with the planned script. Short
Kazakh confirmation and phone transcription still need review. No WER/accuracy
claim is made without manually verified references. Endpointing is untested:
the probe commits only at file end, not at internal pauses.

Local results: `work/voice/{small,large-v3}/transcripts.{json,csv}` and
`work/voice/openai-stream/summary.csv` with per-file JSON event/timing records.
