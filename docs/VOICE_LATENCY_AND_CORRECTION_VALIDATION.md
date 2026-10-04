# Voice correction and latency release validation

Date: 2026-10-04. Starting revision: `5e850d3` on
`codex/stage6-telephony-integration`. The user authorized release to main after the
offline and browser gates. The `545dc10` completion architecture is retained.

## Admission and correction

All sensitive identifiers still require a full spoken read-back and explicit final
confirmation, or a complete manual typed value under the existing policy. A recognizer
result cannot write business slots. Regions remain the only low-risk automatic path.

`StructuredConfirmationResponse` distinguishes confirm, reject, correction and unrelated.
Its private `IdentifierCorrection` contains target, old/new fragment, optional one-based
position (or last), and digits/letters/region segment. A local compositional RU/KK grammar
recognizes replacement operators, ordinal positions, explicit digit/letter names and
whole source-valid values. It does not infer replacements from similar characters.
ASR punctuation loss is supported; punctuation is not required to separate two explicit
replacement atoms. Multiple edits, mismatched old values and non-unique matches fail closed.

Examples covered by regressions:

| Pending | Reply | Result, still pending |
| --- | --- | --- |
| `945ABC02` | «Нет, вместо C — D» | `945ABD02` |
| `87775232862` | «Последняя цифра три» | `87775232863` |
| `SQ-OGPO-123456` | «Пятая цифра не пять, а девять» | `SQ-OGPO-123496` |
| Plate | «Екінші әріп C» / mixed position and Latin letter | Only specified position changes |
| Repeated sevens | «Вместо семёрки восемь» | One narrow position/value clarification |

Every successful edit is source-schema validated, remains private and gets another full
read-back. No Router, Composer, business lookup or segmented recapture is needed for the
correction turn. The customer's final yes admits exactly the candidate that was read.
Whole corrected values work too. Two meaningful correction/read-back cycles and one
ambiguity clarification are the maximum. Browser exhaustion disables automatic voice and
offers working keyboard input; phone exhaustion prepares a specialist handoff. Existing
negative-answer segmented repair, expiry and recognition-versus-lookup bounds remain.

STT confirmation context identifies only the field kind and the correction task; it never
puts the original private identifier into transcription prompts or keywords. Short
RU/KK/mixed replies retain the conversation language. Letter confusion regressions cover
A/B, B/D, C/S, M/N, P/B and E/A with explicitly supplied replacements.

## Recognizer race and endpointing

At commit, Realtime final and bounded `gpt-transcribe` run concurrently. For a whole
sensitive field, the first unique valid candidate authorizes **pending read-back only**.
An invalid first result waits for the other; two failures enter repair. The winning
transcript is bound to the existing one-use receipt. A completed second result can add
corroboration metadata, but cannot replace the candidate already presented. An unfinished
loser is cancelled and joined; no extra result provides admission authority after the
read-back starts. Cancellation bounds application work, but does not guarantee zero
provider billing for an already submitted request. Segmented drafts retain two-pass
corroboration. Ordinary confirmations/corrections make no second transcription call.

Browser omitted/null `pause_ms` selects local adaptive endpointing. Explicit 500–5000 ms
still selects the manual profile. Phone half-duplex timing remains unchanged.

| Browser context | Base silence | Stable complete partial permits |
| --- | ---: | ---: |
| Confirmation yes/no | 750 ms | 650 ms |
| Recognized correction | 900 ms | 800 ms |
| Region | 900 ms | 750 ms |
| Phone/IIN/plate/policy/claim | 1300 ms | 1100 ms |
| Ordinary dialogue | 1600 ms | No completeness shortening |

