# Project Map

## Purpose and requirements

Banking Voice Platform: Insurance Manager for fictional Saqta Insurance and three outbound
sales campaigns for synthetic Merei Demo Bank deposits, cards and loans. A separately selected
Fraud & Security assistant adds shared advisory Risk Intelligence. Prioritize LLM-based
selection in Russian, Kazakh and mixed-language dialogue, context, ambiguity, topic
changes, clarification and handoff. Final MVP requires voice; text remains available.
No encoder intent classifier or hardcoded evaluation utterances.
Business specification: `data/starter_kit/README.ru.md`.

## Current implementation status

- **Segmented identifier hotfix (after 62596fa):** each private part has its own two-turn
  budget: agreement advances, a single valid result gets a short spoken confirmation,
  conflict/unusable evidence repeats only that part once. Exhaustion offers browser
  keyboard input or prepared phone handoff. Domestic 8 remains 8 in read-back; detected
  national 10-digit input uses 3+3+4. Final full confirmation still gates canonical +7
  admission and lookup. Browser segments use 800/650 ms silence; yes/no keeps one STT.
  Verified 1322 backend / 106 frontend tests, Docker and four offline phone smokes;
  all five browser paths completed across retries (live RT/TTS, synthetic mic and
  explicit fault injection). Provider failures/ASR limits remain recorded, no PSTN.
  State-machine and release evidence: `SEGMENTED_IDENTIFIER_CAPTURE_VALIDATION.md`.

- **Voice correction/latency release (after 5e850d3):** private typed RU/KK minimal edits,
  full corrected read-back and final confirmation; two correction cycles/one clarification,
  browser keyboard fallback and phone handoff. Whole-field STT races to pending read-back,
  cancels an unnecessary loser, and never auto-admits sensitive data. Browser adaptive local
  endpointing, mic/socket prewarm during TTS, 400 ms RAM pre-roll and bounded echo rejection;
  immediate hardware cancellation even during pending readiness. Cedar/phone half-duplex and
  completion architecture retained; barge-in/production TTS streaming deferred. Verified
  1265 backend / 106 frontend tests. Actual synthetic-mic Chrome matrix: 26/30 full passes,
  provider/ASR failures safe, final repetition 10/10; TTS-end→active p50 1.8 / p95 4.2 ms.
  Acoustic/recognition limits and release evidence: `VOICE_LATENCY_AND_CORRECTION_VALIDATION.md`.
  Twilio/Vonage live PSTN remains **NOT RUN / pending_credentials**.

- **Insurance completion/context (Part D, Stage 6 branch):** resolved read-only and standalone
  Risk answers enter `conversation.phase=wrap_up`, offer RU/KK further help, acknowledge without
  restarting discovery, and end on no-more-questions. Direct new requests route normally.
  Typed `policy_relationship` retains new/existing context through collection and Risk detours;
  source scenarios plus semantic Router evidence establish it, never ownership authorization.
  New/existing classification is gated to genuine ambiguity; generic SYS_UNCLEAR fallback is open.
  Pure contextual controls have empty selections/segments and never appear as SYS_UNCLEAR.
  Ordinary routing still requires selections/segments. See `CONVERSATION_COMPLETION_VALIDATION.md`.
  Verified: 1160 backend / 97 frontend tests; 14 live RU/KK dialogues (34 turns), zero unnecessary
  classification questions; canonical routing 95.2% primary / 94.2% full, with known remaining errors.

- **Structured speech precision gate (after 545dc10):** application-owned typed risk/outcome
  separates ASR hypotheses from accepted values. All five sensitive fields require explicit
  full read-back confirmation, even when two recognizers agree. Bounded STT starts at audio
  commit in parallel with Realtime; one segmented repair sequence then safe handoff, private
  pending state and no lookup before acceptance. Low-risk regions retain the fast path.
  Completion/Router/Composer rules remain unchanged. Verified: 1216 backend / 97 frontend;
  fresh 112-audio run had 9 correct automatic region accepts, 56 pending confirmations,
  36 repairs, 11 provider failures. One wrong plate had consensus, so confirmation remains
  mandatory. Human-confirmed sensitive precision is unmeasured. See
  `STRUCTURED_SPEECH_PRECISION_GATE.md` for limits, regression and timing evidence.

- **Prior structured speech refinement (Stage 6 branch):** shared expected-slot context,
  high-delay identifier STT, deterministic RU/KK/mixed normalization and one conditional
  bounded gpt-transcribe second pass. Region 01/02/03–20 use Astana/Almaty/other pricing.
  Raw UI transcript stays separate; private one-use receipts feed core, safe flags feed trace.
  Recognition repair is separate from lookup memory; phone/browser share the parser.
  112 synthetic audio cases: canonical 62% versus balanced 43%; five wrong accepted plates
  leave the production precision gate unmet. Five live browser fixtures progressed; local
  Vosk/Whisper and a paired pace pilot were measured in optional environments.
  RU/KK TTS overrides/natural instructions; user prefers existing cedar, no feminine approval.
  Production MP3 remains buffered; streaming is an isolated prototype. Evidence/limits:
  `docs/STRUCTURED_SPEECH_RECOGNITION_VALIDATION.md`.
  Full checks: 1133 backend / 97 frontend tests, TS/Vite, Ruff/format and four phone smokes.

- **Product language / TTS hotfix on Stage 6 branch:** pack-local conservative RU/KK
  continuity and persistent typed explicit preference; language-control commands repeat
  the pending question without sales mutation. Typed HTTP response supports this control.
  Shared backend TTS factory powers browser MP3 playback and existing phone adapters;
  same-origin `/api/speech/tts` is bounded/private, with browser SpeechSynthesis fallback.
  Auto currently uses OpenAI `gpt-4o-mini-tts` / `cedar`; configurable voice/model/RU+KK
  instructions and deterministic speech-only normalization. Silero/Piper CPU prototypes
  ran on Windows/Linux; subjective RU/KK quality remains pending human listening.
  Evidence, model pins, exact tests/latencies: `docs/TTS_QUALITY_VALIDATION.md`.

