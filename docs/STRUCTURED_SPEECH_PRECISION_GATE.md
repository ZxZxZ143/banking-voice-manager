# Structured speech precision gate

## Current interaction gate (2026-10-04)

The follow-up [correction and latency validation](VOICE_LATENCY_AND_CORRECTION_VALIDATION.md)
adds a race to **pending full read-back**, private RU/KK minimal corrections, adaptive
browser endpointing and prewarmed input. This supersedes the timing/repair rules below:
the first unique sensitive hypothesis may be read back even if the other recognizer
fails or disagrees. It is never accepted automatically. The pending value cannot be
replaced by a later recognizer result. The unused recognizer is cancelled; completed
results contribute only safe corroboration metadata. Segmented repair still waits for
both recognizers, and low-risk region admission is unchanged.

`StructuredConfirmationResponse` and `IdentifierCorrection` are local, typed private
objects. Corrections are resolved by position/segment or a unique old fragment, checked
against the original schema, fully read back and confirmed again. No Router, Composer
or lookup runs for a correction-only turn. There are at most two meaningful corrected
read-backs and one narrow ambiguity clarification. Browser exhaustion offers working
keyboard input and disables automatic voice capture; phone exhaustion prepares handoff.
Confirmation STT now receives structural correction hints without the pending value;
it retains no second-pass PCM and makes no additional bounded transcription call.

The original `545dc10` completion behavior and `5e850d3` admission rules remain covered
by the existing suites. Release evidence and current lifecycle limits are in the new
report. All original measurements below are historical, not a post-correction score.

## Original 5e850d3 validation

Implemented on `codex/stage6-telephony-integration`, based on completion hotfix
`545dc10`. No main merge, PSTN activation, credential changes, dashboard changes,
new business stage, or canonical routing tuning.

## Admission contract

`speech/structured/policy.py` owns the typed `StructuredRecognitionPolicy`,
`RecognitionRisk`, `RecognitionOutcome`, `RecognitionHypothesis`, and
`AcceptedStructuredValue`. A normalized candidate is evidence, not a business value.
Only a typed accepted value reaches speech-controlled business slots. Router output,
literal parsing of a voice transcript, and a receipt alone cannot bypass this gate.
The contact-change `new_value` field also uses the phone gate when `contact_field=phone`;
confirming a replacement contact does not replace the current identification phone.

| Kind | Risk | Reason |
|---|---|---|
| region_code | low | Coarse registration/pricing category; does not identify an account or person |
| vehicle_plate | medium | Identifies a vehicle; omitted letters can still produce valid syntax |
| policy_number | medium | Selects a specific insurance record |
| claim_number | medium | Selects a specific claim record |
| phone | high | Contact and cross-record client lookup identifier |
| iin | high | Personal identity and cross-record client lookup identifier |

The initial policy deliberately requires **full read-back confirmation for all five
sensitive kinds, including consensus**. Two models from the same provider can make
correlated mistakes on the same audio. This was observed again in this validation.
Confirmation is transcription verification, not authentication or permission to perform
an irreversible business operation.

| Evidence | Outcome |
|---|---|
| One valid low-risk region | accepted, low_risk_schema |
| Two matching sensitive candidates | confirmation_required; consensus=true |
| Only one usable sensitive candidate, including second-pass outage | confirmation_required; consensus=false |
| Conflicting/ambiguous candidates or no valid candidate | repair_required; never choose one conflicting value |
| Explicit scoped yes to a pending full read-back | accepted, customer_confirmation |
| Complete valid typed correction while verification is pending | accepted, manual_entry |
| Failed bounded verification | manual_fallback, prepared specialist handoff |
| Expired pending verification | exhausted, prepared specialist handoff |

Acknowledgements such as «Хорошо» are not identifier confirmation. The verification
grammar accepts only complete explicit RU/KK affirmative/negative replies in a pending
confirmation step. Longer qualified replies are not silently treated as yes. Ordinary
conversation intent selection continues to use the unchanged semantic Router.

## Parallel recognizers and limits

For phone, IIN, policy, claim and plate collection, `relay_stream.commit()` launches
one bounded gpt-transcribe task on the retained PCM while awaiting gpt-live-transcribe.
Neither recognizer is seeded with the other's output or a known customer value.
Browser and PhoneRuntime share this implementation. For low-risk regions the second
pass remains conditional on first-pass failure. Confirmation yes/no uses ordinary
medium-delay STT without retaining audio or making a second transcription call.

The bounded request has zero retries and a 20-second deadline starting at launch.
Realtime retains its separate 30-second post-commit deadline. Cancellation, disconnect,
timeout and completion cancel/join outstanding tasks and clear the retained PCM buffer.
Existing 120-second audio and 150-second transport limits remain. No runtime audio files
are created. Safe metadata records first-pass time, bounded duration and additional
bounded wait after the Realtime final; those are distinct measurements.

## Bounded capture

`insurance_manager/speech_capture.py` is an application step before slot mutation and
lookup, separate from completion/wrap_up and from lookup failure memory. It performs
no Router/Composer call for a recognized verification step.

- One full read-back, with digits and Latin letter names spoken individually in RU/KK.
- One unclear confirmation may repeat that question; a second ends in handoff.
- A rejection or conflicting initial result permits one segmented capture sequence.
- Phone: 4 + 3 + 4 digits including country/domestic prefix; IIN: 6 + 6 digits.
  Policy/claim: literal prefix then 6 digits. Plate: 3 digits, 2–3 letters, 2 region digits.
- Each segment needs two matching hypotheses. Failed/disagreeing segments hand off;
  partial pieces never enter business slots and are never filled from a database.
