# Router evaluation and Agent Core validation — 2026-09-23

Checkpoint `f9ad3a0` was pushed to `feature/agent-core-router-eval` at the user's request
before testing finished. Subsequent fixes and this report form the approved follow-up commit.
All 104 final predictions were generated and scored with the original evaluator.
**Overall routing regressed in this run; this is not a routing-quality acceptance or a
claim of production readiness.** Clarification reliability and reply-language choice improved.

Model: configurable `gpt-4.1-mini`. Dataset: all 104 original development utterances.
One fresh state and one structured call per utterance; no labels sent to the model.
The original `data/starter_kit/evaluate.py` scores generated predictions unchanged.
No business writes, real STT/TTS, RAG, database or additional routing agent were introduced.

## Method and reproducibility

The comparable runs are serial with a four-second minimum call-start interval, identical
model and original dataset, zero automatic retries and a fresh state for each input.
Invalid or unavailable results are empty predictions, counted wrong, not discarded.
The official primary metric compares the first scenario; full match compares scenario sets;
multi-intent recall counts found reference intents (26 across 13 multi-intent examples).
Consequently a correct set in the wrong order can have full match but fail primary accuracy.
These are single-pass development measurements used while tuning general instructions,
not a hidden-set estimate or proof of deterministic performance. Slot correctness, replies,
actions and multi-turn continuity are not scored by the official evaluator.

Dataset SHA256: `e09e4a557a24e35e045e62628ed62d55654d5b3a252aa22622d945710795013e`.
Reference date for synthetic business data: **2026-10-01**.

## Final before/after results

Percentages include every input, including invalid outputs. RU/KK/mixed below group by
the dataset's language label; they are scenario accuracy, not language-detection accuracy.

| Group | N | Primary before | Primary after | Full before | Full after |
|---|---:|---:|---:|---:|---:|
| All | 104 | 95.19% (99) | 92.31% (96) | 93.27% (97) | 91.35% (95) |
| RU | 52 | 96.15% | 90.38% | 94.23% | 88.46% |
| KK | 45 | 93.33% | 93.33% | 91.11% | 93.33% |
| Mixed | 7 | 100% | 100% | 100% | 100% |
| Single | 84 | 97.62% | 95.24% | 97.62% | 95.24% |
| Multi-intent | 13 | 92.31% | 76.92% | 76.92% | 69.23% |
| Unclear | 3 | 33.33% | 100% | 33.33% | 100% |
| Out of scope | 4 | 100% | 75% | 100% | 75% |

- **Multi-intent recall: 22/26 (84.62%) → 19/26 (73.08%).** Three final multi-intent
  calls failed validation. Conditional recall among valid multi-intent calls was 22/24
  → 19/20; this does NOT replace the official all-input result above.
- Provider failures: **0 → 0**. Invalid outputs: **4 → 4** (different examples).
- Valid routing latency, median / nearest-rank p95: **2261 / 3654 ms → 2398 / 3413 ms**.
  Each side has 100 valid calls. These exclude pacing/failures and are not voice latency.
  Wall time including pacing: **418.98s → 431.79s**.
- Monolingual-language analysis has the same valid coverage on each side: **93/97**.
  Detection: **88/93 (94.62%) → 89/93 (95.70%)**; reply-language choice:
  **50/93 (53.76%) → 89/93 (95.70%)**. This does not measure translation quality.
  Final language mismatches: U054/U066/U099/U101 KK→RU; U004/U093/U097 mixed→KK.
  Overall final language detection among valid results: **93/100**. No mixed reply-language
  gold labels exist, so mixed reply accuracy is not claimed.
- Prompt hashes: before `a7705d88b01790bf17dc2ae0e9a386e0f023a7151c88cb33bde4ab5993913fd4`;
  after `cf4da795b0efaf6df0c2fd09a0150b28e018e933efbdb109bb835f6674f8397b`.
  Final run began **2026-09-23 11:54:35 UTC**. Schema, source enum normalization and fresh
  input serialization also changed; the delta cannot be attributed to prompt wording alone.

## Remaining errors and next routing work