- **Stage 6 telephony integration (offline):** teammate PhoneRuntime/shared STT/Twilio/Vonage
  selectively ported onto Stage 5B main `48da4bb` on `codex/stage6-telephony-integration`.
  Both use current MessageService/Risk and SQLite with canonical `voice` events. Disabled
  by default; incomplete enabled config fails closed. No outbound trigger or PSTN transfer.
  Live status **pending_credentials**; see `STAGE6_TELEPHONY_INTEGRATION_VALIDATION.md`.

- **Insurance lookup memory hotfix:** per-scenario typed unavailable/failed identifier memory,
  exact failed-attempt deduplication, alternative identifiers and voluntary corrections.
  Owned policy/claim lookup is bounded; unavailable or failed paths end in prepared
  `lookup_exhausted` handoff with retained private context and a safe ManagerSummary.
  No policy lookup by vehicle plate is offered. Validation and measured live limitations:
  `docs/INSURANCE_LOOKUP_MEMORY_VALIDATION.md` (original 754 backend / 80 frontend tests;
  live RU/KK lookup 8/8; real browser and synthetic-STT runtime checked). Stage 5B release
  validation additionally excludes individually failed lookup values from subsequent
  alternative-identifier queries; 757 backend tests and the actual browser flow pass.

- **Stage 5B release validated:** teammate Veyra dashboard
  navigation, shadcn views, responsive styles and polling now consume persisted Stage 5A
  events through one same-origin analytics client. Additive AnalyticsService provides
  overview, session summaries/detail, journeys, risk/assistant aggregates and deterministic
  equal-window anomalies with separate source baselines/cold-start protection. Current
  Conversation Demo/runtime/security/voice components remain; conversation CSS is scoped.
  Source labels are explicit; unavailable transcripts/provider/latency fields stay absent/null.
  Contract/runbook: `ANALYTICS_API_CONTRACT.md`, `FINANCE_DASHBOARD.md`; evidence:
  `STAGE5B_DASHBOARD_INTEGRATION_VALIDATION.md`. All eight browser sections, desktop/narrow
  layouts, live runtime ingestion/TTS, real storage error/recovery and backend restart
  passed; 928 stored events and fixed-clock aggregates survived restart/recovery.

- **Stage 5A:** `app/analytics/` contains typed privacy-safe ConversationEvents,
  deterministic result mapping, post-commit best-effort recorder, EventStore protocol
  and SQLite implementation. Atomic turn batches, unique idempotency, deterministic
  sequence, indexed read filters and typed event/session/summary APIs. Docker named
  analytics_data volume preserves events; conversation state/traces remain in-memory.
  Stage 5A itself did not change dashboard/frontend; Stage 5B integrates it above. Contract:
  `ANALYTICS_API_CONTRACT.md`; evidence: `STAGE5A_STORAGE_VALIDATION.md`.

- **Stage 4:** five manually selected assistants, with `fraud_security` producing
  `FraudCaseResult`. `app/risk/` owns typed signals/assessment, conservative candidate
  precheck and one bounded structured Risk Agent call. Ordinary turns skip that call;
  security advice preserves sales/Insurance state/result and never switches assistants
  or performs bank operations. Source policy and separate 50-case evaluation live in
  `data/security/`. Reusable Risk and Fraud case panels share the existing voice runtime.
  Evidence and measured limits: `STAGE4_FRAUD_RISK_VALIDATION.md`.
  KK Risk hotfix: existing fact/answer-based review conditions precede semantic goodbye;
  high risk alone still does not force handoff. Non-mixed terminal controls use established
  RiskContext response language via the existing continuity helper; mixed presentation
  remains unchanged. Deterministic regressions cover RU/KK review and neutral closings;
  live confirmation is pending manual retest.

- **Outbound sales follow-up:** `product_promoter` sells a preassigned deposit;
  `card_promoter` and `loan_promoter` reuse the implementation with separate manifests/context.
  Bot initiates a branded offer, answers focused conditions/opening questions, adapts to
  explicit preferences and asks once after a soft refusal. Second refusal ends the call;
  explicit stop requests end immediately. Customer cannot switch campaigns through speech.
  Replies are brief, direct and grounded; explanation acceptance uses the actual previous
  question and is separate from application consent. Full conditions remain in UI details.
  Operator/caller chooses before the call; scoring and outbound telephony remain external.
  Eight synthetic products and catalog-owned opening steps. Evidence:
  `OUTBOUND_SALES_VALIDATION.md`. Full Loan Consultant remains unimplemented.

- **Stage 3.2:** manual assistant selection only; no natural selector/forwarding.
  SDK slot schema uses source types/enums/patterns; policy status is short, with separate
  grounded date variants for explicit date questions.
  Insurance scope replies preserve expected fields, identity enquiries stay separate from
  operator requests, filler acknowledgement is optional. Client lookup is bounded to two
  attempts. `DEMO_TEST_PHONE` creates a runtime-only synthetic linked profile; canonical data
  stays intact. Explicit action capabilities and safe manager summaries drive handoff.
  Evidence: `STAGE3_2_MANAGER_VALIDATION.md` (prior-stage evidence).

- **Stage 3.1:** Insurance now separates Router, Decision Policy, grounded facts and a
  pack-local LLM Composer. Both packs have assistant-only openers. Insurance tracks the
  previous question/expected answer, resets repair counters on progress, normalizes requested
  numeric/spoken identifiers and masks public identifiers. Separate 32-dialogue evaluation
  and measured evidence: `STAGE3_1_CONVERSATION_VALIDATION.md` (prior-stage evidence).
  Literal trip duration survives date collection; only an explicit start allows the server
  to derive an inclusive end. Sensitive ID/contact fields are masked in public results.

