# Outbound sales follow-up validation

Validated locally on 2026-10-02 after Stage 3.2 commit `3919742`. This follow-up changes
the banking sales behavior; Insurance Manager and the canonical Insurance evaluation data
are unchanged. No Fraud/Risk stage or full Loan Consultant has been started.

## Implemented behavior

Three registered proactive assistants reuse the existing Product implementation with
separate manifests and isolated context:

| Caller-assigned mode | Campaign | Initial offered product |
|---|---|---|
| `product_promoter` | Deposit | `DEP-FLEX`, «Гибкий» |
| `card_promoter` | Card | `CARD-DAILY`, «Повседневная» |
| `loan_promoter` | Loan | `LOAN-DIGITAL`, «Цифровой» |

The caller assigns the campaign before `POST /api/conversation/start`. The demo selector
is labelled «Бот и кампания звонка» and explains that it is an operator setting. After
starting a sales call, the other sales options are disabled until reset. Customer speech
cannot change the assigned category. Explicit operator Insurance switching remains available.
The implementation exposes campaign assignment; it does not implement customer scoring
or actual outbound telephone calls.

The bot opens the dialogue without inventing a customer turn or calling the model. It
identifies the fictional Merei Demo Bank and offers its assigned product with catalog facts.
It answers conditions questions, explains opening and adjusts the offered variant to
explicit needs within that campaign. The catalog has eight synthetic products: the original
three deposits/three cards plus two fictional loans. Existing financial conditions are
unchanged. Opening instructions are new catalog-owned demonstration steps.

Replies are short and direct. For «Какая ставка?» the current offered deposit answers:

> Ставка — 10 процентов годовых, эффективная — 10,47 процента.
> Рассказать, как открыть депозит?

There is no «Проверьте, подходят ли вам его ограничения» or suitability-check preface.
Full conditions remain separately available in `product_conditions`. Two opening steps
are followed by a direct invitation to open/apply. Terms are not invented or altered for
persuasion; an actual incompatible request still needs clarification or another catalog variant.

The one-call structured Agent interprets speech, language, explicit preferences,
`question_topic`, `accepts_explanation` and an explicit stop request. The backend advances
acceptance of the actual previous explanation offer. Consent to hear opening instructions
does not create an application. It records both model intent and effective dialogue act in
the trace. No raw text keyword intent classifier or evaluation-specific utterance rules exist.
The model receives the actual previous question, not the whole product pitch, to prevent
advertised amounts/features from leaking into extracted customer preferences.

A first soft refusal receives one question asking whether the customer is sure. A second
refusal ends the call, even after a reconsideration in between. Explicit requests to stop
calls/sales end immediately. The runtime stops the automatic listening loop for terminal
responses. Applications, callbacks and links remain local interest records; no bank write,
approval, product opening, link delivery or callback scheduling occurs.

## Deterministic checks

- Backend: **603 passed**, `work/sales-tests-603.log`.
- Ruff: **passed** for backend and the Product evaluation script.
- Frontend: **43 passed**, TypeScript and production build **passed**,
  `work/sales-frontend.log`. Docker also builds the production frontend.
- `git diff --check`: **passed**.
- Canonical Insurance `dev_utterances.json` SHA-256 remains
  `4623e6f590715ac0e2e2119b2c475d0408f2ab9a7fd3c05a0cabd03b0239751b`.

Tests cover assistant-only opening for all three campaigns, immutable campaign authority,
amount/term/currency matching, focused rate answers, opening steps without application
consent, explanation acceptance, no suitability preface, one refusal follow-up, reconsideration,
explicit stop, terminal behavior and frontend campaign controls. The prior full test pass
was 600. An intermediate 602-pass/one-failure run expected the Russian spelling «тенге»
inside a Kazakh phrase; the assertion now correctly expects «теңге» and all 603 pass.

## Live model evaluation

Measured with `gpt-4.1-mini`, temperature 0, real local credentials, fresh contexts and
one bounded SDK call per customer turn. Expected labels are used only after inference.
The script accepts an optional `--dataset`, calls the real assistant-only opener and checks
campaign stability. Files are exclusive-created; failed runs are not overwritten.

The original Product fixture now assigns card campaigns before those calls. P01/P11 no
longer expect a customer category-choice question. P26 explicitly exercises a first refusal
and a final second refusal. These changes follow the new behavior; Insurance fixtures were
not edited. A separate 12-dialogue/22-turn outbound set checks the new sales journey.

