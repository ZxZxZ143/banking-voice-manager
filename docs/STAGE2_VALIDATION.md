# Stage 2 validation — modular Insurance Manager

Validated on Windows with Docker Desktop Linux engine on 2026-10-01. Starting reference:
`main` at `324d6af`; remote matched it and the working tree was clean. Stage 1 remains the
insurance behavior baseline. No unrelated branch/history was rewritten.

## Architecture and migration

Introduced `backend/app/packs/contracts.py`, `registry.py`, `lifecycle.py` and
`conversation/` for pack contracts/manifests, interaction modes, trusted registration,
isolated context lifecycle, locked bounded sessions and generic message orchestration.
Only `insurance_manager` is registered in production. The manifest is immutable Python
metadata, consultative, supporting RU/KK/mixed with InsuranceResult output.

`packs/insurance_manager/` now owns Router prompt/schema/validation, canonical JSON
adapters and repositories, catalog, insurance policy/transitions, actions, read-only tools,
responses, history, local context and public wire schema. No supplied dataset was copied.
Old import paths are compatibility exports/adapters, not duplicate business implementations.

Global context stores session/turn/language/channel/status. Each pack entry stores its
own typed business context, lifecycle and latest result. The old flat DialogState is
projected only for API/Router compatibility; actual stored state is separated.
InsuranceResult records the actual flow/status/collected data/actions/sources/completion/
handoff. It does not claim successful issuance, payment, delivery or insurer writes.

Internal lifecycle supports activation, suspension, resumed contexts and completion/fresh
activation. Completing an insurance SCxx read-only flow does not complete its pack or
conversation; existing pending/stack work can resume. Terminal handoff/goodbye completes
the pack and rejects further user turns with 409.

## Isolation and compatibility

The shared core passes only selected local state and a global snapshot to a pack. No other
context/history/result/prompt/knowledge/tool is copied or merged. Exact registered context
and result types are checked before commit. Failed pack execution/switch does not commit
global or local changes. Unit tests use a private fixture pack to demonstrate selective
Router input, independent state, suspension/resume, rollback and result isolation.
No fixture pack is registered by the application. This is a trusted application boundary,
not a sandbox for hostile Python plugins.

`POST /api/message` retains `{session_id,text}` and its six top-level response fields.
Default selection uses the registry and adds no LLM call. Optional
`scenario_mode=insurance_manager` resolves the same pack; unknown modes return 422
before routing or state mutation. The concrete insurance response schema remains available
in OpenAPI through `wire.py`. The frontend reads the previous flat state and reply language.
Trace adds scenario_pack_id, interaction_mode and context_lifecycle. The supervisor panel
accepts new metadata and old traces. STT, TTS, ConversationRuntime and voice protocol were
not redesigned; no scenario-pack logic was added to them.

## Automated verification

- Backend: **429 passed**, including all **417 unchanged Stage 1 tests** and 12 architecture
  checks. Tests cover registry/default/unknown pack, owned capabilities, prompt fingerprint,
  global/local schema separation, legacy projection, lifecycle, selective context/input,
  rollback, grounded result and terminal/default API compatibility.
- Frontend: **29 passed**: runtime 13, TTS 6, trace 6, HTTP integration 2, voice bridge 2.
  The original 28 tests remain; one new test checks additive pack metadata and legacy traces.
- TypeScript and production Vite build passed.
- Ruff check and format check passed for backend app/tests; **117 files formatted**.
- Existing Stage 1 tests were not deleted, relaxed or changed to accommodate the migration.

Evidence: `work/stage2-backend-accepted.log`; normal frontend npm scripts; the source tests.
Commands are in README. Evaluation artifacts and logs stay ignored under `work/`.

## Router evaluation: before/after

Same model `gpt-4.1-mini`, temperature 0, all 104 canonical examples, concurrency 2,
one-second minimum call-start interval, one fresh state and one Router call per example.
Failures count as wrong. No expected label enters model input and no prompt tuning was done.

Offline comparison with trusted Stage 1 Git source confirmed byte-identical instructions,
the same strict SDK output schema and identical fresh Router input for all 104 examples.
Instructions SHA256: `a17f899a7a8c4dc6425824dc9b052be590c40dd54b6af76a67f3f1e8134a19c3`.
Dataset SHA256: `4623e6f590715ac0e2e2119b2c475d0408f2ab9a7fd3c05a0cabd03b0239751b`.
The source regression also verifies same-session projection equivalence.

| Metric/group | Stage 1 | Stage 2 verified |
|---|---:|---:|
| Primary accuracy | 100/104 = 96.15% | 100/104 = 96.15% |
| Full match | 99/104 = 95.19% | 99/104 = 95.19% |
| Multi-intent recall | 21/26 = 80.77% | 21/26 = 80.77% |
| RU primary / full | 96.15% / 94.23% | 98.08% / 96.15% |
| KK primary / full | 95.56% / 95.56% | 95.56% / 95.56% |
| Mixed primary / full | 100% / 100% | 85.71% / 85.71% |
| Multi-intent primary / full | 84.62% / 76.92% | 84.62% / 76.92% |

Stage 2 verified had **zero provider failures and three invalid structured outputs**,
versus two invalid outputs in Stage 1. Mixed dropped by one example, U083, due to a rejected
structured output; U060 and U086 were also rejected. This language-group decline is real
in this run and is not hidden by unchanged aggregate metrics. Valid routing latency:
median 2675 ms and p95 3532 ms, versus 2806/4884 ms in the saved Stage 1 run.

An earlier Stage 2 run is also retained: primary 95.19%, full 94.23%, recall 80.77%,
zero provider and three invalid-output failures. It was followed by the contract-equivalence
diagnostic and a complete rerun, not selective retries or merged predictions. Different
failures across identical input/schema/instruction runs indicate model-output variability;
this evidence does not establish a permanent improvement for individual utterances.