The same normalized partial must remain stable for at least 400 ms; local acoustic VAD
silence is always required. A transient regex match cannot commit. Resumed speech resets
the VAD timer. Frame batching and 32 ms VAD windows can add tens of milliseconds beyond
these configured values. `gpt-live-transcribe` retains manual commit and
`turn_detection: null`, following the [official transcription contract](https://developers.openai.com/api/docs/guides/realtime-transcription).

## Input lifecycle, echo and privacy

`BrowserVoiceInput` prepares the AudioContext/worklet and next WebSocket during TTS, reuses
one microphone stream within an active conversation, and activates PCM transmission only
after playback ends. Prepared UI explicitly says speech is not yet transmitted. A 400 ms
RAM ring is armed only in the final 400 ms of backend HTMLAudio playback and only with a
decoded playback reference. Clear silence/correlated TTS echo is zeroed; arbitrary prepared
audio is discarded. Browser echo cancellation and noise suppression remain enabled.
A bounded 300 ms reference-only echo tail also filters late speaker samples after `onended`.

An initial synthetic speaker-loopback test exposed late TTS echo becoming a turn. The
sample-aligned correlation search and echo tail fixed that reproducer. Exact-PCM unit
tests retain independent caller audio/first phonemes. Three final matrix echo trials and
a separate first-word gate produced no echo turn. This does not prove performance for
every physical speaker, room or headset; the real browser used timed synthetic mic input.
When a playback reference is unavailable, near-end pre-roll is disabled; prewarm remains.
Long provider setup failures can still prevent timely capture and surface an explicit error.

Pause disconnects the run/socket but retains hardware for the next turn. Voice disable,
end, reset, navigation/unmount and dispose stop tracks and close the AudioContext. A stop
cancels a pending readiness promise immediately; late microphone permission also stops
the returned tracks. Failed input preparation releases hardware. Setup/active deadlines,
PCM/backpressure limits and server concurrency bounds remain. Buffers are cleared per turn,
cancel and stop; no customer audio is persisted or logged.

Barge-in is **deferred**. Terminal replies and early critical Risk guidance remain protected
by the existing half-duplex flow. Twilio/Vonage duplex behavior is unchanged.

## Actual browser measurements

Chrome ran the actual production Conversation Demo, native AudioWorklet and WebSocket,
with live STT, Cedar TTS, Router/Composer and Risk. An isolated local FastAPI harness seeded
synthetic session state and injected synthetic spoken answers about 350 ms before the
assistant audio ended. This is not a physical microphone/acoustic test. Validation routes
exist only in `scripts/validate_voice_latency.py`, never the production app.

The three-repeat matrix contained 30 attempts: **26 complete passes**, three provider/network
failures before a voice turn (including two TTS HTTP 502s), and one correction follow-up
where ASR returned “Duh.” for synthetic «Да». That answer was not accepted: the corrected
full value was read again. No heuristic turns “Duh” into yes. The last full repetition
passed all ten cases. All 30 attempts stopped microphone tracks during cleanup.

Phone candidate accuracy was 3/3. The repeated-zero IIN fixture had 0/3 exact candidates;
all three safely requested repair without admission or lookup. Those are safety passes,
**not recognition accuracy successes**. Human-confirmed sensitive precision remains
unmeasured. No new automatic sensitive acceptance is possible through the race path.

The separate overlap gate passed echo, yes, digit correction and letter correction. It
explicitly checked the first words «Последняя» and «Нет», the corrected pending values,
full spoken read-back, final confirmation and track cleanup. Both corrections completed
without restarting collection. Insurance and Risk matrix cases entered wrap_up and their
spoken no-more-questions follow-ups ended the conversation.

Values below are milliseconds; each row has only 2–3 available first-turn timings, so
median and range are reported rather than suggesting a reliable per-case p95.

| Case | Timed n | VAD silence median | Endpoint → authoritative first audio median (range) | Estimated speech end → audio median |
| --- | ---: | ---: | ---: | ---: |
| Ordinary short reply | 2 | 1648 | 4630 (4612–4648) | 6278 |
| Yes confirmation | 2 | 816 | 7309 (6599–8019) | 8125 |
| Digit correction | 2 | 960 | 3568 (3450–3687) | 4528 |
| Plate-letter correction | 3 | 960 | 3889 (3855–4118) | 4881 |
| Phone | 3 | 1216 | 4947 (3863–5589) | 6163 |
| IIN repair | 3 | 1344 | 7756 (5982–7845) | 9100 |
| Region 02 | 3 | 928 | 6444 (6382–10804) | 7406 |
| Insurance request | 3 | 1664 | 7819 (7807–9855) | 9483 |
| Risk authoritative reply | 3 | 1664 | 10592 (10373–10962) | 12256 |

Pooled available first-turn timings (n=24, empirical nearest-rank p95):

| Metric | p50 | p95 |
| --- | ---: | ---: |
| TTS end → active input | **1.8** | **4.2** |
| Endpoint → authoritative first audio | 6413 | 10804 |
| Estimated speech end → authoritative first audio | 7389 | 12256 |

Untouched `5e850d3` frontend measured TTS-end→recording-ready **1486/1364/1330 ms**,
median **1364 ms** (n=3), against the same isolated backend. Current activation median
is **1.8 ms** (n=24; maximum 16.8 ms), meeting the requested <150 ms p50 in this setup.
The earlier baseline attempts were inconclusive due to harness isolation/origin and
provider failures; they are retained separately, not counted as latency measurements.
This comparison isolates lifecycle setup; it does not claim a universal network SLA.

The Risk row intentionally measures the authoritative response, not the earlier precaution.
The yes row includes subsequent business processing/TTS; fast acoustic endpointing alone
does not make the complete business response sub-second. Phone first valid candidate after
commit was median **564 ms**, range **549–1009 ms** (n=3); all went to read-back only.
Five correction read-backs are included even when a later final-confirmation ASR failed.
Unavailable timing samples are not assigned zero latency or removed from failure counts.

For the eight actual full identifier read-backs (phone plus successful minimal edits),
endpoint→first audio p50/p95 was **3876/5588 ms**; estimated speech-end→first audio was
**4979/6740 ms**. These are exploratory empirical percentiles from n=8, with repairs
excluded by outcome rather than mislabeled as full read-backs. The n=3 phone candidate
latency's empirical p95 is its maximum, 1009 ms; a larger corpus is needed for tail estimates.

Browser timestamps use `performance.now`; backend final/candidate durations use monotonic
`perf_counter`. Backend event durations must not be subtracted from browser absolute times.
Speech-end estimates add the measured VAD silence to browser endpoint→audio; they are not
human acoustic annotations. Timing logs contain fixed event names and numeric values only.

The prior precision run's total p50 ≈5927 / p95 ≈19006 ms used a different audio/STT harness,
not this complete browser reply metric. A direct percentage improvement would be misleading.
Unit tests prove that a fast valid result does not await a slow loser; the browser verifies
that the resulting read-back and confirmation still work. Ordinary speech, Insurance and
Risk passed the final repetition without clipped-fixture failures. Provider availability
and short-word/zero-sequence ASR quality remain practical limitations.

## TTS decision and lifecycle

Cedar and all existing RU/KK/general voice overrides are unchanged. Fresh Chrome prototype
RU request→first-audio samples were buffered 3732/1919/1758 ms and streaming 1966/1476/1693 ms:
medians **1919 vs 1693 ms** (n=3 each). One KK streaming sample was 1782 ms. Cancellation
stopped playback. The sample is too small for an SLA.

Production streaming is **deferred**: the shipped near-end echo gate uses a decoded complete
response, while streaming needs incremental reference alignment plus another cancellation,
fallback and phone-conversion gate. Shipping that rewrite here would expand the proven
surface for a modest measured median startup saving. Existing bounded buffered MP3, reset,
terminal state and fallback-only-before-first-audio behavior remain.

Official lifecycle checked on 2026-10-04: the [deprecation page](https://developers.openai.com/api/docs/deprecations)
announces removal on 2027-01-06 for `tts-1`, `tts-1-hd` and the listed dated
`gpt-4o-mini-tts` snapshots; the [model page](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)
marks this family deprecated. The [speech guide](https://developers.openai.com/api/docs/guides/text-to-speech)
still documents Cedar and streaming. No deprecated dated snapshot was newly pinned.
The configured alias stays unchanged for this release; a replacement model/voice migration
requires its own RU/KK listening, cancellation and echo validation before that deadline.

## Reproduction and release evidence

- Backend full suite: **1265 passed** (baseline 1216 retained).
- Frontend full suite: **106 passed** (baseline 97 retained), including cancellation while
  readiness is pending, bounded PCM, echo, no pre-activation transmission and runtime lifecycle.
- TypeScript/Vite, Ruff app/tests/script, Python format and changed frontend formatting passed.
- Existing dashboard format check passed with `--end-of-line auto`: default Prettier flagged
  the untouched Windows CRLF checkout. No dashboard source/style changes were made.
- Completion/policy relationship/Risk resume, Product language, receipt/privacy and structured
  precision regressions remain in the full suite. No canonical routing backlog was tuned.
- Final Docker rebuild/start: backend and frontend healthy. Four Stage 6 phone smokes
  passed with UTF-8 console output; the first Vonage invocation hit a Windows cp1251
  output-encoding error, then passed unchanged with `python -X utf8`.
- Focused security review passed: no high-impact issue found in the changed paths, zero
  configured provider credential matches in changed source/built JS and no tracked `.env`.
- Final rebuilt-Docker browser gate: **6/6** (echo, yes, digit correction, letter correction,
  Insurance, Risk), including both leading-word assertions, final confirmation, wrap_up,
  no-more-questions closure and all microphone tracks stopped.
- The post-push release receipt is `work/voice-latency/release.json`. A commit cannot embed its own SHA, so the
  post-push receipt records the exact integration/main/remote SHAs and ancestry checks.

Reproducible checks from repository root (existing dependencies, PowerShell):

```powershell
.venv/Scripts/python.exe -m pytest backend/tests -q
cd frontend
npm test
npm run build
cd ..
docker compose up -d --build
.venv/Scripts/python.exe -X utf8 scripts/smoke_phone_runtime.py
.venv/Scripts/python.exe -X utf8 scripts/smoke_twilio_runtime.py
.venv/Scripts/python.exe -X utf8 scripts/smoke_vonage_runtime.py
.venv/Scripts/python.exe -X utf8 scripts/smoke_stage6_integration.py
```

For the billable synthetic browser matrix: run `scripts/validate_voice_latency.py --generate`,
then that script without arguments on loopback 8013; open the production frontend on 5173.
Set `PLAYWRIGHT_MODULE` to an existing Playwright module if not installed locally; run
`VOICE_CASES=echo,short_reply,yes,digit_correction,letter_correction,phone,iin,region,insurance,risk`
and `VOICE_REPETITIONS=3` with `node scripts/validate_voice_latency.mjs` (set variables using
`$env:` in PowerShell). `measure_voice_startup.mjs` compares an untouched archived `5e850d3`
frontend preview on 5174, with the same isolated live backend. Its optional TTS prototype
uses `evaluate_tts_streaming.py` on 8011. These harnesses are development-only.

Ignored evidence: `work/voice-latency/browser-matrix-30.json`, `metrics.json`,
`browser-first-word-gate.json`, `browser-release-gate.json`, `startup-initial.json`, `startup-results.json`, test/build
logs and synthetic screenshots/audio. No customer audio is used. Timing evidence is
separate from the explicitly synthetic failure transcript used for diagnosis.

Focused security review follows input→private pending correction→final confirmation→typed
accepted value→business slot and browser hardware→RAM ring→active WebSocket. No new public
authorization surface, credential change, external destination or database migration is
introduced. Recognition metadata and timing logs contain no identifiers. Existing origin,
size, timeout, one-use receipt, expiry and read-only business boundaries remain. Configured
provider secrets are checked against changed source and built JS; `.env` is not tracked.
The user-supplied synthetic phone example can match `DEMO_TEST_PHONE`; it is fixture data,
not a provider credential. Physical acoustic echo and live PSTN are not covered by this review.

**Twilio LIVE PSTN: NOT RUN / pending_credentials.**
**Vonage LIVE PSTN: NOT RUN / pending_credentials.**

Skills used: agent-debugging, agent-evals, security-review, demo-readiness, OpenAI Docs;
agent-browser guidance with bundled Playwright as the available browser driver.