| ID | Expected → observed | Classification |
|---|---|---|
| U012 | SC06 → SYS_UNCLEAR | KK purchase-for-visa boundary; over-clarification |
| U030 | SC15 → SC16 | KK medical-abroad versus personal-accident policy boundary |
| U035 | SC18 → SC14 | RU documents-only outcome confused with underlying property event |
| U090 | SC14+SC18 → SC14 | RU separately requested document information omitted |
| U098 | SYS_OUT_OF_SCOPE → SYS_UNCLEAR | RU unsupported service confused with ambiguity |
| U072 | SC36 → rejected | KK `invalid_slot`; exact rejected value not retained |
| U087 | SC19+SC35 → rejected | RU `invalid_structure`; exact structural cause not retained |
| U088 | SC21+SC22 → rejected | RU `segment_coverage` mismatch |
| U091 | SC07+SC08 → rejected | RU inconsistent/duplicate `alternatives` |

Nine full-match errors comprise five valid semantic mismatches and four rejected outputs.
Primary has eight errors because U090's first scenario was correct. The next routing slice
should strengthen transport constraints for slots and cross-field consistency, compare a
more compact instruction set against this baseline, and retest these boundary categories
with new paraphrases. Do not special-case IDs or utterance strings. Strict validation remains
enabled: no invalid slot or inconsistent route was silently accepted just to raise metrics.

## Earlier runs retained

The initial concurrency-3 run produced primary accuracy 71/104 (68.3%), full match
68/104 (65.4%), multi-intent recall 9/26 (34.6%). It included 25 provider failures
and five invalid outputs, all counted wrong. These scores confound API availability
with routing quality; provider HTTP codes were not captured in this initial run.
Among 74 valid outputs, six semantic mismatches were identified, plus a reply-language
defect: every valid decision selected Russian, including 32 Kazakh inputs.

The serial unchanged-prompt baseline had **99/104 primary (95.19%)**, **97/104 full
match (93.27%)**, **22/26 multi-intent recall (84.62%)**; zero provider failures and
four invalid outputs. Median/p95 valid-call routing latency: **2261/3654 ms**.
Its three valid semantic errors: U030 medical event abroad→accident policy claim;
U086 omitted payment-method information; U090 omitted the separately requested documents.
U003/U082/U102/U103 were invalid outputs; their raw rejected outputs were not retained.

The first prompt-only iteration regressed overall: **92/104 primary (88.46%)**, **93/104
full (89.42%)**, despite **24/26 recall (92.31%)**. It had zero provider failures but
eight invalid outputs. This intermediate run is preserved, not hidden or overwritten.

## General repairs and evidence

General improvements target purchase versus certificate, medical assistance abroad
versus personal-accident claims, incoming payouts versus outgoing premiums, independently
requested secondary information/complaints, enum normalization and current-turn language.
No development utterance is hardcoded into the Router.

- Exact U102 diagnostic: the model returned a useful clarification question but empty
  scenarios/segments. The SDK transport allowed that; the domain schema rejected it.
  Both transport arrays now require at least one item, including a SYS_* selection for
  unclear/out-of-scope/goodbye; alternatives are limited to two in the transport schema.
- A fresh state's default response_language=ru was included as apparent context. Fresh
  input now omits storage language defaults; real prior-turn language remains available.
- Enum values normalize to canonical source spelling. A known city outside named pricing
  regions maps to the source-defined region `other`. This never changes scenario selection
  or fabricates missing IDs; all remaining slot validation stays strict.
- Safe fixed validation-reason codes distinguish malformed structure, IDs, alternatives,
  segment coverage, continuation and slots. No exception bodies, slot values or secrets
  enter diagnostic metadata. Provider failures remain separate from routing failures.

## API, runtime and manual validation

- **249 offline backend tests passed**, plus Ruff lint/format and frontend typecheck/build.
  Vite initially hit sandbox spawn EPERM; the approved unrestricted build passed.
