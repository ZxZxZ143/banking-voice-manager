# Integrated MVP validation

2026-09-23. Local synthetic Saqta Insurance demo, not a production insurance service.

## Included work

Agent Core `feature/agent-core-router-eval` plus `integration/voice-runtime` (0261acc),
which contains `feature/conversation-runtime` (cb9e7fb) and `transcribtion` (138d5fb).
Teammate branches were not changed or force-pushed.

One session spans microphone/STT or text → one structured Router call → confidence policy,
state/stack/pending work → grounded RU/KK reply → browser TTS → listen again.
Only Core `ended`/`handoff` ends the automatic loop; local Stop preserves Core status.
The voice-input toggle provides genuine text-only fallback without background capture.
Current-turn text follows historical context; reply language has conservative RU/KK guards.

## Executed checks (repeated on pushed main)

- Backend: **307 tests passed**; Ruff lint and format checks passed (77 files).
- Frontend: **24 tests passed**, TypeScript check and production build passed.
- Post-merge health/proxy and browser page verified after restarting the Vite process.
- Live baseline API: 9 routed turns + closed-session 409 passed. Covers RU, KK, mixed,
  multi-intent, unclear, out-of-scope, continued slots, goodbye and retained session/history.
- Additional live API: 6 requests passed: clarification → office answer, explicit handoff
  and subsequent 409, mock-client identification → owned policy dates and grounded tools.
- Browser: real HTTP mode, RU office answer → KK office answer in the same session;
  TTS completion returns to input, supervisor displays route/confidence/state/latency.
  Multi-intent returned a safe 502 once; a manual retry succeeded with SC27 active and
  SC04 pending at turn 3. Failed routing did not advance Core state. This remains a risk.
- Physical microphone produced partial/final transcripts and automatic Core/TTS turns.
  Capture was stopped between manual checks; no claimed acoustic-quality score.
- Synthetic Russian WAV through Vite WS proxy: exact transcript, 20 partial events,
  one final, 620 ms after commit, 2,592 ms endpoint silence. Synthetic silence returned
  `empty`, with no invented final turn. Source audio was clearly synthetic, not personal.
- Dependency check passed; .env ignored/untracked. Publishable/index/frontend bundle
  credential-pattern scan found no real secret; test credential strings are fixtures.

## Router evaluation

Latest run: all104, gpt-4.1-mini, one call/input, serial, 3s minimum start interval.
Official unchanged evaluate.py: primary **91.35%**, full **90.38%**, multi-intent recall
**92.31%**. Zero provider failures, one invalid output. Previous integrated run: primary
92.31%, full90.38%, recall76.92%. Input order changed; do not interpret this as a controlled
prompt-quality improvement. Full artifacts remain in ignored work/router-eval/; see
ROUTER_EVALUATION.md for historical measurements.

Remaining errors: travel/visa and suspicious SMS over-clarification, medical-abroad versus
accident, incident versus documents, missing complaint/dispute co-intents, and out-of-scope
versus unclear. U061 failed output validation. No utterance-specific routing was hardcoded.

## Start

PowerShell, repository root; configure ignored .env with OPENAI_API_KEY and
OPENAI_ROUTER_MODEL=gpt-4.1-mini. Never put the key in frontend configuration.

```powershell
./.venv/Scripts/python.exe -m pip install -c backend/requirements.lock -e './backend[dev,voice]'
./.venv/Scripts/python.exe -X utf8 -m app.main
```

Second terminal, repository root:

```powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open http://127.0.0.1:5173. Use real HTTP mode (VITE_USE_MOCK_AGENT=false, default).
Uncheck «Голосовой ввод» for typing without ambient audio. Backend:127.0.0.1:8000;
optional Agent Core-only debug form:/dev with ENABLE_DEV_STAND=true.

## Limits

State/traces are bounded process memory and reset on restart. No authentication; bind
to loopback. No actual operator connection or business writes. Irreversible execution
is disabled; any later action requires preview → explicit confirmation → execute.
Grounded replies cover a minimal read-only slice, not every action in actions.json.
Browser Kazakh pronunciation depends on installed voices; text is localized, but accent
and speech recognition still need human quality review. Routing is not perfectly reliable.