- **Stage 3:** two production packs (natural selection superseded by Stage 3.2),
  isolated suspend/resume and rollback, six synthetic banking products, grounded discovery,
  comparisons, objections, refusal and SalesLeadResult. Product starts the conversation with
  a branded greeting and uses human currency speech. UI selection, lead/conditions and switch
  traces share the existing runtime/session. Evidence is in `STAGE3_VALIDATION.md`.

- **Implemented:** `POST /api/message`, Router + Composer for normal Insurance turns and
  one SDK call for Product turns,
  strict ID/slot validation, RU/KK/mixed routing contract, single/multi-intent prompt,
  continuation/topic switching, bounded in-memory sessions/traces, confidence policy,
  targeted clarification, source-based quotes, assisted catalog workflows, evaluation CLI and a
  separate opt-in `/dev` manual stand. The integrated production frontend adds same-session
  runtime, microphone/file streaming STT, browser TTS and supervisor traces.
- **Verified offline:** API conversations and concurrency, actual installed SDK HTTP
  transport with fixtures (one request even on provider failure), and official evaluator
  integration. Live 104-case before/after measurements are recorded in `ROUTER_EVALUATION.md`;
  offline fixture checks are not model-accuracy measurements.
- **Still incomplete:** business writes/confirmation, actual identity verification, full
  insurer write integrations, real contact-center transfer and public supervisor feed.
  Legacy `/api/v1/turns/text` remains 501 and is not used. Live routing/STT use the local key;
  TTS uses shared backend synthesis with installed browser voices as web fallback. Missing
  dependencies fail visibly, without mock responses.
- **Deployment:** Docker Compose backend/frontend, Nginx HTTP/voice WebSocket proxy,
  loopback ports 8000/5173, runtime-only secrets and health checks.
- **Not introduced:** Supabase, vector store, RAG, external task brokers or unrelated production packs.

## Navigation

