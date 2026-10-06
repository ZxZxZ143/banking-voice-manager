# RU/KK confirmation STT hotfix — 2026-10-06

The application now keeps Russian/Kazakh confirmation evidence in its original
language and keeps an unresolved confirmation inside private structured capture.
English Yes/No/Yep/Nope cannot confirm or reject an identifier.

The requested branch is `codex/ru-kk-confirmation-stt-hotfix`. Its starting remote
main was **17aa980**, containing the expected **9bd5898** plus the bilingual opening
and Kazakh Risk language fixes and a README update. Those changes are preserved.
This is a focused hotfix, not a new stage.

## Reproduction and implementation

The original `17aa980` capture/parser source was replayed against a synthetic pending
phone and `No.`. `advance_capture()` returned no capture step, making the short
answer eligible for Router/business processing. Evidence is in ignored
`work/confirmation-stt/baseline-reproduction.json`. This reproduces the application
ownership failure with the supplied transcript; it does not claim a recording of
the original human microphone failure.

Ordinary streaming and recorded-audio STT prompts now identify Russian/Kazakh as the
primary languages, preserve spoken language/script and forbid English translation.
Genuinely spoken product names and Latin identifiers remain allowed. Conversation
response language is a soft prompt hint, never a transcript rewrite.

Confirmation prompts contain only public RU/KK words: да, нет, верно, неверно,
правильно, неправильно, иә, жоқ, дұрыс, дұрыс емес. They are under the existing
500-character bound, including the language hint. No pending phone, IIN, policy,
claim or plate is included.

The existing deterministic parser remains the confirmation authority. Clear
RU/KK answers and recognized corrections use one transcription. Unknown and
out-of-language replies can trigger **one** `gpt-transcribe` recovery over the
same short audio, with RU+KK, a 20-second deadline and no SDK retries. At most
10 seconds of confirmation audio is retained in RAM; a longer utterance is never
truncated into a purported confirmation. Audio clears on final/cancellation.

`No. → Да.` confirms; `No. → Нет.` rejects; `No. → No.` stays unresolved. If a
second result is already available and disagrees with a valid first result, neither
is selected. Normal valid answers do not launch that second call. Confirmation
evidence is carried privately through the existing one-use receipt; recovered RU/KK
text becomes the visible final transcript and receipt binding. Recovered raw text
is removed before receipt storage. Only allowlisted status/timing flags enter trace.

Whole and segment confirmations retain the same private draft and repeat the
localized confirmation once on unknown/foreign/conflicting evidence. Repeated
uncertainty uses the existing browser keyboard or phone handoff fallback. Segment
recognition budgets, domestic 8, national ten-digit phones, complete read-back and
final admission are preserved. Clearly expressed separate requests still reach the
existing Router. Short unavailable/unrelated answers cannot become a scenario transition.

## Deterministic and release gates

- Full backend: **1435 passed**. Current starting main had 1350 cases, including
  the earlier 1322 baseline; this task adds 85 confirmation cases. Existing
  short-question and segment-uncertainty fixtures were updated to the newly required
  ownership/repeat behavior without removing those tests.
- Focused confirmation file: **85 passed**, including the exact synthetic screenshot
  phone read-back, first `No.`/second `Да.`, successful phone lookup, no IIN fallback,
  no segment restart and no handoff. Coverage includes RU/KK negatives, corrections,
  conflict, recovery failure, bounds, one final publication and matching receipt.
- Frontend: **106 passed**; TypeScript and Vite build passed.
- Ruff app/tests and affected Python scripts, Ruff format and `git diff --check` passed.
  Run Python lint from `backend` so existing import classification is preserved.
- Frontend formatting passed with `--end-of-line auto`. The ordinary command flags
  CRLF in 38 unchanged files in this Windows checkout; no unrelated UI reformat was made.
- Docker build/start: backend/frontend healthy. All four offline phone smokes passed
  on Windows and in the rebuilt Linux image. The Linux core/Risk smoke uses the same
  explicit data paths as Compose; its first standalone attempt omitted those paths.
- Privacy check scans changed source plus built frontend for the configured credential
  without printing it, and checks synthetic browser SQLite event payloads for pending
  identifiers. No credential or pending-identifier matches; no customer audio storage
  was added. Synthetic evaluation clips are explicitly generated fixtures in ignored work.