| Previous miss | Verified Stage 2 result | Status in this run |
|---|---|---|
| U035 | SC14 instead of SC18 | Remains |
| U076 | SC38 instead of previous SYS_UNCLEAR | Improved in this run |
| U081 | SC27 + SC04 instead of rejected output | Improved in this run |
| U086 | Rejected structured output | Remains |
| U090 | SC14 without SC18 | Remains |

U035/U090 remain semantic misses; the migration did not purport to fix them. No hardcoded
example or special-case prediction was introduced. Aggregate routing gate is preserved;
mixed and structured-output reliability remain factual limitations.

Evidence: `work/evals/stage1-verified.*`, `stage2-migration.*`, `stage2-verified.*`,
`work/stage2-equivalence.json`, `work/stage2-comparison.log`.

## Docker and real E2E

Clean startup was performed after final application changes:

```powershell
docker compose down
docker compose up --build
```

Backend/frontend built and became healthy. The foreground command remains running.
Ports remain 127.0.0.1:8000/5173; Nginx uses backend:8000 and supports WebSocket Upgrade.
New pack modules are included by backend COPY/app package discovery without local-only
dependencies or additional infrastructure. Root `.env` is runtime-only.

The existing `scripts/stage1_smoke.py` passed **18 live turns** against the final Docker
frontend: RU, KK, mixed, renewal/driver multi-intent, targeted clarification, RU/KK operator,
goodbye, out-of-scope, same-session duration continuation in all three language categories,
grounded CASCO quote 400000, next information request and final same-session handoff.
Every trace identifies insurance_manager. Mean backend latency 3091 ms, maximum 4297 ms
(excludes STT/TTS). Evidence: `work/stage2-e2e-final.json/.log`, `stage2-docker-final.log`.

The real browser displayed the exact friendly operator reply, successful handoff and
completed browser TTS, with insurance_manager/consultative/completed in Supervisor Trace.
The normal voice file reached the runtime/Agent in the same session, displayed source-based
payment information, completed TTS and resumed listening. Its first STT attempt failed
after partial text and created no Agent turn; the retry succeeded. Observed browser-path
STT after commit was 3570 ms, Router 5830 ms, TTS first audio 533 ms.

The operator WAV then completed the actual browser bridge in that same session as turn 2:
real STT final → pack → exact friendly reply → completed browser TTS → handoff, with no
listening restart. STT after commit 762 ms, Router 2760 ms, TTS first audio 195 ms.
After reset, the goodbye WAV completed as turn 1 in a new session: ended and stopped
listening, retaining history/trace; STT 890 ms, Router 2750 ms, TTS first audio 168 ms.
Screenshots: `work/stage2-handoff.jpg` and `work/stage2-goodbye.jpg`.

## Voice regression

The unchanged `scripts/stage1_voice_smoke.py` passed all three synthetic Russian WAV
fixtures through final Docker WebSocket/Nginx, real local Silero VAD, OpenAI STT and
same-session final-only Agent requests: payment active, operator handoff, goodbye ended.
STT after commit: **612 / 832 / 711 ms**. Exactly one final transcript produced one Agent
turn per fixture. Evidence: `work/stage2-voice-final.json/.log`.

Frontend tests preserve microphone stop-before-routing/TTS, resume after normal playback,
no resume after terminal response, same session, final-only mapping and stale/reset guards.
Actual typed browser handoff completed TTS and disabled new turns. Physical microphone
startup was attempted; a voice stream error before any final/Agent turn remains separate
from the pack migration. Physical speech and Kazakh audio quality are not claimed verified.

Both terminal cases also passed through actual browser file input, live STT, Agent and TTS;
they were not merely simulated by the runtime tests. Slow browser file-chooser/preparation
steps were observed separately from measured STT/Router timings.

## Security review and demo readiness

Security review traced transport → registry → selected context → insurance policy/lookups
→ output/trace. User pack IDs cannot import code or select unregistered tools/knowledge;
unknown mode and context isolation have deterministic checks. Owned-record checks and
disabled irreversible actions remain unchanged. No new public trace endpoint or write
executor was enabled. Configuration injects narrow transport settings; no secret appears
in manifest, Router prompt/input, business state/result or frontend trace.

The exact local key and strict key patterns were scanned without printing them across
intended files, frontend production bundle, local logs and all Git blobs. `.env` is ignored.
Both final image configs and every layer passed: **15612 backend and 995 frontend files**
inspected; no build-time OPENAI_API_KEY or application `.env` in image layers. The key is
provided only to backend at runtime. Evidence: `work/stage2-security.log`.

Demo readiness used the clean documented Docker startup, real health/HTTP/WS, live routing,
grounded insurance and terminal outcomes, browser TTS, voice integration and visible error
behavior. No missing provider result was replaced by an unlabeled mock.

## Remaining limitations

- Routing is not perfect: the reported semantic/structured failures and mixed-group decline
  remain; equal aggregate metrics do not imply identical per-example decisions.
- Live STT/connectivity and browser playback latency vary; a failed stream can require retry.
  Synthetic Russian audio is not a measurement of customer microphones or Kazakh speech.
- Only Insurance Manager exists in production. Lifecycle infrastructure is tested with
  private fixtures; automatic cross-product selection/proactive actions are unimplemented.
- Sessions/results/traces are bounded in-memory and single-process. No authentication,
  insurer writes, external delivery, actual operator queue or persistent store exists.
- Isolation applies to trusted in-process code; arbitrary Python plugins are unsupported.

Skills actually used: agents-sdk, agent-evals, agent-debugging, security-review, demo-readiness.
