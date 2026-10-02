# Stage 4 — Fraud & Security and shared advisory Risk Intelligence

Validated on 2026-10-02 UTC, from current `main`, following
outbound baseline `deef9f2`. Model: `gpt-4.1-mini`. All Stage 4 conversations/data/audio
are synthetic. Local evidence lives in ignored `work/`; secrets, personal demo identifiers,
raw evaluation artifacts, screenshots and audio are excluded from Git.

## Architecture and authority

Five production packs remain manually selected: Insurance Manager, Deposit, Card, Loan,
and consultative `fraud_security`. The sales packs retain their pre-call campaign authority.
Customer speech and Risk signals cannot select, suspend or forward to another pack.
The existing Insurance Router/Composer, sales prompt, catalogs and canonical evaluation
data were preserved. O11 remains explicit backlog, described below.

`app/risk/` is shared infrastructure outside the packs. Core masks authentication values,
then uses a conservative candidate precheck. Ordinary business turns skip the Risk model.
A candidate receives one structured SDK call: `max_turns=1`, zero tools, tracing disabled,
`store=False`, zero provider retries, 1,000 output tokens, default eight-second deadline
(`RISK_TIMEOUT_SECONDS`, maximum 15). Failure is visible as unavailable/invalid output,
nullable relevance and precautionary guidance; it is never reported as a successful NONE.

The strict `RiskInput` firewall exports only current masked text, language, text/voice
channel, active assistant ID, and `RiskContext` containing stable prior signals, a safe
pending-question enum and response language. No InsuranceContext, SalesLeadResult, client
identity, whole conversation, catalog, hidden prompt, Settings/environment or tools enter
the Risk call. Risk additionally masks phone/IIN, email and URL values.

Reported risk causes source-based guidance and retains the exact private business state,
result and lifecycle, including completed sales leads and Insurance awaiting-user status.
Its routing discriminator is `security_guidance`; no business model/tools run on that turn.
The next ordinary message continues the selected pack. Low-confidence signals still get
safe advice without changing business data. Public projections come from the pack itself.

The manual Fraud pack reuses that one semantic assessment, avoiding a second Fraud model
call. Its private context contains stable safe facts, case/transaction kind, pending and
already-asked questions, guidance history and bounded clarification attempts. It asks at
most one question per turn, never the value of a secret. A typed semantic yes/no answer is
applied to the known question contract; regexes do not classify that answer. Opening turns
cost zero model calls. RU/KK rendering is grounded; mixed speech uses its dominant grammar.

`FraudCaseResult` retains repository `status`, `completed`, `handoff`, plus `case_type`,
`case_status` (open/informed/needs_review), safe signal facts, optional transaction kind,
assessment and guidance history. Explicit operator requests use
**«Конечно, передаю диалог оператору.»**. Exposed authentication, installed remote access,
completed coerced transfers, lost card/account concerns and clarified unknown operations
prepare a normal application handoff. No real operator dispatch or banking action occurs.

`RiskAssessment` contains analyzed/unavailable/invalid-output status, nullable relevance,
advisory none/low/medium/high/critical triage, stable signals, recommended action,
enum-derived explanation and policy guidance IDs. These are neither fraud probabilities
nor credit/trust scores or legal conclusions. Actions are strictly `none`,
`show_security_guidance`, `security_review`, `urgent_security_review`, `operator_handoff`.
There is no block/freeze/reversal/product-rejection capability.

The stable 15-signal taxonomy is:

```text
bank_impersonation                 otp_requested_by_third_party
otp_disclosed                      credential_disclosed
pin_or_password_requested          cvv_requested
suspicious_link                    remote_access_requested
remote_access_installed            unknown_transaction
account_takeover_concern           unauthorized_contact_change
transfer_under_pressure            lost_stolen_card
coerced_transfer_sent
```

## Source policy and immediate advice