| Path | Responsibility |
|---|---|
| `AGENTS.md` | Persistent engineering rules and Skills |
| `backend/pyproject.toml`, `backend/requirements.lock` | Package, checks, tested dependencies |
| `backend/app/main.py` | FastAPI factory, lifespan and startup command |
| `backend/app/core/` | Settings, contracts, per-app wiring, safe logging |
| `backend/app/api/routes/`, `api/websocket/` | Health/text HTTP and voice WS boundaries |
| `backend/app/speech/stt/`, `speech/tts/` | Shared STT; backend TTS factory, bounded OpenAI synthesis and deterministic RU/KK speech normalization |
| `backend/app/speech/structured/` | Typed whole/segment policies, RU/KK corrections, private source phone styles, normalization, pending read-back race and receipts |
| `backend/app/speech/stt/adaptive_endpoint.py` | Browser local silence profiles with stable partial completeness guard; explicit manual pause remains |
| `backend/app/packs/insurance_manager/speech_capture.py` | Bounded private correction/confirmation/segmented capture before business slots; keyboard capability versus phone handoff |
| `data/speech/`, `scripts/build_structured_speech_dataset.py`, `scripts/evaluate_structured_speech.py` | 100-positive/12-negative synthetic corpus; text/cloud/local/pace comparisons; ignored audio/models/reports |
| `scripts/validate_structured_browser.py`, `scripts/evaluate_tts_streaming.py` | Synthetic-only browser STT/core harness and progressive MP3 experiment, separate ports 8012/8011 |
| `scripts/validate_segment_capture.py`, `scripts/validate_segment_capture.mjs` | Actual Conversation Demo gate; loopback 8015, synthetic audio, live RT/TTS plus explicit bounded-STT fault injection |
| `backend/app/telephony/` | Teammate PhoneRuntime, AgentBridge, bounded sessions and Twilio/Vonage gateways/adapters; offline bench |
| `backend/app/speech/audio.py`, `speech/conversion.py` | Canonical PCM24 contract and bounded PyAV TTS conversion |
| `scripts/smoke_*runtime.py`, `scripts/smoke_stage6_integration.py` | Explicit offline provider fixtures and current core/Risk/SQLite/API smoke |
| `docs/PHONE_RUNTIME.md`, `docs/VONAGE_WEBSOCKET_INVESTIGATION.md` | Phone contract, bounds, provenance and retained startup backpressure fix |
| `docs/STAGE6_LIVE_TELEPHONY_CHECKLIST.md` | Future credentials/console/call validation; not yet performed |
| `backend/app/triage/` | Text preparation; future language/normalization |
| `backend/app/conversation/` | Domain-independent locked session store, message orchestration and statuses |
| `backend/app/analytics/` | Safe event models/mapping, best-effort recorder, EventStore and SQLite queries |
| `backend/app/api/routes/analytics.py`, `dashboard.py` | Backward-compatible event/session/summary routes; additive dashboard read models |
| `backend/app/analytics/dashboard.py`, `dashboard_models.py` | Persistent deterministic sessions/journeys/risk/overview/anomalies and typed contracts |
| `scripts/seed_analytics_demo.py`, `benchmark_analytics.py`, `stage5a_storage_smoke.py`, `stage5b_dashboard_smoke.py` | Compatible synthetic seed/anomaly extension, timings and real API/restart checks |
| `docs/ANALYTICS_API_CONTRACT.md`, `STAGE5A_STORAGE_VALIDATION.md` | Teammate integration schemas/checklist and storage evidence |
| `backend/app/risk/` | Shared input firewall, candidate gate, typed Risk Agent, source policy and business-state-preserving guidance |
| `backend/app/packs/fraud_security/` | Manually selected consultative security pack, safe facts/questions and FraudCaseResult |
| `frontend/src/components/security/` | Allowlisted reusable Risk panel and Fraud case view |
| `data/security/`, `scripts/evaluate_fraud_risk.py` | Synthetic source policy, 50-case separate live Fraud/Risk evaluation |
| `backend/app/packs/contracts.py`, `registry.py`, `lifecycle.py` | Pack contract, manifest/modes, registry, isolated contexts and lifecycle |
| `backend/app/packs/product_promoter/` | Product decision/state/result, deterministic catalog matching and human speech |
| `backend/app/packs/selector.py`, `structured_agent.py` | Legacy unused selector and bounded production SDK transport |
| `backend/app/packs/insurance_manager/` | Production pack, InsuranceResult, local state, insurance processor and public wire projection |
| `backend/app/packs/insurance_manager/agent/` | One-call SDK Router, structured routing plus conversational progress signal |
| `backend/app/packs/insurance_manager/composer.py` | Natural acknowledgement/question, strict output, immutable facts and safe fallback |
| `backend/app/packs/insurance_manager/expected_answers.py`, `privacy.py` | Already requested identifier normalization and presentation redaction |
| `backend/app/packs/insurance_manager/state.py`, `response/lookup.py` | Per-scenario identification memory, failed-value fingerprints, finite owned-record lookup and prepared handoff |
| `backend/app/packs/insurance_manager/data/`, `scenarios/`, `tools/`, `response/` | Canonical-data adapters, catalog/policy, disabled writes, read-only helpers and insurance replies |
| `backend/app/agent/`, `dialog/`, `data/`, `scenarios/`, `tools/`, `response/` | Compatibility exports/adapters for existing consumers; insurance implementation moved into the pack |
| `backend/app/dev_stand/index.html`, `api/routes/dev.py` | Opt-in same-origin text debug stand; not production UI |
| `backend/app/tracing/` | TraceRecord, nullable latencies and bounded collector |
| `backend/app/packs/insurance_manager/conversation_flow.py` | Pack-local completion phase, policy relationship and gated discovery |
| `data/insurance_conversation/completion_cases.json` | 14 synthetic RU/KK completion/context dialogue evaluations |
| `backend/app/evaluation/` | Data/live-eval CLI, exclusive predictions and official evaluator report |
| `backend/tests/unit/`, `backend/tests/integration/` | Offline tests and API smoke checks |
| `frontend/src/main.tsx`, `App.tsx` | Veyra dashboard navigation/source scope and retained live Conversation Demo/runtime |
| `frontend/src/analytics/`, `components/dashboard/`, `components/ui/` | One typed same-origin client, safe parsers, cancellation/polling and teammate dashboard/shadcn views |
| `frontend/src/styles.css`, `conversation.css`, `lib/shadcn-tailwind.css` | Preserved dashboard styling, scoped current conversation CSS and licensed shadcn variants |
| `frontend/src/runtime/ConversationRuntime.ts` | Session lifecycle, transcript/text turn loop, voice input bridge |
| `frontend/src/services/agentClient.ts`, `tts.ts`, `tts/` | HTTP/mock agent; backend audio playback, cancellation and stable locale browser fallback |
| `backend/app/api/routes/speech.py` | Private POST `/api/speech/tts`, strict text/language request, audio-only no-store response |
| `data/tts/eval_samples.json`, `scripts/evaluate_tts.py` | Synthetic RU/KK TTS comparison; ignored audio/metrics/listening sheets under `work/tts-eval/` |
| `frontend/src/components/voice/TtsDebugPanel.tsx` | Manual Russian/Kazakh browser voice check and playback timings |
| `frontend/src/components/voice/VoiceControls.tsx`, `voiceRuntimeBridge.ts` | Streaming mic/file capture UI and final-transcript bridge to runtime |
| `frontend/src/components/voice/BrowserVoiceInput.ts`, `NearEndBuffer.ts` | Per-conversation microphone reuse, prepared/active input, bounded RAM pre-roll and playback-reference echo gate |
| `frontend/src/runtime/voiceTiming.ts` | Bounded content-free monotonic browser timings |
| `scripts/validate_voice_latency.py`, `validate_voice_latency.mjs`, `measure_voice_startup.mjs` | Development-only synthetic session/audio harness, real Conversation Demo overlap gate and baseline/prototype timing |
| `frontend/src/components/trace/traceViewModel.ts`, `TracePanel.tsx` | Defensive view of supplied scenarios, context, clarification, handoff and latency |
| `frontend/src/api/`, `hooks/`, `types/`, `components/` | Client, health hook, contracts and UI modules |
| `frontend/vite.config.ts` | Local /health and /api proxy to backend port 8000 |
| `data/product_promoter/` | Eight synthetic products/opening guides, 40-case regression and 12 outbound flows |
| `data/starter_kit/` | One canonical copy of business/evaluation inputs |
| `docs/ARCHITECTURE.md` | Detailed boundaries, contracts and parallel ownership |
| `docs/AGENT_CORE_3H_PLAN.md` | Supplied implementation plan, preserved unchanged |
| `docs/ROUTER_EVALUATION.md` | Live measurements, failures, general prompt changes and remaining errors |
| `docs/MVP_VALIDATION.md` | Integrated stand verification, startup and remaining demo limits |
| `scripts/` | Live API/runtime smoke checks and saved evaluation comparison |
| `docs/INTEGRATION.md` | Short frontend/Voice Input/Agent Core handoff contract and checks |
| `docs/VOICE_STREAMING_CONTRACT.md` | PCM protocol, dependencies, endpointing and voice checks |
| `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf` | Health-checked local application stack and HTTP/WS proxy |
| `docs/STAGE1_VALIDATION.md` | Current Stage 1 evidence, eval comparison and remaining limits |
| `docs/STAGE3_VALIDATION.md` | Stage 3 product, switching, speech, live eval, Docker and security evidence |
| `data/insurance_conversation/eval_cases.json`, `scripts/evaluate_insurance_conversation.py` | Separate 32-dialogue live conversation metrics, no style judge |
| `docs/STAGE3_2_MANAGER_VALIDATION.md` | Stage 3.2 phone, scope, overlay, handoff, eval/browser/voice/security evidence |
| `docs/STAGE4_FRAUD_RISK_VALIDATION.md` | Fraud/Risk architecture, live accuracy/unknowns, state preservation, browser/voice, latency and security evidence |
| `docs/STAGE3_1_CONVERSATION_VALIDATION.md` | Stage 3.1 dialogue design, measured regressions, browser/voice/security evidence |
| `docs/STAGE2_VALIDATION.md` | Stage 2 migration, context isolation, measured compatibility and regression results |