- `scripts/smoke_agent_core.py --pace-seconds 4`: **10 live HTTP checks passed**: RU,
  KK (including reply language), mixed, multi-intent/pending, unclear, out-of-scope,
  renewal→policy-number→goodbye in one session, and terminal-session HTTP 409.
- `scripts/smoke_teammate_runtime.mjs`: **three live backend turns passed** through exact
  teammate HttpAgentClient/ConversationRuntime Git blobs at
  `876b038ae8b2b61283e7899eac60f598333b3ba4`; same ID, resume listening after responses,
  ended only on goodbye. STT timing was synthetic and TTS a silent fixture, not live voice.
  The teammate branch and production UI were not modified or merged over existing work.
- In-app browser `/dev`: renewal→Kazakh office question→city→Kazakh goodbye, four
  successful turns with same ID. SC33 completed and restored SC27 from the stack without
  ending the conversation. Trace/source keys/latency were visible, terminal form disabled,
  and browser console errors were empty. The CLI browser helper was unavailable, so this
  was verified with the built-in browser instead.
- Manual defects retained for follow-up: a multi-intent wording mentioning a second driver
  returned invalid-output 502 twice; one isolated diagnostic replay passed, so its cause
  is unconfirmed. The UI exposed both failures and did not advance history. A Kazakh
  city inflection was recognized in the routing reason but not extracted as a slot,
  causing a redundant city question. Both are outside the official scenario metric.

Production integration follow-ups: the teammate client defaults to 20s versus backend's
45s routing budget (smoke used its supported 60s override); TTS should consume
state.response_language, not transcript.language. Agent Core only accepts session_id/text;
STT metadata stays runtime-local. No microphone, TTS provider or full production UI was tested.

## Remaining scope

Implement one explicit preview/confirmation business workflow next; no irreversible action
is currently enabled. Improve slot extraction, complete RU/KK wording of source facts, and
handle confidently urgent work independently from uncertain secondary intents (the current
policy uses the minimum selected confidence). Actual authentication, operator transfer,
production UI merge and voice integration remain future work. Memory is single-process,
bounded and lost on restart; keep the unauthenticated demo on loopback.

Skills applied: agents-sdk (one-call contract), agent-evals (offline/live separation),
agent-debugging (schema-layer diagnosis); browser verification used the built-in browser
fallback after the dedicated browser CLI was unavailable.

Artifacts: `work/router-eval/before.*` (initial burst), `before-paced.*` (unchanged prompt),
`after-prompt.*` (intermediate regression); final `predictions.json`,
`predictions.report.txt`, `predictions.details.json`. Captures contain model, prompt/data
hashes, complete ordered results and safe diagnostics. The source dataset/evaluator and
supplied plan remain byte-identical to the original files.
Raw run artifacts stay local and Git-ignored; this summary is the published report.

From repository root (the commands make real, billable calls; outputs never overwrite):

```powershell
.venv\Scripts\python.exe -X utf8 -m app.evaluation --run --output predictions-new.json --concurrency 1 --min-interval-seconds 4 --continue-on-error
.venv\Scripts\python.exe -X utf8 data/starter_kit/evaluate.py predictions.json data/starter_kit/dev_utterances.json
.venv\Scripts\python.exe -X utf8 scripts/compare_router_evals.py work/router-eval/before-paced.details.json predictions.details.json
```

Manual stand: set ENABLE_DEV_STAND=true and model/key in ignored root .env; run
`.venv\Scripts\python.exe -m app.main`, open `http://127.0.0.1:8000/dev`.
The model remains configurable; no credential appears in source, frontend or these artifacts.

## Integrated MVP rerun — 2026-09-23 12:15 UTC

The historical sections above describe the pre-integration milestone. The full stand now
integrates Agent Core, conversation-runtime and streaming voice; see PROJECT_MAP.md.
All 104 inputs were rerun with the same gpt-4.1-mini prompt (SHA256
`cf4da795b0efaf6df0c2fd09a0150b28e018e933efbdb109bb835f6674f8397b`), serial calls,
4-second minimum start interval, no retries and no expected labels in model input.
Official evaluate.py was run unchanged. No dev utterance was hardcoded.

