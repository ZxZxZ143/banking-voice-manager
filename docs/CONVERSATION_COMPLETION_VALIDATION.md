# Insurance conversation completion and policy context — 2026-10-04

Part D is implemented on `codex/stage6-telephony-integration`. A resolved request now enters
`wrap_up` when no required field, pending/deferred task, confirmation or handoff remains.
The assistant offers more help in RU/KK; acknowledgement retains that offer, another unstated
question gets an open prompt, declining ends the session, and a direct new request routes
normally. Understood control turns have no scenario selections or clarification flag.

`policy_relationship` is typed as new/existing/not_applicable/unknown. Router semantic evidence
and catalog-defined workflows establish it; short answers and related work retain it. Existing
policy ownership as conversational context is separate from the requested operation and never
authorizes a business lookup or verifies ownership. New/existing classification is permitted
only when the distinction is genuinely unresolved and needed. The universal SYS_UNCLEAR
binary fallback is removed; Composer rejects unnecessary classification, including when its
own typed output has already recognized the relationship.

Risk guidance uses a small Insurance-owned hook. Unfinished business keeps its fields, lookup
memory and relationship; acknowledgement resumes the exact pending question before any
recognition repair or lookup. With no unfinished task, security guidance enters wrap-up.
Product behavior, source facts, speech normalization, TTS selection and SQLite schema are
unchanged. Legacy foundation flows without conversation metadata retain their old contract.

## Deterministic verification

- Full backend suite: **1160 passed**; frontend: **97 passed**; TypeScript/Vite build passed.
- **27 new checks** in `backend/tests/unit/test_insurance_completion.py`, including RU/KK
  completion, direct requests, existing/new retention, genuine ambiguity, source evidence,
  Risk resumption with failed identifier recognition, deferred work, identity detours,
  conditional SDK schema and atomic control projection. Fixture decisions test application
  boundaries; they are not measured semantic model accuracy.
- `unnecessary_new_existing_question_count = 0` in the deterministic completion regressions.
  The shared evaluator asserts it for every case where classification is prohibited.
- Ruff check/format and `git diff --check` pass. All four offline Stage 6 smoke scripts pass,
  including shared core/Risk/SQLite restart proof. Their models/audio are explicitly fixtures.
- Docker backend/frontend builds pass; isolated startup and frontend proxy health pass.
  No production database volume or telephony credentials are used by the startup check.

Existing tests that required a completed answer to have status `active` and no question were
updated to require `awaiting_user`, `wrap_up` and one application-owned further-help question.
Privacy, grounded fact variants, slot collection and lookup assertions remain in those tests.

## Live dialogue evaluation

Dataset: `data/insurance_conversation/completion_cases.json`, 14 synthetic dialogues, 34 turns,
RU/KK equally represented. Only each utterance is sent to MessageService; expected labels stay
outside model input. Router/Composer use the configured `gpt-4.1-mini`; Risk uses its normal
configured model and candidate gate. No automatic retries or subjective style judge.

Final full run: `work/part-d/live-completion-v4.json`, **14/14 dialogues passed**.
Median backend turn latency: **4.60 s**. Dataset SHA-256:
`12caf5f644da6aa284f8b0ec4558043adff2058f5f416e0e4736963ff536a7a0`.

| Metric | Passed / checked |
|---|---:|
| Wrap-up correctness | 16/16 |
| Resolved acknowledgement correctness, including no SYS_UNCLEAR | 4/4 |
| Conversation ends after no more questions | 4/4 |
| Context relationship retention | 24/24 |
| Open prompt for another question | 2/2 |
| Direct new request routed | 2/2 |
| Expected field retained/selected | 8/8 |
| Language correctness | 34/34 |
| Grounded fact preservation | 4/4 |
| Provider success / Composer validity | 34/34 each |
| Unnecessary new/existing questions | **0** |

There are 32 turns prohibiting new/existing classification and two genuinely ambiguous turns
where it is allowed. This is a small regression set, not a general accuracy guarantee.

Earlier artifacts remain untouched: v1 passed behavior checks but still exposed SYS_UNCLEAR
for controls; v2 stopped on an assignment-validation error when clearing a legacy selection;
the atomic projection regression now covers that failure. v3 completed 11/14 dialogues:
two were interrupted by provider timeout/error, and one Kazakh ownership declaration received
an unnecessary classification question. The general ownership-versus-operation rule and
Composer guard address that observed error; v4 is a fresh full run, not merged selective retries.

## Canonical routing

The unchanged 104-example starter-kit evaluator is run separately from dialogue quality.
Final artifacts: `work/part-d/canonical-routing-final.json`, `.report.txt`, `.details.json`.
Final prompt SHA-256: `c25932163e3a634f0e4d8d42f878d1855899626dd20dc48cd76a551f5c93d05e`.
Final full run: **99/104 primary (95.2%)**, **98/104 full match (94.2%)**;
multi-intent recall **20/26 (76.9%)**. One rejected model output, no provider failures,
323.37 s routing wall time. RU full match 92.3%, KK 95.6%, mixed 100%.

Remaining errors: U030 medical assistance abroad → general accident; U035 document checklist
→ property claim; U084 two quote requests → unclear; U086 rejected structured output;
U087 omitted payout dispute alongside service complaint; U090 omitted the independent document
request. U086 failed `invalid_structure` validation. These are catalog-boundary,
over-clarification and multi-intent limits, not fixed by
the completion-state change. No evaluation phrase matching or label inputs were added.

Earlier runs remain `canonical-routing.*` (94.2% primary, 93.3% full, no transport/output
failures) and `canonical-routing-v2.*` (87.5% primary, 86.5% full, six provider failures and
three rejected outputs). These used earlier prompt revisions; they do not represent the final
prompt. Failed calls remain errors in the official denominator. Do not infer a controlled
accuracy improvement from single stochastic runs with different availability.

## Browser check and limits

The actual built Conversation Demo uses a local live backend on an isolated port and database.
The screenshot regression follows security guidance → acknowledgement → no-more-questions;
the UI shows wrap_up/ask_followup with no SYS_UNCLEAR, then ended/goodbye and disabled input.
Earlier browser attempts also exercised unavailable Risk analysis: the explicit precautionary
fallback remained visible and still completed correctly. Provider outages are not hidden.
Evidence is retained under `work/part-d/` (local screenshots and synthetic validation database).
Final full-page proof: `work/part-d/browser-final.png`.
The final browser uses the real built UI and live Risk/Router/cedar TTS; microphone input is
disabled, so this proves the text/runtime/TTS lifecycle, not new STT or PSTN precision.

This change does not claim production routing perfection, real insurer authorization or live
PSTN readiness. The prior structured-audio precision limitation remains documented in
`STRUCTURED_SPEECH_RECOGNITION_VALIDATION.md`; that corpus was not rerun for this dialogue-state
change. Cedar remains the user's preferred voice; no gender or MOS approval is inferred.

## Reproduction

From the repository root in PowerShell, use a fresh output filename for each live run:

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest backend/tests -q --basetemp=work/completion-tests
.venv\Scripts\python.exe -X utf8 scripts/evaluate_insurance_conversation.py --dataset data/insurance_conversation/completion_cases.json --output work/evals/completion-new.json
.venv\Scripts\python.exe -X utf8 -m app.evaluation --run --output work/evals/routing-new.json --concurrency 1 --min-interval-seconds 1 --continue-on-error
```

Skills actually used: `agents-sdk`, `agent-evals`, `agent-debugging`.