Backend paths in this table are relative to `backend/app/` where abbreviated.

## Actual and planned flow

Phone: signed Twilio/Vonage admission → per-provider decoder/resampler → PCM16LE mono24k
→ shared StreamingSTT → PhoneRuntime final admission → AgentBridge → current
MessageService.process(..., channel="voice") → existing pack/Risk + EventRecorder/SQLite
→ backend TTS → provider playback ack → listen/terminal cleanup. Same core, no new prompt.
MessageService.end_session finalizes committed calls under the existing lock, without a
new turn; EventRecorder.record_end adds an idempotent safe terminal event. Empty calls
create no analytics conversation. Provider IDs/transcripts/audio are never persisted.
Shared browser STT extraction preserves `/api/v1/voice`; browser TTS now uses the shared
backend factory with SpeechSynthesis fallback, as described in the hotfix evidence.

Startup constructs five registered assistants from canonical Insurance, sales and security
inputs. The shared
store contains global metadata, active pack, isolated typed entries and legacy unused pending-switch
metadata. A pack receives only its own state and a copied global context. Latest InsuranceResult
SalesLeadResult and FraudCaseResult remain in their respective entries. Explicit selection is registry lookup;
natural selection is disabled; out-of-domain questions stay in the selected assistant.

A normal request locks/snapshots the session, activates/resumes the selected pack, calls its
Router, runs deterministic policy/business logic, then Insurance Composer phrases the next
authorized step; Product retains its single-Agent flow. State/result/trace commit together.
Router/provider failures roll back; Composer failures retain business progress and use a
diagnosable safe fallback. Both openers use `/api/conversation/start` with zero model calls.
After commit, deterministic safe events are appended atomically through EventStore in a
worker thread; write failure degrades analytics health without failing the customer reply.
All SDK transport is bounded: no tools/handoffs, max_turns=1, retry=0, disabled tracing/storage.
The extended Insurance schema/prompt have a separate unchanged 104-case live regression run.

The browser fetches real health through Vite. The frontend runtime creates one session ID,
accepts text through `sendText()` or only `utterance.final` through `handleTranscript()`, sends
`POST /api/message` (or either assistant-only start request), displays the reply, prepares input during TTS, then activates listening unless
the API says `handoff` or `ended`. Browser playback uses backend MP3/WAV (`onplaying`/
`onended`) with `speechSynthesis` (`onstart`/`onend`) fallback. A bounded watchdog rejects stalled
speech. Successful handoff/ended states survive TTS failure. A no-audio adapter remains for tests.
The prepared controller cancels hardware/readiness immediately on reset/end/disable/dispose;
legacy controller operations retain serialization. Near-end capture uses a 400 ms private
ring and decoded TTS echo reference; PCM transmission starts only after playback ends.
VoiceControls opens one WebSocket per utterance using that same session ID, reusing the
microphone/AudioContext during an active voice conversation; partials stay
in the voice UI. Real HTTP mode is the default; no key enters the frontend.
The voice check panel has Russian/Kazakh samples, selected voice and playback timings.
The conversation panel shows runtime and backend conversation status. The trace panel
renders only supplied fields, keeps multi-intent order, and uses browser STT/TTS first-audio
timings only when corresponding backend trace timings are absent. It does not show raw trace
data or infer routing decisions. Voice tools are in a disclosure below the main panels.
Mock agent replies and trace fixtures are visibly labeled and enabled only by
`VITE_USE_MOCK_AGENT=true` in Vite dev.
Uncheck «Голосовой ввод» for text-only input with the same runtime/session/TTS. This stops
capture, ignores late voice finals and prevents automatic microphone restart. The local Stop
button does not overwrite backend conversation_status or supervisor trace with a fake end.
The end-to-end path is browser → STT → Router Agent ↔ dialog state → policy → bounded
read-only tools ↔ knowledge/mock backend → response → browser TTS → listen again.
Application traces expose concise reasons and measured latency, never hidden chain-of-thought.

## API and domain contracts

- `GET /api/analytics/events`, `/api/analytics/summary`: optional from/to (timezone-aware,
  inclusive/exclusive), assistant_id, event_type, risk_level, channel=text|voice,
  source=runtime|synthetic_demo, limit (1–500, default 100), offset (0–1,000,000).
  Typed EventPage/AnalyticsSummary; summary ignores pagination and counts latest result
  per session/assistant inside the filter period. Invalid params 422; storage failure
  503 with fixed detail code. Source: `analytics/models.py`, `api/routes/analytics.py`.
- `GET /api/analytics/sessions/{session_id}`: bounded typed SessionEvents, ordered by
  turn/sequence/time/UUID; unknown session 200 with [], total=0, channel=null.
- `GET /health` adds analytics status/backend/failure_count/last_error/last_failure_at.
  Storage failure degrades this section without failing a successful customer turn.
