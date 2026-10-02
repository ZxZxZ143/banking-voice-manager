# Stage 3.1 — Insurance conversation validation

Validated on 2026-10-02 in the existing `main`, starting from `a1ffcbe`.
No Stage 4, additional packs, mandatory services or infrastructure were introduced.
Skills used: agents-sdk, agent-evals, agent-debugging, security-review,
demo-readiness and computer-use.

## Root cause and implementation

Previously a selected scenario directly selected a deterministic customer-facing reply.
An unclear short answer could repeat the same new/existing question and increment the
same counters as genuine failed understanding. Missing-data replies did not expose their
expected field to the next turn. Insurance also waited for the customer to speak first.

The existing pack architecture now has four separate authorities:

| Component | Authority |
| --- | --- |
| Router | Understand intent, language, entities and conversational progress |
| Decision Policy | Authorize continuation, clarification and terminal states |
| Grounded business layer | Look up/calculate facts and determine the next missing field |
| Pack-local Conversation Composer | Phrase acknowledgement and one useful next question |

`composer.py` reuses the existing bounded Agents SDK transport. It has no tools or
handoffs, does not store provider responses, disables SDK tracing and uses no hidden
retries. `OPENAI_RESPONSE_MODEL` optionally selects its model; otherwise the configured
Router model is reused. Both live evaluations used `gpt-4.1-mini`.

Input contains only the current Insurance utterance, eight prior local turns, response
language, authorized scenario/policy, masked collected fields, missing fields, previous
question, trusted fact block and allowed action. It receives no other pack context,
credentials, evaluation labels or arbitrary backend objects. The typed output contains
act, acknowledgement, question, acknowledged context and expected answer type. The
server owns `expected_slot`; the model cannot select a different collection target.
Received-this-turn field names distinguish a new value from an identifier in prior history.
If wording fails validation, typed new/existing goal recognition survives as conversational
metadata. Fallback narrows its question and resets misunderstanding without accepting the
rejected prose or authorizing an operation.

The prompt requires understanding the actual conversation, acknowledging partial answers,
narrowing the next question, varying repairs, avoiding internal labels and identifier
echoes, and never claiming an unsupported write or inventing conditions. Validation
rejects free numeric facts, internal labels, common unsupported operation claims,
unauthorized terminal acts, missing collection questions and identical previous questions.
Failed composition keeps the authorized step and state and emits an allowlisted diagnostic.

**Grounding tradeoff:** trusted localized business facts are inserted unchanged between
the model's acknowledgement and question. The model frames these facts conversationally;
it does not freely paraphrase their numerical or contractual content. This preserves
prices, dates, statuses, required documents and limitations exactly. Some factual blocks
remain longer and less conversational than the surrounding dialogue.

## Opening, progress and handoff

Insurance opens through the existing `/api/conversation/start`, as Product already did.
The RU/KK opener names Saqta Insurance, asks an open help question and adds only an
assistant event. No Router/Composer calls or fabricated customer turn occur. The generic
frontend runtime awaits real browser TTS completion before listening.

Conversation metadata records last act/question, expected answer type/field, repair
attempts, phase and recognized new/existing context. A greeting stays discovery. A useful
short answer, requested value or corrected identifier resets misunderstanding counters.
Conversational progress does not authorize a new business scenario or establish policy facts.

Requested phone, IIN, policy and claim identifiers have a literal validation path against
the existing slot definitions. It supports numeric values, phone formatting and RU/KK
digit-by-digit speech, preserves leading zeroes and refuses ambiguous/incomplete values.
It only parses the already requested field; it never classifies intent. Valid requested
data continues an authorized active flow even if a model decision was rejected.
Numeric identifiers preserve the prior response language.
While SC06 collects travel dates, a literal RU/KK day/week duration is retained separately.
It cannot establish a guessed start date. Once the customer supplies a start, the server
calculates an inclusive end date (fourteen days from October 10 end on October 23), using
the same inclusive-day rule as the quote. Explicitly supplied dates remain authoritative.
The short-answer language guard also recognizes clear Russian function words when the
Router retains a stale mixed-language label.

Non-explicit comprehension handoff requires multiple unsuccessful repair attempts without
progress. Operational handoff follows collection of the flow's useful required data and
the grounded explanation that the real action requires a specialist. No real insurer
write is connected or claimed. Explicit SC37 immediately retains the exact Russian text:
«Конечно, передаю диалог оператору.» It bypasses Composer. Terminal sessions stay closed.

## Automated checks

