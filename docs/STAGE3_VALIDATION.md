# Stage 3 validation — 2026-10-01

Stage 3 adds the proactive Product Promoter beside Insurance Manager. The final version
starts Product conversations with a Merei Demo Bank greeting, interprets explicit spoken
currency/amounts and produces conversational catalog-based replies. All live checks below
used `gpt-4.1-mini`, temperature 0, the real local key and HTTP/WS services. Offline
fixtures are reported separately from model accuracy. No real customer data was used.

## Product Promoter

Exactly six products belong to the fictional Merei Demo Bank: three deposits and three
debit/payment cards. Source: `data/product_promoter/catalog.json`, reference 2026-10-01.
Typed preferences include explicit goals, amount/currency/term, liquidity, replenishment,
cashback, fees, withdrawals and digital availability. Discovery asks one useful question;
matching/ranking, displayed conditions and replies are deterministic backend behavior.
Comparisons preserve restrictions, objections cannot change terms, and refusal stops sales.
Only explicit application/link/callback interest becomes a completed interested lead.

`SalesLeadResult` records outcome, category, selected product, explicit preferences,
shown/compared products, objections, interest and next action. These are demonstration
results; products, links, callbacks and bank integrations are not executed.

Human presentation uses names such as «тенге» and «доллары США», scaled amounts such as
«50 тысяч тенге», decimal commas and grammatical percent/currency forms. Complete source
conditions remain in a UI disclosure. KZT/USD stay in normalized machine state.
The Product opener runs with zero model calls and no invented customer message.

## Multi-pack architecture

Startup registers exactly `insurance_manager` and `product_promoter`. New sessions default
to Insurance; omitted mode later continues the active pack. Explicit API/UI selection
suspends the old local context and initializes/resumes the selected one with one UUID.
Completed leads and refusals survive switching. Contexts/results have exact registered types;
no insurance slots, IDs, history or InsuranceResult enter Product, and no Product preferences
or SalesLeadResult enter Insurance.

The natural selector runs only after an out-of-domain result. Input is restricted to current
text, current pack ID, public manifest descriptions and global language. A different
allowlisted target needs confidence ≥0.75 and customer confirmation. Yes dispatches the
original question; no preserves the old private state. Unsupported domains do not force a
switch. Failed pack/selector calls roll back the complete turn. Selection has a shared
55-second deadline below the browser timeout.

## Frontend and offline checks

The UI includes a two-pack selector, authoritative active pack, switch notice, lead/complete
conditions and product/switch trace fields. It locks selection during requests/playback.
Product selected before Start opens automatically; selecting Product while listening opens
or resumes it immediately. Insurance selection applies to the next customer message.
The runtime keeps UUID/history and plays the opener before starting voice capture.

| Check | Final result |
|---|---|
| Backend pytest | **505 passed**; all Stage 1/2 regressions retained |
| Frontend Node tests | **37 passed**, 0 failed |
| TypeScript | passed |
| Production Vite build | passed; main bundle 259.65 kB / 80.43 kB gzip |
| Ruff check + format | passed for backend; new evaluation/smoke scripts also checked |
| Insurance equivalence proof | identical prompt, SDK JSON schema and 104 fresh routing inputs |

The production-registry test now asserts exactly both registered packs; old fixture-pack
tests still verify generic lifecycle behavior. New tests cover explicit matching, ambiguous
currency, grounding, comparisons, refusal/completion, SDK bounds, input/context isolation,
selector confirmation/rejection, failure rollback, lead contracts, branded opener,
human money, TTS-before-listening and no fabricated user turn.

## Insurance 104-case regression

The Router prompt/schema/input remain unchanged from Stage 1 commit `324d6af`.
Prompt SHA-256:
`a17f899a7a8c4dc6425824dc9b052be590c40dd54b6af76a67f3f1e8134a19c3`.
Dataset SHA-256:
`4623e6f590715ac0e2e2119b2c475d0408f2ab9a7fd3c05a0cabd03b0239751b`.

| Metric | Stage 2 | Stage 3 |
|---|---:|---:|
| Primary | 100/104 · 96.154% | 100/104 · 96.154% |
| Full match | 99/104 · 95.192% | 99/104 · 95.192% |
| Multi-intent recall | 21/26 · 80.769% | 25/26 · 96.154% |
| RU primary / full | 98.077% / 96.154% | 96.154% / 94.231% |
| KK primary / full | 95.556% / 95.556% | 95.556% / 95.556% |
| Mixed primary / full | 85.714% / 85.714% | 100% / 100% |
| Invalid outputs | 3 | 3 |
| Provider failures | 0 | 0 |
| Valid routing median / p95 | 2675 / 3532 ms | 3013 / 5570 ms |

