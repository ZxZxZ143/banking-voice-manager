# Stage 6 telephony integration validation

Date: 2026-10-03. Integration branch: `codex/stage6-telephony-integration`.
Base: clean, fast-forward-updated main `48da4bbe93ef31da8be1b2931e3187775c360a77`.
Stage 5B and Insurance hotfix `a7f5e33` remain ancestors. No blind merge, source-branch
rewrite, force push, outbound dial, public tunnel or real operator transfer was performed.

**Offline integration gates pass. LIVE PSTN: pending_credentials / NOT RUN.**
The integration branch is the delivery target; main is not merged in this task.
Reconciled production integration: `0d9551a`; offline fixtures and smoke coverage:
`5186fc0`. Documentation is committed separately on the same branch.

## Provenance and pre-edit inventory

Inspected remote branches, graph, diffs, merge bases and dependencies before porting.
Their common merge base with current main is `5193ad74a0205633e4f3c097f39945b7c6c29291`.
The temporary per-file inventory and original Git blobs were kept under ignored
`work/stage6-inventory.json` and `work/stage6-source/`. Current main won every core,
analytics, pack and frontend reconciliation.

| Source branch | Inspected tip | Reused work |
| --- | --- | --- |
| `origin/feature/backend-phone-runtime` | `631d8d67b1622c1069c72ed3a7c12355cc271795` | `4474386` historical event foundation inspected; `79f608a` PhoneRuntime, bridge, registry, shared speech, bench/tests/docs |
| `origin/feature/twilio-telephony-provider` | `24a98f0be44431513816e6eae4a1ba5e546097d5` | `d7ea2e6` TwiML, signed admission, stream isolation, G.711 codecs, acknowledgements and fixtures |
| `origin/feature/vonage-telephony-provider` | `642aebf8ab28746644c6109301a5660b1ec9cb4e` | Superset of both earlier branches; `416a416` gateway/L16, `8806142` configuration validation, `5c90895` bounded STT startup backpressure, `642aebf` phone endpoint/timing |

Dependency order is PhoneRuntime → Twilio → Vonage; final phone modules were selected from
the last superset, retaining one implementation of each shared boundary. The design and
provider code originated in those teammate branches, not in a replacement implementation.

| Files/group | Current-main equivalent and integration action |
| --- | --- |
| `backend/app/telephony/{runtime,agent_bridge,sessions,base,audio,bench}.py`, `providers/mock.py` | New; reuse orchestration and fixtures; map to current MessageService and canonical `voice`; remove historical event writer |
| `telephony/{twilio_gateway,vonage_gateway}.py`, `providers/{twilio,vonage}*.py`, `api/routes/{twilio,vonage}.py` | New; port actual codecs/auth/protocol/ack lifecycle; add HTTP body-hash fail-closed check |
| `telephony/vonage_calls.py` | Reuse origin/application/number/RSA validation only; remove outbound SDK/trigger entirely |
| `speech/{audio,conversion}.py`, `speech/stt/{streaming,streaming_provider}.py` | Port shared extraction; browser wrapper and endpointing use it without changing browser protocol |
| `speech/tts/*` | Identical current-main backend TTS reused, no new speech implementation |
| `core/config.py`, `main.py`, `api/routes/health.py` | Add only provider settings, optional composition/cleanup and typed readiness; current routes/services retained |
| `conversation/service.py`, `analytics/recorder.py` | Add transport-close method and safe idempotent terminal projection; no routing/model/prompt change |
| `backend/tests/unit/test_{phone_runtime,twilio,vonage}.py`, `integration/test_phone_message_bridge.py` | Adapt teammate fixtures to current channel and lifecycle; replace obsolete raw-event assertions with state/output checks plus current SQLite integration coverage |
| Three `scripts/smoke_*runtime.py` | Adapt explicit offline provider mocks; remove historical store/outbound references |
| `scripts/smoke_stage6_integration.py`, `integration/test_stage6_telephony.py` | Add complete current-core/Risk/SQLite/API/persistence smoke and regressions |
| `.env.example`, `.gitignore`, `.dockerignore`, dependency files | Empty provider config, key exclusion and only necessary tested dependencies |
| Dashboard `views.tsx` | One label: “Voice conversation channel” includes browser and phone; no design/contract change |
| Existing docs plus `PHONE_RUNTIME.md`, `VONAGE_WEBSOCKET_INVESTIGATION.md` | Reconcile historical descriptions with current persistent dashboard; keep provenance and bounded-backpressure explanation |