- Backend: **544 passed**, 18.95 seconds in the final complete run, including requested-identifier continuation,
  digit speech, leading zeroes, invalid/ambiguous values, repeated clarification, progress,
  terminal policy, fallback, immutable facts, privacy and pack isolation.
- Frontend: **38 passed**; TypeScript check and production build passed. Tests cover
  assistant-only opening, playback-before-listening, pack compatibility and terminal capture.
- Ruff check passed; formatting check passed for 134 backend source/test files.
- `git diff --check` passed. Product source/catalog and canonical Insurance data were unchanged.

## Separate conversation evaluation

`data/insurance_conversation/eval_cases.json` has **32 dialogues**, separate from the
canonical 104 routing inputs. It covers greeting, new/existing clarification, partial and
short answers, phone/IIN/policy/claim values, correction, travel duration, payment problems,
different repairs, genuine misunderstanding, operator requests, operational handoff and RU/KK/mixed.
`scripts/evaluate_insurance_conversation.py` runs real configured agents, saves failures,
uses exclusive new output paths and performs no per-case retry. Labels are checked after
inference and never enter model input. No subjective LLM style judge is used.

Latest full-batch evidence: ignored local `work/evals/stage31-dialogues-complete.json` and its log.
Dataset SHA256: `a3cf2bc2e685e018d2a12468930b3a5ffb8a2ed89a88ff1ea7971fdd981a10eb`.
**26/32 whole dialogues passed all checks**, with **91 customer turns** processed.

| Deterministic metric | Passed / eligible |
| --- | ---: |
| No premature handoff/ending | 76 / 76 |
| No normalized identical question after progress | 36 / 36 |
| Requested-slot continuation | 26 / 26 |
| Progress resets counters | 36 / 36 |
| Conversation-act progression | 22 / 22 |
| Reply language | 90 / 91 |
| Expected next field | 36 / 39 |
| Expected grounded answer present | 16 / 18 |
| Expected terminal state | 12 / 15 |
| Composer without fallback/error | 84 / 91 |
| Both providers available | 91 / 91 |

An earlier `-verified` run's `provider_success=91/91` counted completed service turns, including a
Composer provider failure handled safely. The evaluator was corrected to count both model
providers. A separate `stage31-dialogues-provider-audit.json` derives **90/91** from the
unchanged original trace, without repeating calls or replacing evidence. The final `-complete`
run used the corrected evaluator and had no provider failures. Its seven rejected compositions
were handled by safe fallback. The earlier run also passed 26/32 dialogues, with language
91/91, expected next field 35/39, grounded answer 17/18 and terminal state 13/15. These
differences reflect observed model variability, not selective case retries.
The full batch preceded the final literal-duration, short-RU language and expanded-mask
fixes. Their deterministic regressions and separate live checks are reported below; no
new aggregate score is inferred from those targeted checks.

Final targeted evidence: `work/stage31-targeted-publish.json` / `.log`, seven real Docker/API
customer turns, both checked flows passed. Travel duration did not establish a guessed start;
after October 10 was supplied the end was October 23, travelers were collected and the
grounded quote used fourteen days (15,400 tenge for the synthetic one-person case).
Mixed callback collected phone/time, replied in RU on the explicit Russian final turn and
ended in the authorized handoff. Its first model decision was rejected as invalid_slot;
safe clarification and the later valid phone turn recovered the flow. This targeted success
does not erase the discovery-output failure or change the full-batch score.

The preceding `stage31-targeted-final.json` attempt exposed model-guessed dates on a literal
duration, and failed its assertion. Those guesses are now removed; a unit regression injects
them deliberately and verifies both waiting for a start and the inclusive derived end.
An explicit return-date correction clears the remembered duration and remains authoritative.
`stage31-targeted-confirmed.log` recorded an unavailable local API during the failed Docker
build; it made no successful model calls. All evidence was retained at separate paths.

| Language group | Whole dialogues | Correct reply language |
| --- | ---: | ---: |
| RU | 19 / 21 | 62 / 62 turns |
| KK | 5 / 8 | 21 / 21 turns |
| Mixed | 2 / 3 | 7 / 8 turns |

Mixed checks permit either supported reply language unless a turn explicitly fixes it.
Language and act checks are contract checks, not a measurement of human fluency.

