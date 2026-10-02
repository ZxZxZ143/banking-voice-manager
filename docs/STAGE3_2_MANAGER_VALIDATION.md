# Stage 3.2 — Insurance Manager and local demo backend

Validated locally on 2026-10-02. No new assistant stage, Fraud/Risk pack, database or
voice/runtime redesign was introduced. Skills used: agents-sdk, agent-evals,
agent-debugging, security-review, demo-readiness, computer-use.

## Root causes and changes

- Phone syntax and missing-client lookup were conflated. Complete domestic `8`, international
  `+7` and full ten-digit national numbers now normalize to the same local identifier. RU/KK
  digit-by-digit spoken national numbers are accepted; shorter suffixes need operator/area
  digits, which the application never invents. An unsuccessful
  lookup permits one further identifier/correction attempt, preserves useful business
  fields, then collects remaining useful scenario data and hands off private operations.
- Reactions were effectively mandatory. Composer acknowledgement is now normally empty;
  server guards suppress mechanical filler and consecutive repeated acknowledgement prefixes.
- Short answers lacked enough conversational interpretation. Router/Composer use the last
  question, expected field, active scenario and recent isolated history. A rejected wording
  retains only typed new/existing goal context. Repair preserves the collection target.
- Social/identity questions could be treated as failed business answers or requests for a
  person. Typed scope replies answer briefly, identify the assistant honestly, preserve the
  insurance goal and resume the useful question. Banking requests refer to a separate bank
  products manager while staying in Insurance.
- Production invoked the natural pack selector after an out-of-domain turn. That invocation,
  confirmation/proposal and question forwarding are removed. Explicit UI/API selection alone
  activates another assistant; stored contexts remain isolated. The old selector class/wire
  types remain compatibility artifacts, unused in production.
- Handoff was tied too closely to scenario classification. Application-owned capabilities
  now identify implemented read-only/calculation work and the next unavailable catalog action.
  Required useful fields are collected first; available owned-record/payment/driver checks
  run before handoff. The application never claims an insurer write, SMS or callback occurred.
- Policy status exposed dataset dates and redacted identifiers in a cumbersome sentence.
  Its default fact is now «Сейчас ваш полис действует», with localized expired/future variants.
  Explicit date questions select immutable recorded end-date/period facts in ordinary words.
  The server removes acknowledgements and follow-up filler for this answer. A stale
  continuation flag after a completed answer cannot prevent a fresh follow-up request.
- A broadly typed SDK slot value allowed malformed optional entities to reject the entire
  understood request. The SDK schema now derives names, types, enums, identifier patterns
  and nonempty values directly from the source catalog. Independent domain validation remains.
  A bare «later» callback preference is omitted as insufficient time specificity, so useful
  time collection is not skipped before handoff.

## Local overlay and profile

`DEMO_TEST_PHONE` is an optional `SecretStr` setting read from ignored `.env` at runtime.
`data/demo_profile.py` deep-copies the canonical mock backend and adds linked synthetic
records. No mandatory file mount, image secret, service or starter-kit edit is needed.
Without the setting, canonical tests/evaluations run unchanged. Evaluators explicitly disable
the personal overlay. Run `python scripts/show_demo_profile.py` to print only this profile,
never the API key or unrelated canonical clients.

The configured personal phone is intentionally omitted from this repository report. It is
shown only by the local command and in the developer's local final response. Every other
value below is fictional:

| Record | Values and test purpose |
|---|---|
| Client | `DEMO-LOCAL`, «Демо Клиент (вымышленный)», IIN `000101300000`, Almaty, RU, BM class 7; phone/IIN lookup |
| Contact | `demo@example.invalid`, «Вымышленный тестовый адрес»; no inferred personal data |
| Policy | `SQ-OGPO-990001`, OGPO, 2026-01-01–2026-12-31, premium 28,560 tenge, plate `999DEM02`; status, term, update/renewal/cancellation collection |
| Payment | `DEMO-PAY-990001`, 2026-10-01, 28,560 tenge, successful payment with no issued-policy link; payment-not-issued handoff |
| Claim | `CL-990001`, same policy, incident 2026-09-25, under review; status/dispute, source decision deadline 2026-10-09 |

Policy dates/status still use the canonical demo snapshot reference, 2026-10-01. The active
policy and the separate payment-not-issued case are intentionally distinct synthetic records.

## Action and privacy boundaries

`tools/capabilities.py` is an explicit allowlist of the currently implemented grounded
business functions. Capability changes must accompany implementation and confirmation policy;
neither action names nor the model can enable execution. Canonical `scenarios.json` and
`actions.json` supply required fields and action order. Optional delivery such as SMS is
also unavailable, even if its catalog action is not marked irreversible.