`data/security/policy.json` explicitly identifies itself as synthetic Merei Demo Bank
guidance, not the official policy of a real bank. Eleven RU/KK advice items and five safe
questions cover secret sharing, suspicious calls/links, remote control, safe-account
transfers, unknown operations and verification through independently opened official
bank/insurer channels. Replies do not invent legal claims or fetched URL reputation.

`POST /api/security/precaution` performs a zero-model, session-free source lookup. On
security candidates the common frontend calls it in parallel with the authoritative
message request and speaks its short advice immediately. It produces no score/signals,
does not mutate state and cannot switch assistants. Capture remains stopped through both
the early cue and the final response. One canonical assistant reply remains in history;
the already-spoken sentence is removed only from the remaining audio, avoiding repetition.
Optional cue failure leaves the real message and its visible errors intact.

The normal six-field API response is preserved; `risk` is additive and omitted when the
gate skips analysis. Typed wire variants cover Insurance, Sales, Fraud and security advice.
Risk UI allowlists enum values and presents unavailable distinctly. FraudCaseResult has
its own view. Trace exposes advisory metadata, active pack and precheck/agent timing.

## Tests and live evaluation

All 603 original backend and 43 original frontend tests remain. The registry expectation
adds the fifth pack; the existing voice HTTP assertion now also checks `channel=voice`.
No old test was deleted or weakened. Final results:

| Check | Result |
|---|---:|
| Full backend suite | 648 passed |
| Full frontend suite | 49 passed |
| Backend Ruff check / format | passed |
| Frontend typecheck / production build | passed |
| Live private-state and manual-selection smoke | passed |

New regressions cover strict SDK/output/input contracts, private pack isolation,
ordinary gate skipping, failure visibility, source advice, authentication masking,
RU/KK yes/no continuation, repeated-question prevention, exact handoff, lifecycle
preservation at low confidence, API union compatibility, manual selection and one final
voice event/one user turn. Frontend tests also cover early advice before the pending model
response, canonical history and cue failure.

The separate frozen synthetic dataset has 50 cases / 57 Fraud turns, 33 positive and
17 negative first-turn examples, seven multi-turn cases, 33 RU and 17 KK target replies.
F25/F26 are mixed utterances with KK/RU dominant grammar respectively. First-turn Risk
checks exercise all four business modes. Expected labels stay in the evaluator, never
in production inputs/prompts. Raw evidence is retained without per-call retry.

Final live evidence: `work/stage4-fraud-risk-v3.json`; corrected offline scoring:
`work/stage4-fraud-risk-final-scored.json`. An unavailable negative was initially counted
as TN by the first evaluator; scoring was corrected without repeating calls, and new
runs now apply the corrected rule. The table below uses the corrected counts.

| Shared Risk metric | Raw count / result |
|---|---:|
| Valid confusion matrix | TP 33, FP 0, FN 0, TN 16 |
| Unavailable | positive 0, negative 1 (F33 timeout) |
| Relevance precision on available assessments | 33/33 = 100% |
| Relevance recall on available positives | 33/33 = 100% |
| End-to-end relevance / structured / level / action | each 49/50 = 98% |
| Exact signal-set match, including unavailable failure | 47/50 = 94% |
| Signal micro counts | TP 36, extra 2, missing 0 |
| Signal precision / recall | 36/38 = 94.74%; 36/36 = 100% |
| HIGH/CRITICAL false positives | 0/17 benign cases (16 assessed, 1 unavailable) |
| Reply language, model-called cases | 41/42; available only 41/41 |
| Gate calls / skips | 42/50 calls, 8/50 skips |

Action correctness uses exact expected triage mapping: NONE→none, LOW/MEDIUM→guidance,
HIGH→security_review, CRITICAL→urgent_security_review. This is an evaluation expectation,
not a punitive application rule. Extra signal annotations: F08 also reported remote
access requested; F26 also reported password requested. Neither is a benign HIGH alert.
F33 was general phishing education and returned visible unknown, not confirmed safe.

