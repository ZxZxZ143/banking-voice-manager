# Segmented identifier capture hotfix

Date: 2026-10-04. Base: `62596fa`; branch: `codex/segment-recognition-hotfix`.
This is a focused repair of segmented capture. The whole-field admission gate,
minimal corrections, Insurance completion/Risk behavior, Cedar and Stage 6 remain.

## Reproduction and cause

The original regression entered phone repair, then received “Восемь семь семь семь”
from Realtime while bounded transcription failed. Before this patch, the new test
expected `awaiting_user` but received `handoff`. `advance_capture` required both a
candidate and consensus for every part, treating one imperfect part as exhaustion
of the entire identifier. It also rewrote leading domestic 8 to 7 before read-back.

## Application-owned segment policy

`StructuredRecognitionPolicy.decide_segment` returns evidence and a private draft
candidate; it never returns `AcceptedStructuredValue`.

| Evidence for the current part | Application action |
|---|---|
| Two distinct recognizers agree | Store private part; request next part |
| One unique valid result; other unavailable, invalid or ambiguous | Read only that part back; require explicit yes |
| Two unique valid results disagree | Choose neither; repeat only that part once |
| No usable result | Repeat only that part once |

`segment_attempts` belongs to each part. Its limit is **two customer turns**:
initial recognition plus either a repeat or segment confirmation. A repeat that
still lacks agreement exhausts the budget; it does not add a third confirmation
turn. Rejected/unclear segment confirmation also exhausts that part. Completing a
part leaves the next part's budget unused. Previously verified parts remain private.
The existing 180-second capture lifetime remains an additional bound.

This applies to phone first/middle/last, IIN first/last six, policy and claim
prefix/digits, and plate digits/letters/region. A segment yes only stores a draft.
Complete assembly receives a full read-back and requires a separate final yes.
Only then does `AcceptedStructuredValue` reach slots, lookup memory and lookup.

On exhaustion, the browser offers full keyboard entry and stops automatic voice
capture. Existing explicit `manual_entry` policy schema-validates complete typed
input. PhoneRuntime has no keyboard capability and prepares specialist handoff,
retaining the active problem, safe fields and ManagerSummary. Recognition attempts
do not increment lookup attempts or mark identifiers unavailable.

## Spoken and canonical phones

Private `spoken_value` / `spoken_candidate` and `phone_input_style` preserve the
customer's source form through full read-back and corrections:

| Source form (synthetic) | Private style | Parts | Accepted canonical value |
|---|---|---|---|
| 87775232862 | domestic_8 | 4 + 3 + 4 | +77775232862 |
| 77775232862 | international_7 | 4 + 3 + 4 | +77775232862 |
| 7775232862 | national_10 | 3 + 3 + 4 | +77775232862 |

Phone parts retain their source digits; 8777 and 7777 are conflicting draft parts.
The full pending source is schema-checked without replacing its spoken 8. Canonical
normalization is computed for hypothesis comparison, but only the final accepted
value is committed as +7. A national form is inferred only from an unambiguous
ten-digit source beginning with 7; truncated ten-digit domestic-8 input remains
invalid. Unknown source style retains the existing 4 + 3 + 4 repair prompt.

## Privacy and unchanged boundaries

Drafts, candidate read-backs and counters live only in excluded in-memory capture
state. They are absent from public state, history, traces, SQLite events and logs.
Public history retains redacted markers. Cloud hints contain field/part structure,
never the private candidate. Recognition metadata adds only allowlisted
`segment_evidence`: agreement/single/conflict/unusable. No frontend, dashboard,
provider credential, telephony adapter or completion architecture changes.

## Endpointing and cloud-call comparison

Browser segments use 800 ms silence, or 650 ms after a complete partial stays stable
for 400 ms. Confirmation retains 750/650 ms and never launches bounded STT. Local
VAD silence is still required. Phone half-duplex and its endpoint setting are unchanged.

The bounded segment recognizer still launches concurrently with the Realtime final.
Small live first-phone-part pilot, measured from that part's endpoint to the next
part's prompt/active input (includes TTS, and the extra spoken yes where required):

| Path | Samples | Next prompt begins | Next input active | ASR calls | Extra TTS replies |
|---|---:|---|---|---:|---:|
| Realtime result + segment yes | 2 | 13.071 / 14.191 s | 18.178 / 18.601 s | 2 | 1 |
| Concurrent Realtime + bounded agreement | 2 | 17.453 / 2.671 s | 21.819 / 6.790 s | 2 | 0 |

Both dual-STT samples reached the next part correctly; the slow sample's later last
part encountered a bounded-STT timeout and safely requested segment confirmation.
The single-STT comparison deliberately makes bounded unavailable immediately without
a cloud request, so its two actual ASR calls are the segment and spoken yes. A real
failed bounded request may add latency/cost beyond this comparison.