Non-explicit handoff includes `manager_summary`: reason, scenario, collected field names,
known-client boolean, successful read-only checks and next unavailable action. It contains
no identifier values. The supervisor panel displays this safe structure. Explicit SC37
remains immediate and exactly «Конечно, передаю диалог оператору.» in Russian.

Literal phone numbers, including complete national numbers without a country code, are
replaced before Router provider transport; the original validated
number stays in local business state. Composer and public routing/state/trace mask sensitive
identifiers. A documented marker conveys receipt without requiring the model to copy it as a
phone value. Provider storage, retries and sensitive SDK tracing remain disabled. External
STT still processes voice audio; verification used freshly generated fictional audio, never
the developer's personal spoken phone.

## Deterministic verification

- Backend: **585 passed**; Ruff checks passed for backend and changed/new evaluation scripts.
- Frontend: **39 passed**, TypeScript checking and production build passed.
- Source data validation: 40 scenarios, 3 system intents, 31 actions, 104 canonical utterances.
- Canonical routing dataset SHA256 remains
  `4623e6f590715ac0e2e2119b2c475d0408f2ab9a7fd3c05a0cabd03b0239751b`.
- Dialogue utterances remain unchanged. D18's expected next field changes from repeated phone
  to the requested alternative IIN. Dataset SHA256:
  `132ea16dd1bdbb6e76a6d28fa55b46d5b48a8fe71f970eda964c242f826583b2`.
- The dialogue fact-preservation check accepts the default or an offered immutable date
  variant; it does not permit arbitrary Composer prose as business evidence.
- Unit/API checks cover seven phone formats, RU/KK spoken national numbers, no formatting loop, bounded unknown lookup,
  ownership after correction, preserved payment context, four scope kinds, forbidden selector,
  canonical overlay immutability, real check summaries and grounded policy fact variants.

## Live evaluation

All calls use the configured `gpt-4.1-mini`, no hidden retry, fresh canonical state, no labels
in production input and new evidence paths. Earlier runs are retained rather than overwritten.
The final lifecycle follow-up correction is separately verified by unit and browser checks.

| Routing run | Primary | Full match | Multi-intent recall | Provider / invalid failures |
|---|---:|---:|---:|---:|
| Stage 3.1 reference | 102/104 | 101/104 | 25/26 | 0 invalid |
| Stage 3.2 initial | 99/104 | 97/104 | 20/26 | 2 / 2 |
| Intermediate final | 95/104 | 93/104 | 24/26 | 2 / 5 |
| Intermediate verified | 98/104 | 96/104 | 22/26 | 1 / 3 |
| Source-constrained SDK schema | 101/104 | 100/104 | 24/26 | 0 / 0 |
| Final national-number instructions | **100/104** | **99/104** | **24/26** | **0 / 0** |

The final run is two primary/full matches below the Stage 3.1 reference, with one missed
multi-intent component; it is not a perfect routing result. The five full-match errors were
U012 (travel/visa insurance classified unclear), U030 (foreign injury type), U035 (documents
after flooding), U087 (missed payout-dispute component), and U090 (missed documents component).
No evaluation examples or labels were added to production instructions. Evidence:
`work/evals/stage32-routing-national.{json,details.json,report.txt}`. Source-schema evidence
and earlier runs remain separately preserved. Final instructions SHA256:
`23ad6ac9cb0352d5df29586d4f0fbf3f1ebec23397320f82841bd95097202a05`.

The final full 32-dialogue run completed **26/32**, matching the Stage 3.1 complete-dialogue
count. Provider calls succeeded 91/91; eligible turns had **0 premature handoffs (76/76)**;
progress checks had **0 identical repeated questions (36/36)** and 36/36 repair resets;
expected-field continuation passed 26/26. Language passed 91/91, Composer validity 88/91,
next-field selection 37/39, fact preservation 17/18 and terminal outcomes 13/15.
The six incomplete dialogues were D03 (greeting act), D08 (callback terminal), D11 (Composer
validation/fallback), D23 (travel-date field/extraction and resulting fact/terminal checks),
D28 (existing-policy discovery act) and D32 (Composer wording validation). Evidence:
`work/evals/stage32-conversation-release.json` and `work/stage32-conversation-release.log`.

Earlier full dialogue runs also completed 26/32. The source-schema run had one premature
handoff because a bare Kazakh «later» was treated as a usable callback time (75/76); the
field-quality guard fixed that cause. Focused D08/D09 then passed, with an unrelated provider
outage in D19 (7/8 provider calls). The final full run above includes the guard and confirms
76/76 eligible turns. Earlier failed/interrupted evidence is retained, not reported as passing.

