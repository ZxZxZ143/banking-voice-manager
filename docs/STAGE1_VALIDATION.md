# Stage 1 validation — 2026-10-01

## Scope and implementation

Insurance Manager uses the existing 40-scenario catalog, one Router Agent and the unchanged
synthetic Saqta dataset. No banking packs, extra agents, RAG or database were added.
The runtime/core is shared; `scenario_mode=insurance_manager` and scenario-local slot
snapshots identify and isolate insurance context without introducing a pack architecture.

Deterministic handlers now calculate source-based quotes, read owned records, translate
known source facts, collect required slots and end insurer-dependent operations with an
assisted application handoff. No policy, claim, payment, SMS or booking is fabricated.
Read-only completion returns to pending/suspended work and does not end the conversation.
Identity corrections clear stale record identifiers and scenario snapshots.

The Router prompt covers independently actionable outcomes, RU/KK/mixed continuation,
catalog exclusions and unsupported products. Clarification uses the model's targeted
question or localized alternatives; unresolved template tokens are rejected. Invalid model
decisions never execute business actions: the API records an allowlisted routing_error and
clarifies, then hands off after repeated failures under the existing policy. Provider
outages still return explicit 502/504 errors and never generate simulated success.

SC37 returns **«Конечно, передаю диалог оператору.»** (localized in Kazakh), successful
`handoff`, preserved history/trace and stopped listening. Goodbye returns `ended`.
Terminal states survive TTS/controller failure. Browser playback has a bounded watchdog;
reset and queued microphone starts respect runtime generations.

## Automated checks

- Backend: **417 passed**, `pytest backend/tests -q --basetemp=work/pytest-verified`.
- Ruff check and format check: passed for backend application/tests and both new smoke scripts.
- Frontend: TypeScript and production build passed; **28 tests passed** across runtime,
  TTS, trace, HTTP integration and final-transcript voice bridge.
- Data check: 40 scenarios, 3 system intents, 31 actions, all 104 development utterances valid.
- New offline regressions cover RU/KK terminal turns, continuation, targeted clarification,
  deferred multi-intent slots, context cleanup, quote arithmetic, invalid input/ownership,
  safe invalid-output fallback, all catalog first turns in RU/KK, terminal TTS failure and
  stalled browser speech. These fixtures do not measure model accuracy.

## Live Router evaluation

Every run used the unchanged full 104-example dataset and official `evaluate.py`.
Each example received fresh state and one actual routing call; expected labels were not
provided to the model. Failed calls count as wrong. Concurrency 2, one-second call-start
pacing; outputs use exclusive new paths under ignored `work/evals/`.

| Metric | Before Stage 1 | Final Stage 1 |
|---|---:|---:|
| Primary accuracy | 92.31% | **96.15%** |
| Full match | 90.38% | **95.19%** |
| Multi-intent recall | 65.38% | **80.77%** |
| RU primary / full | 90.38% / 88.46% | **96.15% / 94.23%** |
| KK primary / full | 93.33% / 91.11% | **95.56% / 95.56%** |
| Mixed primary / full | 100% / 100% | **100% / 100%** |
| Multi-intent primary / full | 69.23% / 53.85% | **84.62% / 76.92%** |
| Provider failures | 0 | **0** |
| Rejected invalid outputs | 3 | **2** |

Both compared runs used `gpt-4.1-mini`; the final run uses temperature 0 and changed
instructions, so differences are not attributable to a single isolated prompt edit.
Final prompt SHA256: `a17f899a7a8c4dc6425824dc9b052be590c40dd54b6af76a67f3f1e8134a19c3`.
Dataset SHA256: `4623e6f590715ac0e2e2119b2c475d0408f2ab9a7fd3c05a0cabd03b0239751b`.
Evidence: `work/evals/baseline.*` and `work/evals/stage1-verified.*`.

Five final misses remain: U035 documents classified as property claim; U076 suspicious
SMS classified as unclear; U081 and U086 invalid structured output; U090 lost its separate
document request. No perfect-routing claim is made. A separate `gpt-4.1` probe had 11
provider/timeout failures and 88.46% overall full match; it was not adopted as the default.
An earlier Stage 1 prompt produced 91.35% full match with zero invalid outputs; all saved
runs are retained locally rather than overwritten or combined into artificial metrics.

## Real stand and clean startup