- `GET /health` → 200: status, service, mode=foundation and starter-kit counts.
- `POST /api/message`: `{session_id, text}`; nonblank string ID up to 128 characters,
  text up to 10,000 characters, whitespace trimmed. Reuse the ID for later turns.
  Optional `scenario_mode` selects one of the five packs; `channel=text|voice` defaults to text.
  Optional voice-only `recognition_id` is an opaque one-use STT result; session/turn/slot/text
  binding rejects stale/replayed/mismatched receipts with a safe 422.
  Returns `{session_id, response_text, routing, state, trace, conversation_status, risk?}`.
  Invalid input 422; missing key/model 503; provider failure 502;
  timeout 504; ended/handoff session 409 (use a new ID); busy session pool 503.
  Provider failures do not commit history/state/trace. Invalid structured model decisions
  become SYS_UNCLEAR with an allowlisted routing_error in trace. A source-valid already
  requested identifier may still continue the authorized active workflow; rejected new
  business selections never execute. Genuine repeated failed repairs can lead to handoff.
  Omitted mode continues the active pack or defaults to Insurance; unknown packs return
  422 with `unknown_scenario_pack` without an LLM call. Trace adds pack/mode/lifecycle fields.
- `GET /dev`: standalone debug form, enabled only with `ENABLE_DEV_STAND=true` (otherwise
  404). Reuses editable session ID, shows reply/status/routing/state/trace and browser/backend
  latency. Text rendered safely; no key in browser. New session does not erase older sessions.
- `POST /api/v1/turns/text`: UUID session_id, nonblank text up to 10,000 characters;
  valid input → 501 `{error: {code: not_implemented, message}}`; invalid input → 422.
- Frontend rejects blank/malformed replies, times out after 60 seconds, accepts additive
  response fields, and never substitutes a mock.
  Optional `trace` fields shown in the browser include turn, transcript, language, scenarios,
  alternatives, concise reason, slots, actions, clarification, handoff and `latency_ms`.
  Optional `state` fields shown include active_scenario, scenario_stack and pending_scenarios.
- `WS /api/v1/voice`: one-utterance PCM16 streaming STT; final event includes text,
  nullable language and `stt_after_commit_ms`. See `docs/VOICE_STREAMING_CONTRACT.md`.
  Structured finals add safe `recognition` flags/timings and optional `recognition_id`,
  with no canonical private value. Ordinary wire remains unchanged.
  Recognition adds typed outcome/risk, consensus, verification_method and bounded wait time.
  All sensitive voice candidates require caller confirmation before lookup; region schema
  acceptance stays low-risk. Private pending capture is excluded from public state and models.
- `agent/schemas.py`: RouterDecision has language, response_language (ru/kk), segments, selections,
  alternatives, slots, conversation_signal, optional clarification_question and continuation.
  Typed `policy_relationship` and `relationship_needed` govern contextual discovery. Signals
  `acknowledgement`, `more_questions`, `no_more_questions` bypass business execution only in
  authorized wrap-up/Risk-resume state; those controls allow empty selections/segments.
  Insurance also has optional typed identifier_answer (provided/unavailable/correction/partial/
  unknown + field kind); unavailability and clear alternative identifiers continue the active
  identification step. Private supplied values and failed fingerprints are excluded from
  Router/Composer/public projections. ManagerSummary adds safe business_problem,
  unavailable_fields and failed_lookup_fields, with lookup_exhausted/operator_review.
  SDK transport uses a named-slot list with non-null values for closed JSON
  schema; `to_decision()` restores the slots object. Dependencies use earlier zero-based indices.
  Ordinary SDK selections/segments are nonempty even for system intents. Fresh routing input omits
  storage language defaults; source enum spellings normalize before strict validation.
- `dialog/models.py`: DialogueState includes session/language/response_language/client,
  active scenario, stack, pending scenarios, slots, confirmation flag, turn number,
  unclear and consecutive-low-confidence counts, clarification_options, conversation_status,
  scenario_mode and scenario_slots snapshots, plus bounded history and optional conversation
  metadata (act, question, expected answer/slot, repair attempts, phase, recognized context).
  Insurance conversation adds `phase=wrap_up`, `policy_relationship` (new/existing/
  not_applicable/unknown), per-scenario relationship snapshots and `resume_after_risk`.
  Statuses: active, awaiting_user, awaiting_confirmation, handoff, ended; confirmation is
  reserved, not emitted until a real preview/confirmation workflow exists.
- `tracing/models.py`: transcript, scenarios, alternatives, concise reason, slots, actions,
  session/turn, clarification/handoff/status, active/pending and measured timings
  (router/policy/business/composer/response/total), source_keys, policy_outcome, completed_scenario,
  conversation act/phase/policy_relationship/expected slot/repair count, allowlisted composer_error and optional
  safe manager_summary (field/action names only).
  Actions list only attempted read-only helpers; unmeasured stages = null. Read-only helper
  duration is included in response latency, not a separately measured tools span.
- `PolicySettings` defaults: accept 0.75, low 0.45, legacy low threshold two and unresolved
  threshold three. Conversational policy additionally requires at least two prior distinct
  failed repairs; valid answers/slots reset failure counters. A confident SC37 triggers handoff.
  Confident urgent requests proceed even with a weak secondary intent; only confident
  selections become active/pending, while original evidence remains in routing/history.
  Urgent requests precede normal requests; continuation preserves pending items and slots.
  Clarification/out-of-scope preserve active work; goodbye ends the session. Policy does not
  perform an external operator transfer. SC37 returns a friendly localized message and
  successful handoff; the automatic loop stops while history/trace stay visible.
- A completed read-only answer clears only that scenario: next co-request, then suspended
  stack (LIFO), then older pending work. No remaining work yields `active`, not `ended`.
  Identity correction replaces the old counterpart; a changed established identity drops
  stale policy/claim numbers and scenario slot snapshots unless supplied anew. Owned-record filtering is demo lookup,
  not authentication. Unsupported business actions stay unavailable and never report success.
- Engine inspection and awaiting_confirmation do not authorize execution. Irreversible
  action registration/execution is blocked. No supervisor endpoint/authorization exists yet.