Full-batch failures were D05/D32 (question/claim validation rejected free wording),
D08 (invalid Router output on callback discovery/continuation), D09 (KK reply on a turn
explicitly expecting RU), D22 (travel quote blocked because an earlier required field was
not retained), and D23 (Router omitted a Kazakh-inflected travel destination). The two
travel cases therefore failed to reach their expected quotes; they did **not** alter existing
quotes. All generated factual
blocks remained unchanged. Safe fallback avoided an accidental transfer and retained data,
but can be more general than the intended narrower follow-up. Expected-field recovery only
applies once a business path and expected field exist; it cannot invent a rejected discovery route.

Earlier development runs are retained locally as `stage31-dialogues-initial`, `-final`,
`-release`, `-release-2`, `-verified`, `-acceptance`; they used earlier code/contracts or fixtures and are not replacements
for the final result. Fixture corrections followed inspected business data: unique claim
status lookup does not require a redundant claim number, claim dispute requires complaint
text, mixed language needs a mixed contract, and payment issue uses the actual synthetic
C003 charged-but-unissued payment. Production code contains no literal evaluation-utterance rules.

## Canonical routing and Product regression

Canonical data hash remained
`4623e6f590715ac0e2e2119b2c475d0408f2ab9a7fd3c05a0cabd03b0239751b`.
Final Router instructions hash:
`0d5514b88790b4374a70a8e46bf075948875fd9b83f7486488b2cc7a2007c288`.
SDK output no longer permits null placeholder slot values; business validation remains strict.
Each canonical input had a fresh state, one routing call, no Composer and no label inputs.
Concurrency was two, with four seconds between call starts; failures remain in the denominator.

| Run | Primary | Full match | Multi-intent recall | Invalid outputs |
| --- | ---: | ---: | ---: | ---: |
| Prior Stage 3 baseline | 100 / 104 | 99 / 104 | 25 / 26 | 3 |
| Stage 3.1 initial | 99 / 104 | 98 / 104 | See saved report | 3 |
| Stage 3.1 intermediate release | 100 / 104 | 98 / 104 | 24 / 26 | 2 |
| Stage 3.1 final verified | **102 / 104** | **101 / 104** | **25 / 26** | **0** |

Final run completed 104/104, with zero provider/routing-output failures. Primary accuracy:
98.08%; full match: 97.12%. RU primary 51/52, full 50/52; KK primary/full 44/45;
mixed 7/7. Remaining semantic errors: U030 accident abroad selected SC16 instead of SC15;
U035 required documents selected SC14 instead of SC18; U090 omitted the document scenario
from a multi-intent flood request. These are observed confusion pairs, not special-cased fixes.
Evidence: `work/evals/stage31-insurance-verified.json`, `.report.txt`, `.details.json`.

Unchanged Product evaluation completed 40 cases / 45 turns and eight selector checks:
intent, structured output and grounding **45/45**; reply language **42/45**; flow **37/40**;
continuation **12/13**; selector validity and cross-pack selection **8/8**. RU language 22/22,
KK 16/18, mixed 4/5. Stage 3 had the same overall language/flow counts and 13/13 continuation.
The one-turn continuation variation is disclosed; Product prompt, catalog and business code
were not changed to tune this run. Evidence: `work/evals/stage31-product.json`.

## Latency cost

Normal in-domain Insurance turns use **two sequential model calls**, Router then Composer.
Explicit operator uses only Router; openers use neither. An out-of-domain turn may still
add the existing platform selector. Product retains its single pack-agent call.
Business/Composer spans are separate from aggregate response time in the safe trace.

Latest full 91-turn conversation run, milliseconds; p95 uses the nearest-rank method:

| Span | Samples | Median | p95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Router | 91 | 2,482 | 3,432 | 8,515 |
| Business logic | 91 | 0.220 | 0.546 | 1.929 |
| Composer, including failures | 89 | 1,398 | 2,404 | 4,099 |
| Total backend | 91 | 3,893 | 6,166 | 10,055 |

The additional call costs about 1.40 seconds at the median; tail delays are material.
The earlier `-verified` run had backend median/p95 4.18/11.74 seconds and Composer maximum
15.53 seconds; the faster final sample does not eliminate that observed provider tail risk.
Browser first audio is measured from actual SpeechSynthesis `onstart`, separately from
backend time. Final UI observations included 808 ms on the existing-policy follow-up,
809 ms on explicit handoff, 824 ms on the IIN question and 514 ms on the factual IIN reply.
These browser events verify playback scheduling, not a subjective acoustic quality score.

## Real browser and voice

The in-app browser used the final Docker UI at `http://127.0.0.1:5173/`, real HTTP agents,
browser TTS and the actual voice WebSocket. No mocked UI responses or fabricated voice finals.

