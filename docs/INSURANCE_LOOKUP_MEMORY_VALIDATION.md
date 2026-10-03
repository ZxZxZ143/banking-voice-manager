# Insurance identifier memory hotfix

Validated on 2026-10-03 in `codex/stage5b-dashboard`, preserving the three existing
Stage 5B integration commits. This is a pack-local correction, not a new platform stage.

## Failure and change

The original deterministic reproduction failed after the customer supplied a phone while
the assistant expected a policy number: `expected_slot` remained `policy_number`.
The required-slot loop preceded client lookup, and missing/unavailable identifiers were
indistinguishable. Record lookup failures could also ask for the same number indefinitely.

`IdentificationState` now retains typed unavailable, attempted, failed, requested and
successful fields; private supplied values and failed-attempt fingerprints; completed
read-only checks; and exhaustion. Each suspended Insurance scenario keeps its own memory.
Public state and Router/Composer memory omit the private values and fingerprints.
Final identifier questions use the application-authorized localized request, so even an
indirect or misleading Composer question cannot reopen the preceding identifier step.

The Router adds a small `identifier_answer` contract: status and identifier kind. It resolves
RU/KK unavailability against the last question or explicitly named field. A bounded literal
fallback handles short answers only while an identifier is expected. This does not select
business intents. Clear alternative phone/IIN/policy/claim/plate formats use source validation;
domestic, international and national Kazakhstan phone normalization remains unchanged.

The application owns progression:

- Preserve the initial required record question where applicable; a supplied alternative
  phone/IIN bypasses the missing record field.
- Attempt each normalized client lookup once; accept a genuinely corrected value.
- Resolve owned records through the existing client-scoped `get_policy`/`get_claim` helpers.
  A unique record does not require the customer to recover its number.
- If several owned records remain and the record number is unavailable, prepare handoff.
  A failed explicit record number also ends that lookup; it is not requested again.
- A vehicle plate is accepted as context but never requested as a policy lookup method:
  the current helper has no such supported ownership-safe path. A plate is not authentication.
- Exhaustion constructs and retains `ManagerSummary` before terminal status. The active
  scenario, history, collected values and attempt memory stay in private pack state.

`lookup_exhausted` summaries expose only the scenario, a catalog-backed business-problem
enum, known-client flag, field names, checks and `operator_review`. The RU/KK customer reply
explains that the question/data are retained and a specialist review is prepared; it
explicitly states that this demo does not connect a real operator. The existing trace UI
renders the additive summary fields. No analytics event schema or dashboard behavior changed.

## Verification

- Full backend suite: **754 passed** (731 existing plus 23 new regressions), 32.00 seconds.
- Existing frontend suite: **80 passed**; TypeScript check passed.
- Focused live Router regression: **8/8 RU/KK cases passed**, including absence, forgotten
  number, inaccessible document and requests to use a phone instead.
- Live voice state smoke: **4 synthetic STT finals → 4 actual HTTP turns**, one session,
  unavailability retained, phone/IIN exhaustion, terminal handoff and late-final rejection.
  TTS is an explicit silent fixture; acoustic recognition quality was not measured.
- Tests cover the complete reported customer sequence, early terminal protection of later
  turns, five subsequent turns without re-requesting unavailable policy data, voluntary
  policy recovery, corrected phone A→B, no retry of failed A, ambiguous policies, claims,
  source ownership, RU/KK handoff, scenario resume and private/public/persistence boundaries.
- Three older behavioral expectations were updated deliberately: failed record → handoff;
  unique claim may resolve without asking its number; two failed identity paths no longer
  lead to another policy-number request. Their original privacy/context assertions remain.

The permanent tests use synthetic phones. `INSURANCE_REGRESSION_PHONE` optionally supplies
the exact local reproduction value without committing it. Canonical starter-kit data and
evaluation labels were not changed.

## Live evaluation limits

The full unchanged 104-case Router evaluation completed with **100/104 primary matches
(96.2%)**, **99/104 full matches (95.2%)**, no provider failures and one invalid output.
The five full-match errors were U030, U035, U086, U087 and U090. These concern general
scenario decomposition/selection, not identifier memory; no example-specific tuning was made.

The complete existing 32-dialogue evaluation processed **91 turns**, with **24/32 complete
dialogues passing** on its first run. Progress reset was 36/36, no repeated question 36/36,
expected-field continuation 26/26, no premature handoff 76/76 and language 91/91.
Other totals: Composer validity 89/91, next-slot 34/39, grounded facts 17/18, terminal 13/15.
D16 exposed changed collection order; the original business-question order was restored and
its separate four-turn rerun passed all checks. This is not reported as a second full run.
Remaining observed failures: D08/D09/D32 extracted an unprovided identity value; D11/D30
rejected Composer wording or invalid routing; D25 selected a different document workflow;
D26 did not reach the expected uncertainty handoff. The prior documented Stage 3.2 full run
was 26/32; probabilistic extraction/discovery limitations remain visible rather than hidden.

Local evidence is ignored under `work/insurance-lookup-*`; it is not published or committed.

## Browser, Docker and privacy

Real Codex in-app browser checks used the Docker UI at `http://127.0.0.1:5173`:

1. The exact reported phone is the locally configured demo number. With the normal overlay,
   supplying it while renewal expected a policy number resolved the owned policy immediately
   and prepared the renewal operation for a specialist, with no repeated policy request.
2. The overlay was temporarily disabled using an ignored Compose override, leaving `.env`
   and the persistent analytics volume intact. The reported text/phone sequence advanced
   policy → phone accepted → IIN. The subsequent pronoun referred to the current IIN question;
   it was marked unavailable and produced early `lookup_exhausted`, before further inputs.
   The browser displayed retained renewal context, failed phone and unavailable IIN.
3. A separate explicit-policy-unavailable flow advanced phone → IIN → `lookup_exhausted`.
   The visible summary had unavailable policy, failed phone/IIN, both collected field names,
   renewal scenario, checks and `operator_review`. The transcript was masked and the terminal
   input disabled. The result was visually inspected and captured through the browser tool.

The normal Docker configuration and configured local profile were restored. A final live
policy-status API lookup and synthetic-STT runtime smoke were rerun on the final image.
These phone/IIN paths operate only on the existing synthetic demo backend, not real identity
verification. No real operator or telephone call was made by this hotfix.

Security checks cover intended source files, frontend build, backend logs, image configs
and persisted SQLite rows/files. Private values/fingerprints stay in process memory;
safe summary enums/field names remain separate from the unchanged analytics allowlist.
Neither private values nor raw transcripts are added to analytics. No secrets, `.env`,
runtime database, personal phone, screenshot, `work/` file or log is part of the commit.

## Reproduce

```powershell
$testPath = Join-Path (Get-Location) ('work/pytest-lookup-' + [guid]::NewGuid().ToString('N'))
./.venv/Scripts/python.exe -m pytest backend/tests -q --basetemp $testPath
$env:PYTHONPATH = 'backend'
./.venv/Scripts/python.exe -X utf8 scripts/evaluate_insurance_lookup.py
node --import ./frontend/node_modules/tsx/dist/loader.mjs scripts/smoke_insurance_lookup_voice.mjs
```

The scripts use the existing configured model and live local API. The voice smoke uses an
unknown synthetic phone; do not configure that fixture as `DEMO_TEST_PHONE`.

Skills used: agent-debugging, agents-sdk, agent-evals, security-review, demo-readiness.