**Keep concurrent dual STT as the default.** The normal successful dual sample was
substantially faster; the one-STT path adds a customer turn and TTS call and does not
reduce ASR call count once its yes is included. The network-degraded dual sample was
slower, so this pilot does not establish a general latency distribution or dollar-cost
claim. Actual provider charges were not measured. Both paths have the same final
admission requirement; the single-result path is now a working recovery path.
Measured first-part endpoint silence was 832–864 ms, inside the target band.
Whole-field race/cancellation behavior is unchanged.

## Validation evidence

- Before-fix screenshot regression reproduced: immediate handoff on missing second STT.
- Full backend: **1322 passed**, retaining the 1265-test baseline and adding 57 cases.
- Full frontend: **106 passed**; TypeScript/Vite production build passed.
- New deterministic matrix covers all five kinds in RU/KK, independent budgets,
  consensus/single/retry, browser/phone exhaustion, all three phone styles, final
  minimal correction, lookup isolation, and private SQLite/log/history projections.
- Existing completion/context/Risk and correction/echo/lifecycle suites remain in
  the full baseline. No canonical routing backlog tuning or fresh routing score claim.
- Ruff app/tests and affected validation scripts, format checks and `git diff --check`
  passed. Run Python lint from `backend`, as in the existing project checks.
- Docker build/start passed; backend and frontend healthy, analytics healthy, both
  telephony providers disabled. The first build failed fetching a Docker Hub token
  (`unexpected EOF`); the subsequent build succeeded.
- Four Stage 6 offline smokes passed: PhoneRuntime, Twilio, Vonage and shared
  core/Risk/SQLite integration. These use explicitly labeled fixture providers.
- Credential scan: 415 source/bundle files, one configured provider secret checked,
  zero exact matches and zero tracked real `.env` files. Demo phone fixtures are not
  provider credentials and are not included in the credential-value scan.
- Browser: all five paths below have completed successfully across the recorded runs.
  This is coverage after retries, not an uninterrupted five-case reliability score.

| Conversation Demo path | Observed result |
|---|---|
| A: Whole failure → one valid first phone part → spoken segment yes | Next parts collected; source 8 retained; full yes admits canonical +7 |
| B: First-part conflict → repeat same part → agreement | No early handoff; all parts assembled; full yes admits the phone |
| C: Repeated conflict | Keyboard available, voice stopped, complete typed phone accepted as manual_entry |
| D: IIN whole failure → six + six | Both private parts assembled; full read-back and yes precede lookup |
| Comparison: two STT agree on phone parts | Private parts advance without extra yes; final full confirmation still required |

Successful runs assert stopped microphone tracks and zero lookup/accepted value before
final confirmation (or complete explicit manual entry). The IIN full-read-back screen
was also inspected: caller prompt present, supervisor transcript redacted, no lookup.
The harness allows at most one repeat of final yes if the exact correct full draft is
still pending, no lookup occurred and no actions ran. It never confirms a mismatched
segment fixture or changes the application's budgets.

Earlier attempts are preserved in ignored JSON reports: seven recorded case failures
across the pilot/retries (four provider/voice timeouts, one safe segment confirmation
where the earlier harness expected direct assembly, one unusable IIN segment, and one
unrecognized final yes). The first harness also had a misplaced dual-case branch that
was fixed before the matrix rerun. All these are distinguished from application
handoff or false acceptance. No wrong identifier was admitted in the recorded cases.
An IIN attempt with an injected unavailable second recognizer safely repeated the
unusable first result; the final IIN gate used both live recognizers. Deterministic
RU/KK tests cover single-recognizer confirmation for IIN and all other kinds.

`scripts/validate_segment_capture.py` is a loopback-only test server on port 8015.
It uses actual Realtime STT and Cedar TTS, with explicit test-only initial whole
failure and selected bounded-STT outage/conflict injection. Unmodified segment and
yes turns use live providers. `scripts/validate_segment_capture.mjs` drives the actual
Conversation Demo with a synthetic MediaStream. It asserts no lookup/acceptance
before final confirmation, source read-back, bounded fallback and stopped tracks.
It does not simulate successful ASR for ordinary segment turns. Results/audio/screenshots
remain under ignored `work/segment-capture/`; test routes are never mounted in production.
Successful-case provenance and all attempt statuses are collected in
`work/segment-capture/release-gate.json`; raw failed-run files remain alongside it.

Physical microphone validation is **not performed** by browser automation. Live
Twilio/Vonage PSTN remains **NOT RUN / pending_credentials**.

Reproduce the browser gate from the repository root (separate terminals):

```powershell
.venv/Scripts/python.exe -X utf8 scripts/validate_segment_capture.py --generate
.venv/Scripts/python.exe -X utf8 scripts/validate_segment_capture.py
# With Docker Conversation Demo running on 5173, and Playwright available:
node scripts/validate_segment_capture.mjs
```

`PLAYWRIGHT_MODULE` can select an already installed Playwright module. `SEGMENT_CASES`
can select single, dual, disagreement, keyboard or iin. This harness is sequential;
its fault-injection seed belongs to one active test session at a time.