| Group | n | Primary | Full match |
|---|---:|---:|---:|
| All | 104 | 92.31% | 90.38% |
| RU | 52 | 90.38% | 88.46% |
| KK | 45 | 93.33% | 91.11% |
| Mixed | 7 | 100% | 100% |
| Single | 84 | 92.86% | 92.86% |
| Multi-intent | 13 | 84.62% | 69.23% |
| Unclear | 3 | 100% | 100% |
| Out of scope | 4 | 100% | 100% |

Multi-intent recall: **20/26 = 76.92%**. Two invalid outputs, zero provider failures.
102 valid calls: median 2,491.8 ms, p95 4,460.7 ms; full paced run 443.2 s.
Compared with the immediately preceding same-prompt run: primary unchanged at 92.31%,
full 91.35% → 90.38%, multi recall 73.08% → 76.92%. This is repeat-run variability,
not evidence of a prompt improvement.

Remaining valid-output errors: U012 travel/visa → unclear; U030 medical assistance abroad
→ accident; U034 payout timing → unclear; U035 document checklist → incident; U061 payment
method → unclear; U075 suspicious agent → out of scope; U086 missed independent payment
question; U090 missed independent document request. U081/U088 failed output validation.
These expose scenario boundaries, over-clarification and multi-intent omissions. The MVP
does not claim perfect routing or guaranteed understanding of every input. Invalid output
returns a safe API error without advancing state; it is never replaced with a fake success.

Latest root `predictions.json` / `.report.txt` / `.details.json` contain this run. Its copy is
`work/router-eval/mvp-final.*`; the previous root artifacts are preserved as `pre-mvp.*`.
Artifacts remain ignored. Post-evaluation integration fixes affect policy, deterministic
RU/KK response rendering, current-turn reply language and transport, not the Router prompt
or selected-scenario evaluation. Live browser/API regression results are in MVP_VALIDATION.md.

## Final main input-order validation — 2026-09-23 12:39 UTC

After a live multi-turn test exposed stale-context selection, the input builder now puts
the current utterance **after** dialogue history. Catalog/instruction text is unchanged,
so the instructions hash above is unchanged; the input builder is different. The following
is a new complete run, not selective retries. Concurrency1, minimum interval3s (previous4s),
104/104 calls, no provider failures, one invalid output, 326.4s wall time including pacing.

| Group | n | Primary | Full match |
|---|---:|---:|---:|
| All | 104 | 91.35% | 90.38% |
| RU | 52 | 92.31% | 90.38% |
| KK | 45 | 88.89% | 88.89% |
| Mixed | 7 | 100% | 100% |
| Single | 84 | 94.05% | 94.05% |
| Multi-intent | 13 | 92.31% | 84.62% |
| Unclear | 3 | 100% | 100% |
| Out of scope | 4 | 25% | 25% |

Multi-intent recall: **24/26 = 92.31%**. Compared with the preceding integrated run:
primary92.31% → 91.35%, full90.38% → 90.38%, recall76.92% → 92.31%. Out-of-scope worsened;
do not call this an overall routing-quality improvement. These are single stochastic runs,
with a pacing difference, not a controlled statistical experiment.

Errors: U012→UNCLEAR; U030→SC16; U035→SC14; U061 invalid output; U076→UNCLEAR;
U087 missing SC19; U090 missing SC18; U098/U099/U101→UNCLEAR instead of OUT_OF_SCOPE.
Fresh-state evaluation does not prove dialogue quality. In the browser, RU→KK office
answers in one session passed; a later multi-intent request needed one manual retry after
a safe502. Independent direct reproduction succeeded, so no speculative validation bypass
or utterance-specific route was added. Wrong-language context leakage also motivated narrow
RU/KK reply guards in MessageService; these do not alter Router evaluation selections.

Final artifacts: root predictions.json/report/details and the preserved
`work/router-eval/mvp-current-turn-last.*`. Earlier runs remain untouched in work/.
Post-merge main validation:307 backend tests,24 frontend tests, lint/format/typecheck/build
passed. The frontend was restarted after checkout so Vite reloaded its proxy configuration.