- Fresh Insurance opener had one assistant item, no customer item and no routing latency.
- The exact bad journey was reproduced: «здравствуйте» → vague insurance problem →
  «разобраться с существующим» → «у меня уже есть полис». New/existing was acknowledged,
  different problem questions followed, counters reset and no transfer occurred.
- Explicit operator yielded the exact friendly phrase, terminal handoff and stopped capture.
- Callback collected phone and convenient time in successive turns, with receipt acknowledged
  only after actual data arrived. Supplying the phone did not transfer. After time arrived,
  the assistant acknowledged it, said the request data were collected, explained the specialist
  limitation and entered handoff without claiming a completed callback.
- A synthetic digit-by-digit IIN WAV was uploaded through the UI. Real STT yielded one
  final and exactly one new customer turn (turn 2 → 3). The active SC32 flow continued,
  returned the mock bonus-malus class 7, masked the number in trace and resumed listening
  after TTS. STT observation was approximately 697 ms; voice diagnostics reported 724 ms
  after commit with 2,528 ms endpoint silence. A subsequent empty ambient capture produced
  no new customer turn. The microphone was disabled after verification.

Screenshots are ignored local evidence: `work/stage31-browser-verified.png`,
`stage31-browser-operator.png`, `stage31-browser-voice-iin.png` and additional flow captures.
Callback evidence: `stage31-browser-phone.png` and `stage31-browser-operational-handoff.png`.
They are not committed.

Streaming script evidence `work/stage31-voice-release-2.json` verifies phone, IIN and the
short existing-policy answer with real 24 kHz PCM/STT. Each produced one `utterance.final`,
one customer turn, zero repair attempts and no handoff. STT after commit: 781/759/791 ms.
The final-image rerun `stage31-voice-verified.json` completed phone with 609 ms STT and no
handoff, then timed out while preparing the IIN seed request (not while transcribing audio).
Backend logged a provider error. The partial result and error log are retained. The separate
final browser IIN check above succeeded. Synthetic audio establishes integration, not the
accuracy of noisy physical microphones or every spoken numbering convention.

## Docker and focused security review

Clean Compose shutdown/start with `docker compose up --build` succeeded, including another
clean launch after the final source changes; final rebuilt
backend/frontend are healthy on loopback 8000/5173. No Compose, image or mandatory-service
changes were needed. Backend still runs as non-root with runtime-only credentials.
A late build failed with a BuildKit missing-parent-snapshot error. Repeating the normal
Compose build recovered it without cache pruning, volume removal or additional services.

The Composer has no execution authority. Untrusted utterances/history are explicitly data;
provider traces and stored responses are disabled. Full identifiers stay in private
pack-local state for validated synthetic lookups. Composer input, public state, routing
reasons/segments, safe trace and source references mask sensitive values. The core's later
transcript assignment invokes the pack redaction hook so it cannot restore the raw number.
Policy/claim masks are case-insensitive, including normalization from lower-case input.
New-driver IIN and changed contact values are also masked. Unit checks verify masks and
preserved private values. Final dialogue/voice JSON artifacts
were scanned for fixture phone/IIN/policy/claim identifiers: none exposed.

Credential scan passed for 227 intended files, frontend bundle, local logs and 482 reachable
historical Git blobs. `.env` is ignored/untracked. Both image configs contain no static
OPENAI_API_KEY; streaming image/layer inspection passed for 15,692 backend and 995 frontend
files. Only counts are printed, never credential values. Evidence: `work/stage31-security-complete.log`
and the final publish scan. Screenshots and work artifacts remain ignored.
Final scan evidence: `work/stage31-security-ready.log`, same file/blob/image counts above.
No real policy, payment, SMS, claim or callback operation was executed.

## Remaining limits

Live natural wording and initial entity extraction remain probabilistic: 26/32 complete
conversation cases passed, despite all measured requested-ID continuations and no-premature-
handoff checks passing. Safe fallback is intentionally visible and may feel less natural.
Literal spoken-ID parsing supports digit-by-digit RU/KK, not arbitrary grouped-number speech.
Free prose guards are bounded safeguards, not a general semantic proof against every
possible qualitative hallucination; immutable business blocks and absent execution tools
preserve actual business authority. Urgent catalog guidance retains its existing wording.
State is in-memory, there is no authentication/persistent contact-center integration,
and physical microphone/Kazakh voice quality depends on the user's installed voices/device.
Stage 4 remains outside scope.