Intentionally not imported: historical MessageService/packs/prompts/registry/frontend,
`app/events` and its raw-transcript in-memory store, old health/composition replacements,
old channel enum, outbound `create_trial_call`/`start_vonage_call.py`, Vonage outbound SDK
dependencies and their exclusively outbound tests. The 757 current-main tests were retained;
one strict health expectation gained the new additive telephony field. No assertion removed.
Current Dockerfiles/Compose remain authoritative; PyAV wheels worked without extra OS packages.

## Current application path and measured behavior

Signed provider → inherited decoder/resampler → PCM16LE mono24k → shared StreamingSTT →
PhoneRuntime/AgentBridge → current MessageService (`channel="voice"`) → selected current
pack/shared Risk → backend TTS → provider playback acknowledgement. No HTTP loopback,
phone-specific agent, prompt, risk engine or public mock/transcript injection route.

One physical-call ID maps to one UUID. Two turns retain state; simultaneous Insurance/Fraud
calls have separate UUIDs, captures, contexts, playback and events. Final-only admission,
half duplex, duplicate stream/final rejection, bounded tasks/queues/timeouts and late-audio
suppression pass. Vonage's delayed-start test consumes all 21 frames instead of failing at
frame 17; timeout and signed terminal interruption while blocked also pass. A 1,000-turn
cap additionally applies even without STT item IDs.

Insurance phone regression: policy number requested → unavailable → phone requested →
failed phone → IIN requested → failed IIN → `lookup_exhausted`/handoff. Memory retains the
unavailable/failed fields and does not ask again after terminal. Final reply precedes close.
Goodbye and explicit operator handoff persist exactly one matching terminal event. No human
connection is claimed. State remains in memory; no call resumption after application restart.

Shared Risk runs with `channel=voice`, keeps Insurance selected, persists advisory signals;
failure persists `analysis_status=unavailable` and precautionary guidance without fabricated
signals. Phone TTS uses the Risk reply's language rather than retained business language,
matching existing browser behavior. No business routing or expensive LLM dataset was changed
or rerun; external Agent/STT/TTS outputs in phone tests are explicit fixtures.

Current EventRecorder/SQLite is the only production event source. Existing safe business/Risk
mapping is reused. Transport end finalizes only committed conversations without an extra
turn; no-answer/empty calls do not fabricate analytics. Handoff stays handoff. Storage
failures preserve replies and honestly degrade health. No transcripts, replies, audio,
phone/IIN/auth values, whole state/trace or provider IDs enter persisted events.

The complete smoke created **7 events / 2 turns / 1 UUID** including Insurance result, Risk
and terminal closure, then queried current overview/sessions/detail/journey/risk/scenarios/
anomalies APIs. A fresh app/EventStore returned identical session history/detail. Those
`source=runtime` fixture events use a temporary DB only; they never pollute the Docker volume.

## Release checks actually executed

| Gate | Measured result |
| --- | --- |
| Full backend `python -m pytest backend/tests -q --tb=short -p no:cacheprovider --basetemp=work/stage6-full-02` | **929 passed**, 39.05 s; 757 baseline + 172 new, no skip/failure |
| New PhoneRuntime unit suite | **42 passed** within full suite |
| New Twilio unit suite | **60 passed** within full suite |
| New Vonage unit suite | **54 passed** within full suite |
| Adapted current MessageService bridge | **1 passed** |
| New complete Stage 6 integration/failure/security suite | **15 passed** |
| Existing Insurance memory, Risk/Fraud, SQLite/dashboard and browser-STT suites | Included unchanged in full backend pass |
| Frontend `npm test` | **80 passed**, 0 failed/skipped; final label-change run 1.19 s |
| `npm run typecheck`, `npm run build` | Passed; production Vite bundle built |
| `npm run format:dashboard -- --end-of-line auto` | Passed; Windows checkout CRLF preserved |
| Ruff check + format for `backend/app backend/tests` | Passed, **198 files** formatted |
| Ruff check + format for four phone smoke scripts | Passed, **4 files** formatted |
| `git diff --check` | Passed |
| `python -m pip check` | No broken requirements |
| Four offline smoke scripts, Windows | All passed; no live speech/model/provider requests |
| Same four scripts streamed into Linux Docker backend | All passed; real PyAV mu-law/L16 conversion and fixture playback acknowledgements |

During adaptation, obsolete test-only channel/event assertions and the strict health
expectation failed and were reconciled to current contracts. Initial sandbox pytest setup
could not access its Windows temp directory; authorized runs used isolated `work/` paths.
Plain Prettier rejected CRLF checkouts; the explicit end-of-line-auto check passes without
rewriting unrelated files. An exploratory whole-`scripts` Ruff scan also reported existing
issues in `stage3_voice_smoke.py`, `test_openai_stream.py`, `transcribe_audio.py` and formatting
in older scripts. Those are outside the repository's documented backend lint gate; all
changed/new Python passes its applicable configuration. No broad legacy cleanup was made.