- The assembled source-valid value receives one final full confirmation. Rejection
  cannot restart segmented capture. Thus there are at most three segments and four
  confirmation replies per capture, with an absolute 180-second admission expiry.
- A complete text correction is available through the existing text input. Telephone
  callers get a prepared specialist handoff, without instructions to use a keyboard.
- A direct new business request routes normally and discards the abandoned candidate.
  Risk guidance retains unfinished work; its acknowledgement resumes the exact question.

Pending data is bound to scenario and expected slot, excluded from Pydantic public/model
serialization and repr, and cleared on acceptance, abandonment or terminal state.
Expiry is checked on use; this is not a scheduled memory-erasure guarantee. The existing
bounded in-memory session store still owns idle-session lifetime. Recognition repair
does not write unavailable/failed lookup values or attempt a client lookup.

## Privacy and wire compatibility

Recognition receipts remain one-use, bounded to 100 entries/120 seconds and bound to
session, turn, expected slot and transcript hash. Clients never submit canonical values.
Unreceipted voice transcripts also require confirmation; an unsolicited sensitive field
from an ordinary voice turn is collected through the gate, not copied from Router slots.

The caller receives the full read-back to check it. Public state/history, model context,
trace, analytics, logs and SQLite do not receive pending candidates or partial fragments.
The raw first transcript remains in the existing local voice UI. Safe final metadata adds
`outcome`, `risk`, `consensus`, `verification_method` and `second_pass_wait_ms`; no value,
candidate list, confidence guess, raw bounded transcript or audio is added to that wire.
Existing frontend/phone terminal statuses and provider settings are unchanged.

## Validation on 2026-10-04

Deterministic suite: **1216 backend tests** (45.01 s), **97 frontend tests**. The original 27
completion regressions are unchanged and pass. There are 56 new precision/regression
checks, including all five sensitive fields, RU/KK confirmation, segmented reconstruction,
disagreement/outage, finite repair, expiry, manual correction, privacy, parallel launch,
cancellation, Risk resumption, direct requests, wrap_up/ack/more/end and Cedar preference.
Recognition confirmation uses the existing `slot` expected-answer contract; Router and
Composer schemas were not expanded. An unrelated question cancels the prior read-back
authority, while a Risk acknowledgement resumes it. Backend/script Ruff and formatting,
diff whitespace checks, and a configured-secret scan of the changed files passed.
HTTP/WebSocket tests and the PhoneRuntime lookup-exhaustion flow now explicitly confirm
each sensitive identifier. All four offline phone/Twilio/Vonage/current-core smokes pass,
including SQLite restart consistency. No actual PSTN call was attempted.

Completion helpers, Router prompt/schema/validation, Composer, completion dataset and
original completion tests are byte-for-byte unchanged from `545dc10`. The prior live
14/14 completion and canonical primary 99/104 results remain historical baseline evidence;
neither live routing benchmark was rerun or tuned in this task.

### Fresh 112-audio run

Existing synthetic audio, fresh Realtime + bounded STT, concurrency 3, no resume/retries:
`work/structured-speech/openai-precision.json`. Expected labels never enter model inputs.
This is single-utterance gate measurement, **not** a human-confirmed identifier benchmark.
The shared TTS/STT synthetic-corpus and unreviewed-waveform limitations of
`STRUCTURED_SPEECH_RECOGNITION_VALIDATION.md` still apply.

| Measurement | Result |
|---|---:|
| Available utterances / attempted | 101 / 112 |
| Provider failures | 11: 7 DNS failures, 4 timeouts |
| Accepted automatically | 9, all correct low-risk regions |
| Sensitive identifiers automatically accepted | **0** |
| Confirmation required | 56 |
| Correct candidates awaiting confirmation | 52 / 56 = 92.86% |
| Candidates with two-recognizer consensus | 45 |
| Correct consensus candidates | 44 / 45 = 97.78% |
| Repair required | 36 |
| Bounded-pass failures among completed utterances | 2 |
| Harness total latency p50 / p95 | 5927 / 19006 ms |
| Realtime after-commit p50 / p95 | 1983 / 5815 ms |
| Additional bounded wait p50 / p95 | 0.002 / 1947 ms |

The old five false accepted plates were `vehicle_plate-02/04/08/10/20`. In this fresh
run, 02/08/10/20 still produced wrong candidates but all required confirmation; 04 hit a
timeout and was not accepted. Crucially, **02 had matching wrong hypotheses**. Consensus
alone would still have admitted it. No exact plate or benchmark label was special-cased.

There were zero wrong automatic acceptances, but the automatic acceptance denominator
contains only regions. **Sensitive accepted precision after human confirmation is not
measured here**, and must not be reported as 100%. The old 62% canonical coverage is not
directly comparable to the new 9% automatic coverage: the new policy defers sensitive
values. Model confidence, human confirmation errors and real customer recordings remain
limitations. Provider failures were retained, not rerun away. Timing excludes human
confirmation and does not establish a controlled before/after customer latency gain.

The provider-call bound is two transcriptions per sensitive whole/segment utterance,
one ordinary transcription per confirmation, and no new recognition retries. Actual API
charges were not measured. Rejections can require up to three additional dual-STT segments.

Reproduce from the repository root:

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest backend/tests -q --basetemp=work/precision-tests
.venv/Scripts/python.exe -X utf8 scripts/evaluate_structured_speech.py --provider openai --report-tag precision --concurrency 3
```

The audio command uses existing synthetic PCM and configured server credentials. Preserve
the existing report before intentionally rerunning it. Initial restricted test/smoke runs
could not access Windows temporary directories; normal authorized reruns passed. No test
fix changed the filesystem sandbox or real provider credentials.

Skills used: agent-debugging, agent-evals, security-review.