Stage 5B analytics adds `GET /api/analytics/overview`, `/sessions`, `/risk`, `/scenarios`,
`/anomalies`, `/sessions/{session_id}/detail` and `/sessions/{session_id}/journey`.
Original Stage 5A `/events`, `/summary`, `/sessions/{session_id}` retain their schemas.
Lists use bounded limit/offset; aggregates read full safe retained session histories through
EventStore. Detail/journey use source and pagination. Session filters apply to latest
activity/highest analyzed risk/any observed assistant; time is inclusive/exclusive. Unknown
risk differs from analyzed none. Anomalies compare one rolling hour with six prior equal
windows per source, require observed baseline coverage/positive average/minimum volume,
and produce advisory volume messages. No new model calls, in-memory store or credentials.
Full contracts and errors are in `ANALYTICS_API_CONTRACT.md` and backend OpenAPI.

## Data, state and evaluation

`data/starter_kit/` contains scenarios.json (40 + 3 system intents), slots.json (43),
actions.json (31), knowledge_base.json, mock_backend.json (11 clients, 11 policies,
4 claims, 2 payments), dialogs_sample.json (10), dev_utterances.json (104), evaluate.py,
README.md, README.ru.md and README.kz.md. All supplied data is synthetic; reference date
**2026-10-01**. JSON files use metadata wrappers, not bare root arrays. Originals are unchanged;
.DS_Store/AppleDouble files are excluded.

User-supplied `scenarios.json`, `dev_utterances.json`, `evaluate.py` from Downloads /
`voice_router_dataset/case_2/voice_router_dataset` were reverified on 2026-09-23:
all three canonical copies match their supplied SHA-256 hashes byte-for-byte. Keep these
files unchanged as the baseline for future work. Router uses descriptions, not_this_if,
priority, up to two source examples per language, slots and reference date; never dev labels.

Knowledge uses exact dotted-key lookups, not retrieval. Repository reads return copies.
State/traces are bounded and per-process; restart loses them. Use one worker. State keeps
100 LRU sessions and 20 history entries each; traces keep 100 sessions × 100 turns.
Concurrent same-session turns are serialized, distinct sessions can run concurrently,
and active sessions are pinned against eviction. Session IDs are demo correlation IDs,
not authentication: keep the service local until access control is implemented.
SQLite schema v1 `events` persists only allowlisted enums, catalog IDs and booleans plus
opaque correlation metadata; no raw transcripts, collected identifiers, preferences,
replies or free-text reasons. Indexes cover time/session/assistant/type/risk/source.
Unique hash of source/session/turn/type makes retried batches idempotent; started/handoff/
ended keys are unique across a session. Schema and queries: `analytics/sqlite.py`.
No ORM/external DB/RLS/upload service or durable replay exists. Failed writes are
observable but can lose events. Runtime DB/WAL/SHM are ignored and excluded from images.

Evaluation passes only text and fresh state to an injected Router, without expected labels,
and writes `{utterance_id: [scenario_id, ...]}`. The supplied evaluator scores that output.
Offline adapter tests are not model accuracy measurements. `--run` defaults to all 104
utterances, invokes unchanged `evaluate.py`, and saves predictions plus a sibling
`.report.txt` with official metrics and `.details.json` with validated outputs, safe failure
codes, model/prompt/data fingerprints and routing timings. Outputs are exclusive-create.
Default failure aborts; explicit `--continue-on-error` records null decision/empty prediction
and counts it wrong, never fabricating a route. `--limit N` is an explicit subset run.
Concurrency and call-start pacing are configurable; use serial paced runs for comparison.
Allowlisted validation_reason distinguishes output contract failures without saving raw
rejected values. Live manual slot misses/unstable output rejection remain documented in the
evaluation report; a high scenario score is not evidence of complete business behavior.
Stage 1 104-case run (gpt-4.1-mini, temperature 0, concurrency 2, one-second pacing):
primary 96.15%, full 95.19%, multi-intent recall 80.77%; zero provider failures and two
invalid outputs counted wrong. Current comparison and five misses are in STAGE1_VALIDATION.md.
Earlier before/after regressions and complete subgroup/error analysis are retained in
`docs/ROUTER_EVALUATION.md`; no perfect-routing claim is made. Deterministic reply rendering
uses grounded RU/KK translations. Current monolingual request language overrides stale reply
language; a conflicting generated clarification is replaced with a localized fallback.
A small Kazakh-orthography guard also protects reply language from stale Russian context
labels; a borrowed place name or greeting in a longer Russian sentence is not enough.
This affects replies only, not scenario selection or the recorded Router language label.

## Configuration and commands

Stage 6 names (empty examples, no provider credentials): TWILIO_ENABLED (false),
TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER; VONAGE_ENABLED (false),
VONAGE_APPLICATION_ID, VONAGE_PRIVATE_KEY_PATH, VONAGE_API_KEY, VONAGE_SIGNATURE_SECRET,
VONAGE_TEST_FROM_NUMBER, VONAGE_TEST_TO_NUMBER; PUBLIC_BASE_URL, BACKEND_TTS_MODEL,
BACKEND_TTS_VOICE, PHONE_ENDPOINT_SILENCE_MS (1200, 800–5000). Health adds provider
`disabled|unavailable|ready` labels only. Signed HTTP routes: Twilio `/api/v1/telephony/twilio/voice`,
Vonage `/api/v1/telephony/vonage/answer` and `/events`; each provider has WS `/media`.
No public transcript/mock/dial route. Private keys remain outside Git/image, mounted read-only.
Run `python scripts/smoke_stage6_integration.py` for an isolated two-turn core/Risk/SQLite/API
smoke and restart proof; three `smoke_*runtime.py` scripts verify explicit provider fixtures.