These are complete live runs, including failures in the denominator. Overall accuracy is
unchanged; RU decreases while mixed/multi-intent improve despite identical prompt/schema.
This is observed provider-output variability, not a claim of perfect compatibility. Remaining
valid semantic misses are U035 (SC14 rather than SC18) and U090 (missing SC18 beside SC14).
Invalid slot outputs occurred in U003, U008 and U060 and count as incorrect predictions.
Known Stage 2 failures remain documented in `STAGE2_VALIDATION.md`; no targeted evaluation
utterances were added to the prompt. Concurrent live checks can influence provider latency.

Local evidence: `work/evals/stage3-insurance.json`, `.details.json`, `.report.txt`,
`work/stage3-insurance-comparison.log`, `work/stage3-equivalence.json`.
The evaluation saved all 104 predictions/reports before its final Windows console print hit
a cp1251 UnicodeEncodeError. Saved output was validated; subsequent commands use `-X utf8`.

## Separate Product evaluation

`data/product_promoter/eval_cases.json` contains **40 synthetic cases**: 32 product journeys
with 45 turns plus eight selector cases. Includes RU, KK, mixed speech, short continuation,
comparisons, objections, refusal, explicit interest, terminal intents and unsupported topics.
Labels are checked after calls, never passed into agents. Every full run uses a new output
path; there are no selective case retries or hidden excluded provider failures.

| Metric | First complete run | Final release run |
|---|---:|---:|
| Intent | 30/45 · 66.67% | **45/45 · 100%** |
| Structured output | 45/45 · 100% | **45/45 · 100%** |
| Grounding | 45/45 · 100% | **45/45 · 100%** |
| Reply language | 29/45 · 64.44% | **42/45 · 93.33%** |
| Complete case/flow | 17/40 · 42.5% | **37/40 · 92.5%** |
| RU reply language | 22/22 · 100% | **22/22 · 100%** |
| KK reply language | 3/18 · 16.67% | **16/18 · 88.89%** |
| Mixed reply language | 4/5 · 80% | **4/5 · 80%** |
| Continuation | 8/13 · 61.54% | **13/13 · 100%** |
| Cross-pack selection | 8/8 · 100% | **8/8 · 100%** |

General intent definitions, current-utterance language guidance, conservative reply-language
guard and deterministic discovery/matching fixed earlier errors. The final three failed
cases are language choices only: P25 (KK cashback/card), P28 (mixed deposit), P30 (KK USD
deposit). Their intents and product grounding passed. Intermediate complete runs are kept
in ignored local evidence and showed selector/language variability; they were not discarded.

The original grounding metric required the complete conditions string in the reply. After
human presentation separated concise speech from complete conditions, the final metric
checks byte-equivalent displayed records and that numeric speech values come from the
selected source records, including scale conversion. Its definition changed, so the two
grounding percentages are not an identical before/after semantic measure. Independent unit
checks cover all RU/KK source conditions and speech currency formatting.

Final fingerprints: prompt
`0cefc794d2c332ca8229145b75e4b22f43953af6702860a0bb8108153a1976b1`,
dataset `3d0548584c34c8a5708470afca3c122d2fb1c8589dbbf66b07e4ac6c629e70fa`,
catalog `ca84fc45d6f9b7ee557691799ab26f61dab778c1e4cbcd3797753adf109b0d48`.
Final evidence: `work/evals/stage3-product-release.json` and
`work/stage3-product-eval-release.log`.

## Cross-pack HTTP E2E

The final real HTTP smoke through Nginx passed **21 turns**, all nine required journeys
plus natural confirmation in both directions and terminal-session 409 checks.

| Flow | Verified outcome |
|---|---|
| A: deposit | discovery → explicit preferences → grounded DEP-FLEX → interested lead |
| B: card | cashback discovery and product selection |
| C: objection | service fee objection selects an eligible free alternative |
| D: refusal | declined lead, neutral follow-up does not restart selling |
| E: Insurance → Product | travel insurance context stays isolated |
| F: Product → Insurance | card preferences/result stay isolated |
| G: resume both directions | original insurance flow and Product preferences resume |
| H: operator | exact «Конечно, передаю диалог оператору.»; handoff; further turns 409 |
| I: goodbye | localized KK goodbye; ended; further turns 409 |
| Natural switches | Insurance → Product and back only after yes; original request processed |

Evidence: `work/stage3-e2e-release.json/.log`. The first development smoke failed because
its assertion used noncanonical travel-slot names; assertions were corrected to actual
schema fields. Insurance logic/prompt was not changed to satisfy that check. All earlier
evidence remains in `work/`.

## Voice and browser

Actual streaming OpenAI STT used locally generated Microsoft Irina synthetic WAVs, PCM16
mono 24 kHz. Each produced exactly one `utterance.final` and one same-session HTTP turn.
Product discovery → continued amount/liquidity preferences → Insurance SC31 all passed in
one UUID. Actual transcript: «Хочу вложить пятьдесят тысяч тенге с возможностью частичного
снятия.»; amount=50000, currency=KZT. STT after commit: **619 / 534 / 739 ms**.
Separate Insurance payment/operator/goodbye voice regression also passed.