| Fraud metric | Raw count |
|---|---:|
| Complete cases | 47/50 |
| Structured / language / fixed pack / status | each 57/57 |
| Source-grounded advice / at most one question | each 57/57 |
| Intent | 55/57 |
| Risk relevance | 56/57 |
| Expected safe pending question | 11/11 |

Remaining Fraud mismatches: F37 normal transfer processing and F39 KK policy validity
were classified as general_info rather than out_of_scope; risk remained NONE. F49 explicit
operator request retained prior PIN-request risk while the label expected none; the exact
terminal reply and handoff passed. Labels have not been changed to hide the mismatch.

Two development runs remain in ignored evidence: v1 (six-second deadline) had five Risk
and five Fraud timeouts, with two precheck misses; v2 had seven Risk and 15 Fraud timeouts.
The final eight-second run had one Risk timeout and zero Fraud timeouts. These are distinct
whole evaluation runs, not concealed retries. Precheck/language fixes were confined to
Risk/Fraud; Product and Insurance prompts were not tuned.
Final source-rendering review prioritizes urgent exposure/installed-access advice over
earlier request facts; RU/KK multi-turn tests check the urgent first sentence. This
presentation-only change does not change Risk model decisions or evaluation labels.
Final live cross-pack smoke was repeated successfully after that change:
`work/stage4-cross-release.json`, with exact Card/Insurance private-state/result/lifecycle
preservation, resumed ordinary turns, manual Fraud exposure handoff and benign SMS.

## Existing regressions and O11 backlog

| Live regression | Result |
|---|---|
| Canonical Insurance Router, 104 utterances | primary 101/104; full 100/104; no provider/invalid failures |
| Multi-intent Router subset, 13 | primary 12/13; full 11/13; recall 0.923 |
| Insurance Conversation final, 32 cases / 91 turns | complete 29/32; provider 91/91; language 91/91 |
| Insurance continuation / terminal / grounded facts | 26/26; 15/15; 18/18 |
| Insurance no premature handoff / repeated question | 76/76; 36/36 |
| Insurance act progression / reset / Composer validity | 22/22; 35/36; 89/91 |
| Product, 40 cases / 45 turns | complete 34/40; intent 43/45; language 41/45 |
| Product structure / grounding / fixed campaign | each 45/45 |
| Product continuation / manual policy / no auto switch | 12/13; 8/8; 8/8 |
| Outbound, 12 cases / 22 turns | complete 11/12; intent 21/22 |
| Outbound structure / grounding / language / fixed campaign | each 22/22 |
| Outbound continuation | 10/10 |

Insurance Router mismatches: U030 SC15→SC16, U035 SC18→SC14, U087 lost SC19 from
SC19+SC35, U090 lost SC18 from SC14+SC18. Its CLI saved all results/report, then exited
with a CP1251 UnicodeEncodeError during final stdout printing. Saved results were read
as UTF-8; model calls were not repeated merely to repair console encoding. Canonical
dataset SHA256 remains `4623e6f590715ac0e2e2119b2c475d0408f2ab9a7fd3c05a0cabd03b0239751b`.

Final Insurance dialogue failures: D01 one progress-reset mismatch; D11/D32 each one
Composer unsupported-claim validation fallback. Initial whole dialogue run was 27/32,
with one provider failure; the later complete rerun was 29/32. Both artifacts are retained.
Product failures: P01/P11 intent, P21/P25/P28/P30 language, P30 next action.
O11 is the known Card→Deposit utterance classified as decline instead of out_of_scope.
It still preserves the Card campaign. This was intentionally left as Product backlog.

## Latency

Final 50/57-case run, measured with monotonic backend timers; p95 uses nearest rank.