| Latest run | Original Product: 40 cases / 45 turns | Outbound: 12 cases / 22 turns |
|---|---:|---:|
| Assistant opens assigned offer | 32/32 | 12/12 |
| Intent | 41/45 | 21/22 |
| Valid structured output | 45/45 | 22/22 |
| Catalog grounding | 45/45 | 22/22 |
| Reply language | 41/45 | 22/22 |
| Fixed campaign | 45/45 | 22/22 |
| Complete case | 32/40 | 11/12 |
| Continuation | 11/13 | 10/10 |
| Manual-only selection / no automatic switch | 8/8 each | Not in this dataset |

Latest evidence: `work/evals/sales-product-concise.json` and
`work/evals/sales-outbound-concise.json`. There were no provider or invalid-output failures
in these two runs. JSON evidence records prompt/catalog/dataset fingerprints and each turn.

The remaining outbound failure O11 interprets a request for a deposit instead of the
assigned card as a refusal rather than out-of-scope. The campaign still remains card and
no other product is offered. Original regression failures: P01/P11 generic discovery intent,
P09 farewell interpreted as first refusal, P21/P28 mixed-language reply choice, P25/P30
Kazakh detection, P29 currency answer intent and P30 callback action. These are measured
model limits, not an all-pass claim. Full API output, grounding and campaign invariants pass.

Earlier complete evidence is retained under `work/evals/sales-*`: initial release,
conversation, progression and question-context runs. Initial outbound completion was 7/12;
later conversation had one real provider failure, while progression reached 11/12.
The question-context run reached 10/12 and exposed repeated conditions after acceptance
of the opening offer. The final typed explanation-acceptance signal fixes that progression
and passes all 10 continuation checks. No hidden retry or best-run substitution is used.

## Browser and Docker

Real local browser checks use the Docker backend through the frontend proxy, live Product
Agent and browser TTS. Text input is enabled for reproducible utterances; microphone input
is disabled during these browser steps. The earlier Stage 3.2 voice validation remains
documented in `STAGE3_2_MANAGER_VALIDATION.md`; no new sales STT claim is made here.

Verified deposit flow: assistant opens before the customer, «Какая ставка?» produces the
short direct response above (Router 2.24 s, browser first audio 843 ms), then «Да, объясните»
produces the two opening steps and «Хотите открыть этот депозит?» (Router 1.94 s, first audio
800 ms). It stays consulting and does not create an application. Earlier rate response with
the unwanted suitability preface was observed and replaced; its result is not presented
as the current behavior. Screenshots are local ignored evidence:
`work/sales-browser-short-rate.png`, `work/sales-browser-opening.png`.

On the final Docker build, a fresh deposit call with «Сейчас неинтересно» produced one
refusal-check question; «Нет, я уверен» then returned the goodbye with `ended`, `declined`
and phase `closed`, disabled input and no listening restart. Browser Router times were
2.22 s and 2.05 s; first audio 779 ms and 846 ms. Evidence:
`work/sales-browser-refusal.png`. Separate reset/start checks also show the card opener
offering `CARD-DAILY` and the loan opener offering `LOAN-DIGITAL`, with the other sales
options disabled during the call. No client category-choice question appears.

`docker compose up --build -d` rebuilt both production images and started the backend
healthy and frontend running; evidence `work/sales-docker-concise.log`.
The final source synchronization also passes, `work/sales-docker-final-sync.log`.

## Security and repository scope

`work/sales-security-final.log`: **passed** for 239 intended files, frontend bundles,
local logs and 573 reachable historical Git blobs. The backend image scan inspects 15,709
files and the frontend image scan 995 files, including layers/configuration. Neither the
local API credential nor the personal demo phone occurs in intended repository content,
reachable history or images. `.env` stays ignored; credential/phone are runtime configuration.
The local override, recordings, screenshots, reports and logs under `work/` are not staged.
All six original banking products retain their original financial fields; only new opening
guides and the two synthetic loan products were added.

## Reproduce

1. Start Docker using the existing ignored local `.env` and `docker compose up --build -d`.
2. In the demo choose «Продажа депозита» before starting; disable microphone for text checks.
3. Start. The assistant names the bank and offers its deposit first.
4. Ask «Какая ставка?», then accept the offer to explain opening. Expect short grounded
   answers and opening steps, with no application recorded merely for hearing them.
5. Reset and start a new deposit call. Refuse once, then confirm refusal. Expect one question,
   then an ended call. A hard stop request must end immediately.
6. Reset before choosing card or loan. Their openers offer only their assigned category.
7. Run deterministic tests and either Product evaluation dataset independently when needed.

Skills actually used for this work and the preceding Stage 3.2 validation: `agents-sdk`,
`agent-evals`, `agent-debugging`, `security-review`, `demo-readiness`, `computer-use`.