The full baseline still covers completion/wrap_up, Risk resume, Product language,
Cedar, microphone prewarm, echo protection, segmented capture, phone formats,
SQLite/dashboard and offline Twilio/Vonage boundaries. No Router business prompt,
TTS voice or telephony architecture was changed.

## Actual Conversation Demo

All **nine cases passed in one matrix** using Chrome, a synthetic MediaStream,
actual Conversation Demo, real endpointing/WS/API/core, Cedar TTS and live STT where
listed. Every case asserts one customer/API turn and stopped microphone tracks.

| Case | Recognition provenance | Observed result |
|---|---|---|
| Russian да | Live Realtime | Visible `Да.`, confirmed, no recovery call |
| Russian нет | Live Realtime | Visible `Нет.`, existing segmented repair, no recovery call |
| Kazakh иә | Live Realtime | Visible `Иә.`, confirmed, no recovery call |
| Kazakh жоқ | Live Realtime | Visible `Жоқ.`, existing segmented repair, no recovery call |
| Russian да with first `No.` | Injected first; live bounded audio recovery | Visible `Да.`, phone accepted, business answer completed |
| Exact `No. → Да.` | Explicit first/second transcript fixtures | Confirmed full phone; no IIN fallback/restart/handoff |
| Exact `No. → No.` | Explicit first/second transcript fixtures | Same candidate/confirmation, no lookup/action/Router transition |
| Exact `No. → Иә.` | Explicit first/second transcript fixtures | Confirmed |
| Exact `No. → Жоқ.` | Explicit first/second transcript fixtures | Rejected through existing repair |

Evidence: ignored `work/confirmation-stt/browser-results-main.json` and screenshots.
The live recovery screenshot was inspected: the exact full read-back, visible `Да.`,
`find_client/get_policy` and completed business answer are present; supervisor phone
data remains redacted. No physical microphone was used. Live PSTN remains
**NOT RUN / pending_credentials**.

## Synthetic acoustic measurement

`data/speech/confirmation_utterances.json` has 16 RU/KK/mixed/uncertain/noisy phrases.
The live benchmark generated them in existing Cedar and Coral voices for **32 cases**.
Noise variants add small deterministic PCM noise. This is separate from the offline
fixture benchmark and from human-recording accuracy.

Fresh release run (`live-results-release.json`):

| Metric | Result |
|---|---:|
| First-pass decision accuracy | 23/32 — 71.875% |
| Conditional recovery cases | 13/32 |
| Recovery-pass final decision accuracy | 10/13 — 76.923% |
| Final decision accuracy | 29/32 — 90.625% |
| False confirm | **0** |
| False reject | **0** |
| Unresolved | 7/32 — 21.875% |
| Provider failures | 0 |
| Recovery added latency, median / maximum | 946 / 2409 ms |
| Recovery calls after valid first-pass yes/no | **0** |

Four unresolved cases were intentionally uncertain responses. The other three were
two mixed-language affirmatives and one noisy Kazakh affirmative; they remained
unresolved instead of being assigned a wrong decision. This sample does not establish
zero error for human callers. Both recognizers can still make correlated RU/KK mistakes.

The first live run is retained as `live-results.json`: zero false confirmations or
rejections, with two bounded-provider timeouts (20 seconds each), both failing safely.
The fresh release run is a separate evaluation, not an application retry. No per-turn
retry was added. Offline contamination fixtures scored 32/32 with zero wrong decisions;
their timings are mock timings and are not claimed as live latency.

## Reproduce

From the repository root, using configured server credentials only for live paths:

```powershell
.venv/Scripts/python.exe -X utf8 scripts/evaluate_confirmation_stt.py
.venv/Scripts/python.exe -X utf8 scripts/evaluate_confirmation_stt.py --live --run-label release
.venv/Scripts/python.exe -X utf8 scripts/validate_confirmation_browser.py --generate
.venv/Scripts/python.exe -X utf8 scripts/validate_confirmation_browser.py
# Separate terminal, with Conversation Demo on 5173 and installed Playwright:
node scripts/validate_confirmation_browser.mjs
```

`PLAYWRIGHT_MODULE` can select an already installed module. `CONFIRMATION_CASES`
selects browser cases; `CONFIRMATION_RUN` preserves separate attempt reports.
The loopback test server uses one active fixture session; its routes are never
registered in the production application. Live evaluation audio is synthetic only.

Skills actually used: agent-debugging, agent-evals, vercel:agent-browser.