| Path | Samples | p50 | p95 | Max |
|---|---:|---:|---:|---:|
| Risk precheck | 50 | 0.10 ms | 0.31 ms | 0.89 ms |
| Risk Agent, including one timeout | 42 | 1,302 ms | 2,278 ms | 8,009 ms |
| Full Fraud backend turn | 57 | 1,298 ms | 2,946 ms | 5,505 ms |
| Existing Insurance dialogue backend | 91 | 3,620 ms | 7,187 ms | 15,851 ms |

Live cross-pack smoke: ordinary Card continuation 1,634 ms and Insurance continuation
3,715 ms; respective prechecks 0.065/0.099 ms, no Risk model. Security-only detours took
1,391/1,529 ms with Risk agents 1,389/1,528 ms and no business models/actions. These are
two measured examples, not a claim of statistically proven latency improvement.
Irrelevant security candidates can still add an assessment before the business response.
Ordinary turns add only the small gate cost, and make no extra precaution HTTP request.

Browser early safety audio started 839 ms after the Card incident submission, while the
Risk Agent took approximately 1,630 ms. This measures speech synthesis onset, not audible hardware or
full STT-to-reply latency. Further browser/voice evidence is recorded below.
The local zero-model precaution HTTP roundtrip was 61.78/19.23/3.00 ms for three candidate
requests, and 3.01/3.01/2.99 ms for three ordinary requests returning no advice. The latter
were direct measurement requests; ordinary runtime turns do not call this endpoint.

## Browser, voice and Docker evidence

The actual in-app browser used the final Docker stand at `127.0.0.1:5173`, with real SDK
responses and browser speech synthesis. Card opened proactively, captured cashback,
received an SMS-code incident, showed HIGH and kept its SalesLead/preferences/campaign.
The next opening question continued CARD-REWARD. Manual Fraud selection then displayed
its own safe facts/question. A disclosure turn timed out at eight seconds and visibly
showed unavailable with precautionary advice. A subsequent explicit operator request
produced CRITICAL, needs_review and exactly «Конечно, передаю диалог оператору.»;
the runtime entered handoff, with no automatic assistant switch.

Insurance independently opened SC06 with Turkey and pending `trip_start`. A suspicious
insurer-link turn showed MEDIUM/source advice, retained Insurance and awaiting_user, with
first safety audio at 841 ms and Risk Agent approximately 1,590 ms. The next date/duration
reply continued SC06, retained Turkey, accepted 2026-10-20 and asked `trip_end`. Exact
private state/result/lifecycle equality is additionally covered by the live core smoke.

Real browser voice evidence used `work/stage4-security.wav`, generated by Windows speech
synthesis: PCM16 mono 24 kHz, approximately 4.8 seconds. The file went through the existing
WebSocket uploader and real streaming STT, yielding **«Мне позвонили из банка и просят
назвать код из СМС.»**. DOM history contained exactly one customer entry; the trace was
turn 2 (opening plus one voice final), active `card_promoter`, HIGH with bank impersonation
and third-party code request, and no pack switch. The canonical response contained the
secret-sharing warning and independently opened official-channel advice.

Measured voice STT after commit was 710 ms; first safety audio after the final transcript
was 219 ms, Risk Agent approximately 1,380 ms and browser TTS first audio 197 ms. Installed
voice was Microsoft Irina, ru-RU. After the response, the runtime resumed listening and
microphone capture; capture was then cancelled to prevent unrelated background input.
Microphone was stopped while preparing the clean file session. An earlier chooser attempt
while capture was busy timed out; it did not count as a passing file test. The successful
session was fresh. Actual audio hardware output was not separately instrumented.

Screenshots are local only: `work/stage4-card-risk.png`, `work/stage4-fraud-handoff.png`,
`work/stage4-insurance-risk.png`, `work/stage4-insurance-resume.png`,
`work/stage4-voice-full.png`, and compact `work/stage4-voice-risk.png`.