Names: OPENAI_API_KEY, OPENAI_ROUTER_MODEL, optional OPENAI_RESPONSE_MODEL (Router fallback), ROUTER_TIMEOUT_SECONDS (45), RISK_TIMEOUT_SECONDS (8), SECURITY_POLICY_PATH,
ROUTER_MAX_OUTPUT_TOKENS (2500), optional ROUTER_TEMPERATURE, BACKEND_HOST, BACKEND_PORT, FRONTEND_ORIGIN,
ROUTER_ACCEPT_THRESHOLD (.75), ROUTER_LOW_THRESHOLD (.45), ROUTER_HANDOFF_AFTER (2),
ROUTER_MAX_UNCLEAR_TURNS (3), ENABLE_DEV_STAND (false), optional STARTER_KIT_PATH,
EVENT_DB_PATH (repository data/runtime/veyra_events.db; Docker /app/data/runtime/veyra_events.db),
ANALYTICS_WINDOW_SECONDS (3600), ANALYTICS_BASELINE_WINDOWS (6),
ANALYTICS_MIN_VOLUME (5), ANALYTICS_ANOMALY_MULTIPLIER (3).
Root .env.example contains no credentials/personal phone; .env is ignored. Optional
`DEMO_TEST_PHONE` seeds a generated local overlay via `data/demo_profile.py`;
`python scripts/show_demo_profile.py` prints only that synthetic profile. Canonical data is untouched.
Health, UI and offline tests need no credentials. Live routing/evaluation needs an explicit
Responses/structured-output-compatible model and key. Local .env has a verified key and
`gpt-4.1-mini`; the model remains configurable, with no implicit production default.
Frontend
`frontend/.env.example` defines `VITE_API_BASE_URL` (empty means Vite proxy) and
`VITE_USE_MOCK_AGENT` (false by default; true works only in Vite dev).
Streaming STT uses gpt-live-transcribe and local faster-whisper Silero VAD (voice extra).
Browser TTS uses the backend response_language for backend synthesis and locale-safe
OS/browser fallback. Configure `TTS_PROVIDER`, `BACKEND_TTS_MODEL`, `BACKEND_TTS_VOICE`,
`BACKEND_TTS_VOICE_RU`, `BACKEND_TTS_VOICE_KK` (blank uses legacy voice),
`BACKEND_TTS_INSTRUCTIONS_RU`, `BACKEND_TTS_INSTRUCTIONS_KK`; all settings stay server-side.
STT models: `STREAMING_STT_MODEL=gpt-live-transcribe`, `STRUCTURED_STT_MODEL=gpt-transcribe`.

PowerShell from repository root:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -c backend/requirements.lock -e './backend[dev,voice]'
./.venv/Scripts/python.exe -m app.main
./.venv/Scripts/python.exe -m pytest backend/tests -q
./.venv/Scripts/ruff.exe check backend/app backend/tests
./.venv/Scripts/ruff.exe format --check backend/app backend/tests
./.venv/Scripts/python.exe -X utf8 -m app.evaluation --check-data
./.venv/Scripts/python.exe -X utf8 -m app.evaluation --run --output predictions.json --concurrency 1 --min-interval-seconds 4 --continue-on-error
./.venv/Scripts/python.exe -X utf8 scripts/smoke_agent_core.py --pace-seconds 4
node scripts/smoke_teammate_runtime.mjs origin/feature/conversation-runtime http://127.0.0.1:8000
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/message -ContentType 'application/json; charset=utf-8' -Body '{"session_id":"abc123","text":"Сколько стоит страховка на машину?"}'
```

Frontend (second terminal, repository root): `cd frontend`, `npm ci`, `npm run dev`.
Keep `VITE_USE_MOCK_AGENT=false` for the full live stand; true is for isolated dev fixtures only.
Frontend checks: `npm test`, `npm run test:dashboard`, `npm run format:dashboard`, `npm run typecheck`, `npm run build`, `npm run test:runtime`,
`npm run test:tts`, `npm run test:trace`, `npm run test:integration`,
`npm run test:voice-bridge`, `npm run test:packs`. Browser speech needs a supported browser and an installed voice;
Kazakh uses an exact/prefix voice when available, otherwise the browser default.
The evaluator needs real predictions from Router v1. Defaults: backend 127.0.0.1:8000,
frontend localhost:5173. Update Vite proxy if changing backend port.
Tested with Python 3.13 and Node 24.13; minimum Python 3.11.

## Skills and next step

Skills live in `.agents/skills/`; read only relevant ones: agents-sdk, agent-evals,
agent-debugging, security-review, demo-readiness. supabase-data is conditional on an actual
Supabase requirement; SQLite uses no external DB skill. agri-rag-vision is irrelevant here.

Integrated `feature/agent-core-router-eval` with `origin/integration/voice-runtime` (0261acc),
which already includes `origin/feature/conversation-runtime` (cb9e7fb) and
`origin/transcribtion` (138d5fb), without modifying teammate branches. Transcript language
and STT timing stay on the runtime side; voice turns add channel=voice to session_id/text.
`/dev` remains an optional separate text debugger, not the full voice stand.

Next: resolve measured routing errors, improve complete RU/KK business wording and actual
identity verification, then implement one preview/confirmation workflow when needed.
SQLite safe event storage is implemented; actual insurer/bank writes remain disabled. Product turns use one bounded
structured agent. Assistant/campaign selection is explicit registry lookup, never a model call.

Stage 5B final release gates passed: 757 backend / 80 frontend tests, all eight browser
sections, Docker runtime/API/WS boundary, privacy, degraded-state recovery and restart.
Next scale work requires measured need: current aggregate reads materialize retained safe events.
Best-effort recording can lose events; no auth/retention/backups/outbox/production-scale claim. Preserve measured O11 backlog: card campaign
→ deposit request can be interpreted as decline instead of out_of_scope. No routing/model
prompt changes were made in Stage 5B; prior model variability remains documented.

Stage 6 offline integration gates: 929 backend / 80 frontend tests, four Windows/Linux
phone smokes, current-core/Risk/SQLite restart proof, focused browser/health/security checks.
Providers stay disabled; next gate is authorized live verification when credentials arrive,
using `STAGE6_LIVE_TELEPHONY_CHECKLIST.md`. Integration branch only, no automatic main merge.