Product regression: 45/45 intent/structure/grounding, 43/45 language, 38/40 flow checks,
13/13 continuation, and 8/8 manual-only/no-automatic-switch cases. Its consultation/catalog
implementation remains unchanged. The former selector fixtures intentionally test the new
platform policy instead. Evidence: `work/evals/stage32-product.json`.

## Browser and voice

Real browser checks on the Docker-served `http://127.0.0.1:5173/` verified domestic `8` and
international `+7` developer-phone lookup, the short active-policy answer and a separately
requested human-readable ending date. The latter TTS first audio was 826 ms; short status
first audio was 174–177 ms. Screenshot `work/stage32-browser-policy.png` contains only a
fictional demo IIN and shows «Сейчас ваш полис действует.».

A complete fictional national number without country code was accepted immediately and
used by `find_client`, then offered one alternative IIN lookup. Following a second missing
identifier, the browser collected the useful policy number and handed off with a masked
`client_not_found` manager summary, without restarting identification. Manual selection of
Product and return to Insurance resumed the original SC25 collection context. Product's
opener and its TTS were verified here under the pre-sales-campaign behavior; the later
outbound-sales request is a separate follow-up change.

Small talk and honest virtual-assistant identity preserved the expected IIN and active
insurance context. In this longer unknown-client browser conversation, weather and deposit
turns received visible repair because Router structure was rejected; neither switched pack
or discarded the active goal. One bounded fresh SDK reproduction of the same five-turn
fictional flow subsequently answered all four scope kinds correctly without routing errors
(`work/stage32-browser-reproduction.json`), as did the separate release scope smoke
(`work/stage32-live-scope-release.json`). These are retained as separate observations, not
hidden retries or a claim that every scope response succeeds. Short «Не появился» after an
existing-policy question resolved to the policy and asked whether it was absent in the app
or after payment. Explicit operator request immediately produced exactly
«Конечно, передаю диалог оператору.» (TTS first audio 214 ms).

The add-driver browser flow collected policy/new-driver IIN, accepted the local demo
client's fictional IIN as an alternative to phone, performed `find_client`, `get_policy`
and `get_bm_class`, then handed off for `update_policy`. The customer was told the change
had not been executed; the supervisor summary showed only field/action names, known-client
true and the unavailable next action. TTS first audio was 168 ms.

Real streaming STT → message API verification passed all four fresh synthetic clips: domestic
spoken phone, short contextual answer, small talk and return to Insurance. Every clip yielded
one final transcript and one customer turn; no premature terminal state or pack switch. The
phone progressed without asking its format again. The return selected active SC30. Evidence:
`work/stage32-voice-release2.json` and `work/stage32-voice-release2.log`. A further complete
ten-digit national spoken phone passed in `work/stage32-voice-national-v2.json`, with one
final transcript, a real client/policy lookup and advancement to the policy field; STT took
566 ms. Its first synthetic clip failed because Windows PowerShell interpreted a UTF-8
script without a BOM using the wrong encoding, producing corrupted speech. That failed
recording/report is retained; generating the same words with an explicit UTF-8 BOM fixed
the test fixture. No voice/runtime code was changed to hide this failure.
This is integration verification with
synthetic speech, not a claim about every noisy microphone or grouped spoken number.

## Docker and security

Clean Compose down/start with `docker compose up --build -d` succeeded. The final follow-up
fix was rebuilt normally; both containers are healthy on loopback 8000/5173. Runtime overlay
lookup works through Docker. Backend remains non-root; `.env` and ignored `work/` are excluded
from images. A Docker Hub HTTP 522 build failure recovered on a normal build retry without
cache pruning, container-data removal or new infrastructure.

The pre-publication review passed across **236 intended files**, frontend bundles, local
logs and **531 reachable historical Git blobs**. No API key or configured personal phone
was found in intended repository files/bundles/history. `.env` is ignored and untracked.
Docker image configuration contains neither runtime secret; all backend image layers
(15,708 files) and frontend layers (995 files) were inspected without finding `.env`, the
key or the personal phone in international, domestic or national forms. Evidence:
`work/stage32-security-publish.log`. The final scan after documentation completion also
passed with the same counts (`work/stage32-security-final.log`) before publishing.

## Remaining limitations

The synthetic lookup is not real authentication or access to an insurer's production data.
Sessions are in-memory. Handoff marks application state and prepares context; no actual
contact-center transfer, policy write, claim registration, SMS or callback is connected.
Initial model routing/extraction and conversational phrasing remain probabilistic, and
provider outages can cause visible repair/fallback. Typed immutable facts prevent the
Composer from authoring prices/status/dates or enabling actions, but prose checks are not
a general semantic proof of all possible wording. Literal phone masking does not cover
every possible spoken-number formulation; personal voice data should be treated according
to the configured external STT service. No Fraud/Risk or Stage 4 work was started.