Clean Compose down/up --build was executed without deleting volumes, then the final
frozen production code was rebuilt. Both existing services use loopback ports only,
and backend runs as non-root. The synthetic security directory is copied into the
backend image and its Docker policy path is configured explicitly. There are no new
mandatory services, databases or queues. Build evidence: `work/stage4-docker-clean.log`
and `work/stage4-docker-frozen.log`. The final diagnostic-export masking build is in
`work/stage4-docker-deliverable.log`; both services were checked healthy after startup.
Final urgent-rendering release rebuild: `work/stage4-docker-release.log`.

## Focused security review and limits

Inspection traced frontend text/file final events through core masking, narrow RiskInput,
structured no-tool output, grounded policy, public state, trace and TTS. Authentication
masking covers labeled numeric/token secrets, password disclosure forms, spaced/spoken
RU/KK code digits, full card patterns and naked short numbers when answering a specialist
exposure question. Frontend history/diagnostics and downloaded diagnostic JSON mask the
same practical patterns; the raw STT diagnostic string is no longer exported.
Insurance identification retains its existing business handling; Risk never receives
those identifiers. There is no raw secret-valued model output field or model-authored
explanation rendered by the new panels.

The focused scan passed for intended source, built frontend, all reachable Git blobs,
ignored `.env`, and both final Docker image configs/layers, checking both key and private
phone variants. Local log scanning checks credential values (older ignored Insurance
demo evidence can contain its configured test phone). Stage 4 cases/audio use synthetic
data only. Key and phone values were loaded only inside the scanner and never printed. Existing
image boundaries keep runtime credentials out of build layers. Exact final scan counts
are recorded in local `work/stage4-security-final.log`, `work/stage4-security-deliverable.log`
and `work/stage4-security-release.log`: 263 intended files, 595 reachable historical blobs,
15,763 backend layer files and 995 frontend layer files inspected before the Stage 4 commit.

This remains a local synthetic demo, not an authenticated production banking/security
service. The precheck is conservative and language coverage is finite; reports depend
on model interpretation and provider availability. Pattern masking is not universal DLP:
arbitrarily worded secrets may evade it. No URL reputation service, account investigation,
real operator dispatch, persistent case database, outbound telephony or account action
was added. A failure cannot certify safety. Browser TTS/microphone support depends on
installed voices and permissions. Existing Product language/intent and Insurance model
mismatches remain explicit above.

## Reproduction and presenter sequence

Use the documented runtime-only local `.env`, then `docker compose up --build -d`.
For text demos uncheck «Голосовой ввод»; TTS remains enabled.

1. Select Card before Start. Hear the branded offer, then say «Для меня главное — кешбэк».
2. Say «Мне сейчас звонят из банка и просят SMS-код». Hear immediate advice, inspect HIGH
   and the unchanged Card SalesLead. Continue «Как оформить эту карту?».
3. Manually select Fraud & Security. Describe the caller; answer the safe yes/no question,
   without giving any code. Inspect FraudCaseResult and explicit operator handoff.
4. Reset, select Insurance, create travel context. Mention a suspicious insurer link,
   then continue the same travel request. Insurance remains independent.
5. For voice-file testing, choose a synthetic PCM16 mono 24-kHz fixture while the
   microphone is stopped. Enable voice input, cancel live capture, then select
   «Проверить файл». One final transcript produces one user turn and source guidance/TTS.
   Capture resumes after TTS; cancel it when finishing a synthetic file demo.

From repository root with `PYTHONPATH=backend`, run the README test/evaluation commands.
Stage 4 live commands use new output paths and real provider calls:

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/evaluate_fraud_risk.py --output work/evals/new-stage4.json
./.venv/Scripts/python.exe -X utf8 scripts/stage4_risk_smoke.py --output work/new-stage4-state.json
```

Skills used: `agents-sdk`, `agent-evals`, `agent-debugging`, `security-review`,
`demo-readiness`, and `computer-use` for actual browser/file/STT/TTS verification.