An initial two-sentence fixture had a pause longer than the smoke's 500 ms endpoint and
correctly finalized after «Нужно частичное снятие.»; the amount was never sent to Agent Core.
Diagnostic output preserves that failure. A continuous utterance verifies the full amount;
the browser default remains 2.5 seconds to allow ordinary pauses.

Browser verification uses the real application and browser TTS, no mock Agent. Product
Start displayed an assistant-only branded opening, zero Router latency, first audio
**937 ms**, then returned to listening. Live voice/UI and switch evidence is recorded below.
Physical human speech and native Kazakh voice quality are not claimed as tested.

The browser WAV path displayed the actual spoken 50,000-tenge request, offered DEP-FLEX
with human currency text and resumed voice capture after playback. Controlled subsequent
text checks ran with microphone disabled: Product preferences (amount=50000, KZT, 12 months,
partial withdrawal) → Insurance SC06 travel slots → immediate Product resume with the same
UUID/preferences → explicit application/callback interest (DEP-FLEX, high, completed lead,
global active) → exact operator phrase and stopped loop. Product reply first audio was
738 ms; interest 806 ms; operator 723 ms. Reset created a different UUID; goodbye returned
`ended` in that fresh conversation (first audio 759 ms). Three assistant opening events
(including resume) and five customer/API events form these
eight controlled browser events. No artificial customer opener was inserted.

Screenshots: `work/stage3-human-product.png`, `work/stage3-human-lead.png`,
`work/stage3-browser-handoff.png`; DOM evidence `work/stage3-browser-handoff.txt`.
The final browser check revealed a stale discovery-question flag on goodbye. Product now
sets clarification from the actual reply and clears questions on terminal outcomes; seeded
RU/KK/mixed terminal regressions verify this. Final terminal DOM is also saved in
`work/stage3-browser-goodbye.txt`.
After the trace correction the full backend suite still passed **505** tests, including
76 Product tests. Four final Docker HTTP events separately verify branded opener → goodbye
and opener → operator, both with clarification=false and last_question cleared. Evidence:
`work/stage3-final-tests3.log`, `work/stage3-terminal-tests.log`,
`work/stage3-terminal-wire.json/.log`. Routing prompts, model inputs, conditions and reply
text are unchanged by this trace correction, so the complete live evaluations remain applicable.

Evidence: `work/stage3-voice-release.json/.log`, `work/stage3-voice-diagnostic.json/.log`,
`work/stage3-insurance-voice.json/.log`; browser screenshots stay local in `work/`.

## Docker, security and demo readiness

The final **`docker compose down` → `docker compose up --build`** completed successfully.
Backend and frontend are healthy, bound to loopback 8000/5173; frontend proxies health,
HTTP and voice WS. Backend is non-root. Both dataset paths are explicit in Compose.
An initial Docker build lacked the installed-package Product catalog path; explicit
`PRODUCT_CATALOG_PATH=/app/data/product_promoter/catalog.json` fixed startup.
No Docker volumes or database were deleted.

Focused security review used the project `security-review` skill and deterministic checks.
No cross-pack business-data merge, unbounded routing retry, dynamic imports, write tools or
provider storage were introduced. Selector inputs, failure rollback, type validation and
unregistered targets have offline checks. Traces contain short supplied metadata, no prompt,
environment or hidden reasoning.

Secret scan passed intended files, frontend bundle, local logs and reachable historical Git blobs.
`.env` is ignored. Both final image configs contain no baked API key; layer contents passed
exact-key/pattern scanning: **15,662 backend files**, **995 frontend files**. Runtime backend
credentials are not frontend build arguments. No security exception or public exposure
was needed. Evidence: `work/stage3-security.log` and final rescan
`work/stage3-security-final.log`; final startup after the trace correction is recorded in
`work/stage3-docker-final.log` (both services healthy).

Skills applied: agents-sdk, agent-evals, agent-debugging, security-review, demo-readiness,
and computer-use for the real browser check. No new infrastructure or unrelated packs.
README, architecture, project map, integration handoff and root AGENTS were updated.

## Git and remaining limits

Work targets existing `main` and `origin=git@github.com:ZxZxZ143/banking_voice_manager.git`.
Stage 3 uses ordinary new commits/push; no history rewrite or force push. Local evidence,
audio, build outputs and `.env` remain ignored. Teammate remote branches are unchanged.

Remaining limits are measured language variability above, bounded single-process memory,
no authentication/persistence, installed browser voice availability, unverified physical
microphone/Kazakh audio quality, synthetic catalogs and no real bank/insurer/operator
integration. Interest recording is not actual opening or delivery. The stand stays local.