Docker Desktop Linux engine was started. A temporary Docker Hub TLS timeout was recovered
by retrying; certificate verification was not disabled. Final backend/frontend images
built successfully. Native backend/Vite processes were stopped, then:

```powershell
docker compose down
docker compose up --build
```

The exact foreground command remains running. Both services became and remained healthy.
The frontend uses `backend:8000` over container DNS, not localhost between containers.
Backend host port 8000 and frontend 5173 bind only to 127.0.0.1.

Verified UI at `http://127.0.0.1:5173`, direct backend health on 8000, frontend-proxied health,
live `/api/message`, Nginx WebSocket Upgrade and outbound OpenAI access.
Evidence: `work/docker-clean-start.log`, `docker compose ps` and the smoke artifacts below.

## Live E2E

`scripts/stage1_smoke.py` passed **18 real API turns through Docker frontend**:
RU paid-policy issue; KK travel; mixed clarification; renewal plus driver addition;
ambiguous policy clarification; RU/KK operator; goodbye; out-of-scope; same-session travel
continuation in RU/KK/mixed; grounded CASCO quote 400000; another information request in
that session; final human handoff. Required scenarios and statuses were asserted.
Mean backend turn latency: 3399 ms; maximum: 6851 ms (excludes TTS/STT).
Evidence: `work/docker-e2e-verified.json` and `.log`.

The real browser UI was also exercised: friendly operator response, successful goodbye,
targeted clarification, preserved trace/history and completed browser TTS. Handoff
screenshot: `work/stand-handoff.jpg`. The UI does not show terminal replies as errors.

## Voice verification

`scripts/stage1_voice_smoke.py` sent three locally synthesized Russian PCM16/24 kHz WAV
fixtures through the **Docker frontend WebSocket**, real local Silero VAD and OpenAI
`gpt-live-transcribe`. Payment question, operator request and goodbye were transcribed
correctly. Each stream emitted partials, one commit and exactly one final transcript;
only that actual final text became one same-session Agent turn. Results were respectively
active, handoff and ended. STT after commit: 693, 822 and 694 ms.
Evidence: `work/docker-voice.json` and `.log`.

Offline frontend regressions verify final-only callbacks, same session, microphone stopped
before TTS, resume after normal playback, no resume after terminal status, and stale/reset
callbacks. Browser TTS was actually observed for typed handoff/goodbye.

The browser's file input also exercised the actual voice bridge end to end: synthetic
operator WAV → live WebSocket/STT → final callback → same-session Agent → browser TTS →
handoff. The UI retained transcript/history/trace and disabled new turns/listening.
Observed STT after commit was 647 ms, TTS first audio 194 ms, routing 3850 ms.
The goodbye WAV also completed the browser pipeline with `ended`, stopped listening and
preserved history/trace (STT 704 ms, TTS first audio 172 ms, routing 4960 ms).
The payment WAV completed the actual browser bridge after a retry: final callback → SC31
→ browser TTS → listening/active in the same session. The first attempt reported a voice
stream failure after partial text and created no Agent turn. The retry's measured STT was
11150 ms and routing 23080 ms, showing that live latency/connectivity is variable.
Automatic microphone restart was observed; its subsequent silent stream ended as empty,
without generating another Agent turn.
Physical microphone startup was attempted but remained at the browser permission step;
that waiting capture was cancelled before using the synthetic file.

Remaining physical microphone step: allow microphone access in a supported browser, speak
an insurance question and observe STT → reply/TTS → listening; then request an operator,
reset and repeat with goodbye. Physical microphone capture and live Kazakh audio quality
were not verified by the synthetic Russian fixtures.

## Security and remaining boundaries

The security-review skill was applied to changed APIs/state, credentials, logs, build
context, Docker config and read-only authority. The local `.env` is ignored. Intended files,
frontend production bundle, logs and Git history (260 blobs before commits) were scanned without printing
keys. Final backend/frontend image configs and every layer were inspected (15468/995 files):
the local key is absent and no image-level OPENAI_API_KEY exists. The runtime alone receives
the secret. No irreversible action executor was enabled; owned-record checks remain intact.

The stand is local and synthetic: no authentication, persistence, insurer write/delivery
integration or real operator queue. Unknown translations, destinations and unavailable
tariffs remain unavailable rather than guessed. Browser TTS depends on installed voices.
Sessions/traces are bounded, single-process and lost on restart. These are actual limits,
not untested future requirements.

Skills actually used: agents-sdk, agent-evals, agent-debugging, security-review, demo-readiness.
