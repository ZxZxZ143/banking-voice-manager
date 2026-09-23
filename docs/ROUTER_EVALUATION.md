# Router evaluation checkpoint — 2026-09-23

This checkpoint is being committed at the user's request while live tests continue.
Final paced before/after metrics and live API/runtime smoke results are not yet recorded.

Model: configurable `gpt-4.1-mini`. Dataset: all 104 original development utterances.
One fresh state and one structured call per utterance; no labels sent to the model.
The original `data/starter_kit/evaluate.py` scores generated predictions unchanged.

The initial concurrency-3 run produced primary accuracy 71/104 (68.3%), full match
68/104 (65.4%), multi-intent recall 9/26 (34.6%). It included 25 provider failures
and five invalid outputs, all counted wrong. These scores confound API availability
with routing quality; provider HTTP codes were not captured in this initial run.
Among 74 valid outputs, six semantic mismatches were identified, plus a reply-language
defect: every valid decision selected Russian, including 32 Kazakh inputs.

General improvements target purchase versus certificate, medical assistance abroad
versus personal-accident claims, incoming payouts versus outgoing premiums, independently
requested secondary information/complaints, enum normalization and current-turn language.
No development utterance is hardcoded into the Router.

Artifacts are local and excluded from this checkpoint: `work/router-eval/before.*`
and the currently running unchanged-prompt `before-paced.*` (serial, 4-second minimum
call-start interval). A final same-condition run will produce `predictions.json` and
siblings. Scripts under `scripts/` compare complete captured runs and test live APIs.