## Docker, persistence and focused browser QA

`docker compose up --build -d` passed with both providers disabled. Backend/frontend are
healthy at loopback **8000 / 5173**. Backend runs UID 1000. No `.env` or PEM/key file exists
under `/app` in the image; provider credential presence checks returned false without
printing values. Only config names/empty examples were added; local `.env` was not edited.

Normal persistent volume survived rebuilds and `docker compose restart backend`:
**932 events / 190 sessions** before and after (includes one new zero-model browser Insurance
opener, in addition to Stage 5B history). Full safe event history plus anomaly response at
fixed `as_of=2026-10-03T15:00:00Z` had identical SHA-256:
`c40adb4ec8f1911e8e8100f703c7cf8646c067b9ba1ce6b3e6ccf2d33d7e2b27`.
Separate temporary-phone smoke also proves persistence across fresh app/store construction.

Actual app at `http://127.0.0.1:5173` was opened through browser control. Focused checks:
Overview populated; Live Calls rendered existing labelled synthetic voice sessions; detail
opened with safe business/risk fields; Journey ordered started → selected → fraud case →
risk → ended. Conversation Demo displayed all five selectors, Risk advisory panel, normal
Insurance opener and enabled text fallback after browser speech state completed. Leaving
and returning retained the same UI session/history. No real microphone/PSTN or audible
speech-quality claim is made; browser voice protocol regression uses the existing offline
WebSocket fixtures. Full eight-section/responsive validation remains Stage 5B evidence.

One visible integration label was corrected: the combined `voice` metric no longer says
“Browser voice channel”. No dashboard redesign, source guessing or provider metadata was added.

## Focused security review

Used project `security-review` alongside `demo-readiness` and `agent-evals`.
Reviewed auth/authority from public routes to gateway/call ownership, PCM/STT, MessageService,
TTS, safe logs, SQLite/API and Docker/frontend boundary.

- Twilio: official signature validator, configured origin/account binding, bounded signed
  form, admitted CallSid/StreamSid matching, sequence/chunk/timestamp checks, per-stream
  mark ownership, duplicate/closed replay rejection. Forwarded Host cannot select signature URL.
- Vonage: HS256 only, issuer/account/age/jti validation, optional application binding, body
  hash verified for HTTP (missing/tampered hash rejected), exact configured caller/destination,
  admitted UUID and native WebSocket controls. RSA key validation now gates enabled composition.
  Signed-media bearer has no body; no global jti replay cache or across-restart tombstones claimed.
- Frames, JSON/body sizes, active/pending/lifetime calls, final IDs/turns, STT input,
  conversion duration, queue/backpressure and playback/cleanup waits are bounded and tested.
  Failures in one call leave the other active call intact. Raw dependency errors are not logged.
- Source/built-bundle scan found **0 matches** for actual locally configured secret values;
  **0 tracked `.env`/private keys**. Keys excluded from Git and Docker context. No frontend
  credential setting, raw persisted transcript/provider metadata or public injection route.
- Production fixture fallback is absent. Phone unit mocks are explicitly offline. Authentication
  is never disabled for tests. Current analytics privacy schema is unchanged.

No unresolved high-impact blocker found within this offline integration scope. This is not
a penetration test, dependency CVE audit or live provider security validation. Existing
demo APIs remain private/unauthenticated; expose only signed telephony ingress later.
Transport ownership/replay memory is single-process; provider retries, TLS/console setup,
real latency/echo/audio quality and cancellation cooperation still require live evidence.
Best-effort analytics can have gaps, including bounded transport-finalization failures.

Protocol checks consulted primary sources: [Vonage signed webhooks](https://developer.vonage.com/en/getting-started/concepts/webhooks)
and [Voice WebSockets](https://developer.vonage.com/en/voice/voice-api/concepts/websockets).

## Provider readiness and remaining gate

| Provider | Code integrated | Offline provider tests | Credentials present | Live call |
| --- | --- | --- | --- | --- |
| Twilio | Yes, teammate implementation reconciled | 60 + common/integration fixtures, Windows/Linux smoke pass | No | **NOT RUN — pending_credentials** |
| Vonage | Yes, including startup backpressure fix | 54 + common/integration fixtures, Windows/Linux smoke pass | No | **NOT RUN — pending_credentials** |

Later procedure: `STAGE6_LIVE_TELEPHONY_CHECKLIST.md`. No credential request is necessary to
finish this offline integration. Do not infer live readiness from gateway `ready` health.
Do not merge main automatically; separate authorization/live evidence is required for that
next release decision. Outbound dialing, real human transfer and O11 Card campaign deposit
request interpretation remain outside this task.
