# Structured speech recognition validation

## Inspected baseline (2026-10-03)

Branch: `codex/stage6-telephony-integration`. Providers remain disabled; no PSTN
activation or credential changes are part of this work.

Browser `VoiceControls` captures microphone/file audio as mono PCM16LE at 24 kHz,
100 ms frames, over one-utterance `/api/v1/voice`. `voice.py` validates origin,
UUID, framing and pause; local Silero detects speech/endpoints. `relay_stream`
forwards frames to OpenAI, commits once, emits partials and one raw final.
`voiceRuntimeBridge` admits the final; `ConversationRuntime` displays it and posts
`/api/message` with the same session ID and channel=voice. It awaits the business
reply and backend MP3 playback, with browser SpeechSynthesis fallback, before
listening again. Terminal states stop this loop.

Phone Twilio mu-law 8 kHz and Vonage PCM16LE 16 kHz adapters use PyAV to produce
the same PCM24 framing. `PhoneRuntime` shares `OpenAIStreamingSTT`/`relay_stream`,
admits one final and calls `AgentBridge`/the same MessageService, then the shared
TTS factory and provider codec/playback acknowledgement. It is half duplex.

Both STT entrances currently call `configure_transcription`: static insurance
prompt, languages kk/ru, medium delay, no expected-slot context or second pass.
Audio has a 120-second byte bound and is forwarded without utterance retention.
Insurance `expected_answers.py` handles literal regex identifiers and isolated
RU/KK digits for phone/IIN. It lacks grouped numbers, spoken prefixes/plates and
region codes. This places raw ASR repair pressure on the business router and can
repeat collection questions. Recognition and lookup failure are not distinguished.

The authoritative starter-kit regexes are phone `+7` plus ten digits, IIN twelve
digits, policy `SQ-(OGPO|CASCO|TRVL|PROP|NS|DMS)-` plus six digits, claim `CL-` plus
six digits, plate three digits/two or three Latin letters/two digits. Region is
the coarse enum almaty/astana/other. Synthetic records need no IIN checksum.

Sources checked: [OpenAI realtime transcription](https://developers.openai.com/api/docs/guides/realtime-transcription),
[file transcription](https://developers.openai.com/api/docs/guides/speech-to-text),
[speech](https://developers.openai.com/api/docs/guides/text-to-speech),
[model lifecycle](https://developers.openai.com/api/docs/deprecations),
[government registration-code table](https://www.gov.kz/article/22592).
The installed OpenAI SDK also declares gpt-transcribe, keywords and languages.

## Implemented pipeline

`speech/structured/context.py` defines a frozen, bounded TranscriptionContext.
MessageService reads the active Insurance expected slot and RU/KK response language;
STT receives only its kind, public format instructions and product-prefix keywords.
Aliases include drivers_iin/new_driver_iin → iin and culprit_vehicle_plate → plate.
Unknown slots and other packs retain ordinary medium-delay streaming. Structured
slots use high delay; xhigh was not promoted or benchmarked. Both languages remain
enabled. No known customer value, development label or full business state is a hint.

```text
expected-slot snapshot → session.update(prompt, keywords, languages, delay)
PCM24 → gpt-live-transcribe → raw first transcript → deterministic candidates
    one schema-valid candidate → accept without another model call
    invalid/ambiguous → at most one gpt-transcribe call on the same bounded PCM
    accepted value → server-only receipt → original business slot / normal lookup
    unresolved → targeted RU/KK repair → alternative identifier or prepared handoff
```

Models are configurable through STREAMING_STT_MODEL and STRUCTURED_STT_MODEL.
The current model names and SDK parameters were checked against official OpenAI
guidance and installed SDK declarations; no deprecated transcription snapshot was
added. The bounded WAV request uses RU+KK, the format prompt and public keywords,
max_retries=0 and a 20-second timeout. The first transcript has a separate 30-second
post-commit deadline. Only structured turns retain PCM, with the existing 120-second
byte limit. Completion/cancellation clears it; no runtime audio file is created.

The deterministic normalizer supports RU/KK individual numbers, unambiguous grouped
cardinals, mixed forms, policy/claim prefixes and context-specific Latin letter names
or Cyrillic-looking glyphs. It bounds candidate generation to 64 candidates/60 tokens.
Source regexes validate final phone, IIN, policy, claim and plate values. Missing digits
or letters are never filled. More than one valid candidate is a repair, not a guess.
An explicit first-pass ambiguity cannot be replaced by an unrelated second-pass value.
The literal fallback and existing identifier-memory/alternative-route behavior remain;
a clear phone supplied while policy is expected is admitted as a phone.

Browser final events retain the first-pass raw `text` and add safe `recognition` metadata
and an opaque `recognition_id`; displayed text is never replaced by a canonical value.
The server stores the canonical result only in a bounded one-use receipt, bound to
session, turn, expected slot and transcript hash (100 entries, 120-second expiry).
POST /api/message admits that receipt only on channel=voice under the session lock.
Invalid/stale/replayed/cross-session receipts return a safe 422. Clients cannot supply
canonical values. Voice requests without a receipt still use deterministic text parsing,
with no audio second pass. PhoneRuntime shares exactly this parser and receipt flow;
provider codecs and legacy fixture STT implementations remain compatible.

The business router cannot repair structured ASR digits in a voice turn. Accepted
private speech routes with a field-kind marker and applies the validated value afterward.
Recognition failure has separate per-slot counters and performs no lookup. One targeted
repair precedes an existing alternative identifier; exhaustion produces a safe prepared
ManagerSummary. Successful recognition and scenario changes clear relevant counters.
Valid values absent from the synthetic database use the existing lookup progression,
without being relabelled as ASR failure. Terminal state, Risk and Stage 5B remain intact.

## Region codes and screenshot regression

The source format is unchanged: almaty/astana/other pricing. Code 01 maps to astana,
02 to almaty, and 03–20 to other. Names also work; Almaty city and Almaty province
(05) are distinct. Conflicting names/codes, negated regions and 21 are rejected.
The parser runs only when region/plate context is expected. No pricing rules changed.
`регион ноль два`, `это регион ноль два` and `регион 02` resolve to code 02 and almaty.
Tests cover every code 01–20, spoken variants and plate suffixes.

Sources: [government code table](https://www.gov.kz/article/22592) and the
[Ministry of Internal Affairs announcement of codes 18–20](https://polisia.kz/zhanga-oblystardyng-avtokolik-ieleri-ajmaqtyng-zheke-kody-bar-nomirlerdi-ala-bastady/).
They identify 18 Abai, 19 Jetisu, 20 Ulytau. The source comment and implementation
remain deterministic; there is no model-based region/pricing inference.

## Synthetic evaluation (2026-10-03)

The checked-in corpus has 100 positives with the requested 20/20/20/15/10/15 split,
plus 12 negatives; positives are RU 38, KK 32, mixed 30. Three region utterances had
incorrect original language labels; they were corrected and all affected provider rows
rerun. Existing audio was retained (those files' original language instruction profiles
are not a claim about the actual words spoken). Generated audio uses coral/nova/shimmer,
with individual/grouped numbers, fillers, Latin/Cyrillic artifacts and spoken letters.
All 112 audio fixtures were evaluated by both OpenAI modes and both local engines.

This is a synthetic stress corpus, generated using OpenAI TTS and tested partly using
OpenAI STT. The expected values describe the source text; nobody manually verified every
generated waveform. TTS can omit/change a letter before STT sees it. These results measure
the end-to-end synthetic system, not real-customer accuracy. The text-only run measures
the parser alone; its 100% raw-text exactness is automatic by construction.

The balanced comparison is an ablation using generic medium-delay transcription,
no second pass, and the **same new parser**. It is not a replay of the original legacy
Insurance normalizer or a statistically controlled model-quality experiment. Realtime
sessions are nondeterministic. Evaluation resume reran failed transport cases; production
has no retry loop. Initial handshake/ping/timeouts and one generation interruption occurred;
the completed retained reports below have no outstanding provider failures. Do not infer
100% service availability from these resumed runs.

| Positive canonical accuracy | Balanced ablation | Structured OpenAI | Vosk constrained | faster-whisper base |
|---|---:|---:|---:|---:|
| Phone (20) | 25% | 55% | 50% | 10% |
| IIN (20) | 60% | 75% | 55% | 20% |
| Plate (20) | 40% | 50% | 35% | 25% |
| Policy (15) | 40% | 66.67% | 13.33% | 33.33% |
| Claim (10) | 60% | 70% | 40% | 30% |
| Region (15) | 40% | 60% | 73.33% | 26.67% |
| All positives (100) | 43% | **62%** | 45% | 23% |
| RU | 76.32% | 84.21% | 73.68% | 52.63% |
| KK | 28.13% | 71.88% | 40.63% | 0% |
| Mixed | 16.67% | 23.33% | 13.33% | 10% |

| Metric across 112 cases | Balanced | Structured OpenAI | Vosk | faster-whisper |
|---|---:|---:|---:|---:|
| Raw transcript exactness | 0.89% | 0.89% | 31.25% | 0.89% |
| First-pass positive accuracy | 43% | 55% | 45% | 23% |
| Conditional second-pass positive recovery | N/A | 7/41 = 17.07% | N/A | N/A |
| Correct among accepted | 43/45 = 95.56% | 62/67 = 92.54% | 45/52 = 86.54% | 23/29 = 79.31% |
| Wrong among accepted | 2/45 = 4.44% | **5/67 = 7.46%** | 7/52 = 13.46% | 6/29 = 20.69% |
| Repair rate, including intended negatives | 59.82% | 40.18% | 53.57% | 74.11% |
| Harness latency p50 / p95, ms | 12364 / 30139 | 12486 / 39815 | 170 / 227 | 1110 / 3416 |

False acceptance denominator is all accepted cases; corpus-wide wrong acceptance is
5/112 for structured OpenAI. All five wrong accepted cases were valid-looking plates,
principally omitted/misheard letters. Two versus three letters are both valid project
formats; rejecting all two-letter plates or inserting the expected missing letter would
violate the schema or guess the answer. Structured OpenAI, balanced OpenAI and Vosk
rejected all twelve negatives; faster-whisper wrongly accepted two negative regions.
The text
parser alone obtained 99/100 positives, zero false accepts; one grouped Kazakh phone
remained ambiguous (95% phone, 100% other kinds).

**Precision gate is unmet.** Coverage improved for all six kinds, but accepted precision
fell relative to the ablation, and mixed-language coverage is low. Schema validity cannot
prove a single ASR transcript matches the waveform. This branch is not approval for
production sensitive-identifier automation or live PSTN. A subsequent evidence-based
confirmation/confidence strategy and independently recorded/human-checked audio are
needed before that release gate. The implementation does not claim zero false acceptance.

Ordinary medium-delay STT (six RU/KK ordinary replies) measured post-commit p50/p95
2733/3448 ms, versus structured first-pass 4043/20448 ms. Structured total includes the
conditional second call. Harness total starts before connection/upload; audio is already
segmented and sent faster than real time. It is **not** customer end-to-end conversational
latency. Local inference timings exclude audio generation and model initialization; cloud
times include network/server work and cannot be compared as interchangeable CPU timings.

A separate paired pace pilot used 24 new files: six kinds × RU/KK × requested fast/slow,
same voice/text per pair. Seven of twelve slow files were longer; model instructions do
not provide controlled speaking rates. Main-corpus fast/slow tags were nominal moderate
delivery; do not report them as a controlled rate sweep. Pilot canonical accuracy was
19/24 OpenAI (first 16/24, second recovery 3/8, accepted 19/19), 16/24 Vosk (one wrong
accepted), 9/24 faster-whisper (zero wrong accepted). Small-pilot precision does not erase
the five errors in the main corpus. Pilot total p50/p95: OpenAI 17665/33866 ms, Vosk
146/203 ms, faster-whisper 1141/2517 ms.

## Local model/resource/compatibility findings

Local packages are confined to ignored `work/tts-eval-env` and an evaluation-only image;
production requirements and Dockerfile are unchanged. Windows Python 3.13.12 ran Vosk
0.3.45 and faster-whisper 1.2.1 / CTranslate2 4.8.2, CPU int8, four Whisper threads.
Vosk uses RU small 0.22, KK small 0.42 and public-number/letter grammar. Mixed uses RU;
KK uses the KK model. Unsupported grammar words are filtered by model vocabulary.
Whisper uses public initial_prompt/hotwords, RU forced for RU and autodetection for KK/mixed.

Main-corpus Vosk: 17.41 process CPU seconds total, sampled peak RSS 418.55 MiB,
both unpacked models 198,276,652 bytes; initialization 1.32 seconds on the resumed run.
Whisper: 595.47 CPU seconds, sampled peak RSS 193.97 MiB, model 147,886,535 bytes;
initialization 0.50 seconds. RSS is sampled after each case, not a profiler-certified peak;
warm caches affect startup. Neither wins the overall accuracy/precision gate. Vosk's region
score is useful research evidence, insufficient to replace the shared primary STT.

Linux Python 3.13 Docker performed actual inference on two RU/KK phone fixtures with
both engines. Vosk: 1/2 correct, 0.36 CPU seconds, RSS 446.20 MiB, p50/p95 173/196 ms.
Whisper: 0/2 correct, 10.46 CPU seconds, RSS 233.87 MiB, p50/p95 1000/1445 ms. This
proves tested runtime/model compatibility, not a full Linux accuracy benchmark.

Model provenance in ignored `work/structured-speech/models/provenance.json`:

- RU archive 46,236,750 bytes, SHA256
  `961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4`.
- KK archive 59,697,294 bytes, SHA256
  `b6d6bfe6195c866805bd18b1f56723e4d2ba4866e81df1481006d0c5704fda4f`.
- Systran/faster-whisper-base revision
  `ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66`.

Official model sources/licenses: [Vosk model catalog (Apache 2.0 models)](https://alphacephei.com/vosk/models),
[faster-whisper implementation (MIT)](https://github.com/SYSTRAN/faster-whisper),
[base model card (MIT)](https://huggingface.co/Systran/faster-whisper-base).

## Browser, phone and privacy evidence

Real in-app browser playback/AudioContext decoded prerecorded synthetic MP3, paced
PCM24 frames over the actual voice WebSocket, admitted its receipt through the real
MessageService and compared private slot values server-side. The harness uses an
explicit fixture scenario router, real parser/business lookups and isolated SQLite.
It tests speech/core integration; it does not measure live LLM scenario-routing accuracy
or ambient microphone quality. No new production/mock fallback was added.

| Browser fixture | Canonical correct | Progressed to | Successful total ms |
|---|---|---|---:|
| region_code-02 | yes, 02 → almaty | drivers_iin | 36229 |
| phone-04 | yes | iin (valid phone absent from demo DB) | 8441 |
| iin-01 | yes | phone (valid IIN absent from demo DB) | 47679 |
| policy_number-01 | yes | phone | 11155 |
| vehicle_plate-01 | yes | region | 10279 |

Region raw text stayed `Region ноль два.`; the second pass resolved 02 and the business
region became almaty. An initial region network attempt and the first IIN connection
attempt failed; explicit benchmark reruns succeeded. No recognition retry was hidden in
production. Five successful rows, screenshot and safe results are under ignored
`work/structured-speech/browser-results.jsonl` / `browser-validation.jpg`.

Offline Twilio/Vonage regressions run provider codec → PCM24 → fixture STT → shared
parser → current core. Full existing phone smokes verify acknowledgements, cancellation,
terminal behavior, Risk, SQLite and restart. Live PSTN is still pending credentials.

Private values are retained only in local business state/short-lived receipts. Raw
runtime identifier audio never enters SQLite, analytics, logs, trace or dashboard.
Accepted private voice uses a routing marker; safe recognition metadata has no value or
candidate strings. Public history and trace redact digits/groups/spoken letters and spaced
plates/policy/claim formats, including older turns after the expected slot changes.
Provider failures log exception class only. SQLite tests search for synthetic IDs and
raw transcripts; replay/cross-session/mismatched-text tests fail safely. Evaluation files
contain authorized synthetic speech only and remain ignored. Existing analytics schema
and allowlist are unchanged; no migrations or Supabase additions.

## TTS and verification

Five voices have 20 new RU/KK samples each, including ordinary, financial, Risk and
handoff replies. Optional RU/KK voice overrides fall back to the existing cedar choice;
mixed/unknown language uses the legacy voice. Application instructions now request warm,
calm manager delivery and natural number pacing. Display facts are unchanged. The user
reported **«cedar звучит лучше всего»** on 2026-10-03; this records overall preference,
not feminine approval, separate language scores or MOS. Listening sheets preserve human
notes on resume. Silero/Piper historical findings remain intact.

The isolated streaming MP3 prototype reduced one RU browser start from 3401 to 2408 ms;
KK streamed start was 2744 ms. Browser cancellation stopped playback and cancelled the
upstream request. Production synthesis still buffers complete MP3, preserving its existing
fallback/terminal handling and phone codec conversion. Full candidate timing evidence,
limitations and reproduction are in `TTS_QUALITY_VALIDATION.md`.

Final backend: **1133 passed** (45.11 seconds); frontend: **97 passed**. TypeScript,
Vite build, backend/script Ruff and format checks, git diff --check and all four Stage 6
smokes passed. Both Docker images built and started on isolated loopback ports 8013/5174,
with an isolated SQLite path and no .env credentials: backend/frontend /health returned
200, analytics was healthy, and both telephony providers were disabled. The real frontend
/api/analytics/overview proxy also returned 200. This was startup/API evidence, not live
model or PSTN validation. The starting 1045 backend / 96 frontend tests remain;
new tests cover parser ambiguity,
all region codes, slot aliases, second-pass bounds/deadlines, safe receipts/repair,
privacy, WS/phone contracts and language-specific TTS selection.

Focused secret scan of changed/new files and the built frontend found zero configured
secret matches. Generated audio/models/SQLite/browser evidence remain ignored; no .env
or production dependencies were added. Temporary servers/containers were scoped to this
validation; normal Compose data volume was never reset. Main stays at 48da4bb.

Full pytest runs from the backend directory initially failed collection because Stage 6
imports root scripts; the documented root run passed. A later redaction check caught
overmasking of safe source provenance; it was corrected without loosening identifier
redaction. A brittle privacy assertion that matched digits inside a timing float was
replaced by exact metadata-key assertions. The final full run passed all 1133 tests.

## Windows reproduction

Run backend tests from the repository root (Stage 6 tests import `scripts`). Formatting
uses the backend directory/config. Audio API commands use the existing server key and
incur configured provider usage; ordinary evaluation never reads private customer files.

```powershell
.venv\Scripts\python.exe -X utf8 scripts/build_structured_speech_dataset.py
.venv\Scripts\python.exe -X utf8 scripts/evaluate_structured_speech.py --provider text
.venv\Scripts\python.exe -X utf8 scripts/evaluate_structured_speech.py --generate-audio
.venv\Scripts\python.exe -X utf8 scripts/evaluate_structured_speech.py --provider openai --resume --concurrency 1
.venv\Scripts\python.exe -X utf8 scripts/evaluate_structured_speech.py --provider openai --baseline --resume --concurrency 1
.venv\Scripts\python.exe -X utf8 scripts/evaluate_structured_speech.py --provider openai --ordinary --resume --concurrency 1
.venv\Scripts\python.exe -X utf8 scripts/evaluate_structured_speech.py --generate-audio --paced
.venv\Scripts\python.exe -X utf8 scripts/evaluate_structured_speech.py --provider openai --paced --resume
work\tts-eval-env\Scripts\python.exe -X utf8 scripts/evaluate_structured_speech.py --provider vosk --constrained --model-path work/structured-speech/models/vosk-model-small-ru-0.22 --model-path-kk work/structured-speech/models/vosk-model-small-kz-0.42
work\tts-eval-env\Scripts\python.exe -X utf8 scripts/evaluate_structured_speech.py --provider faster-whisper --model-path work/structured-speech/models/faster-whisper-base
.venv\Scripts\python.exe -X utf8 -m pytest backend/tests -q --basetemp=work/structured-tests
.venv\Scripts\python.exe -X utf8 scripts/smoke_phone_runtime.py
.venv\Scripts\python.exe -X utf8 scripts/smoke_twilio_runtime.py
.venv\Scripts\python.exe -X utf8 scripts/smoke_vonage_runtime.py
.venv\Scripts\python.exe -X utf8 scripts/smoke_stage6_integration.py
docker compose build
```

Browser harness: from the root, start uvicorn for `scripts.validate_structured_browser:app`
on 127.0.0.1:8012 using the existing venv, then select the five synthetic fixture buttons.
It requires generated files, current STT access and local voice dependencies. The local
models must be separately downloaded/verified; no production image installs them.

Skills actually used: agent-debugging, agent-evals, security-review. Branch stays
`codex/stage6-telephony-integration`; main, credentials and PSTN activation remain unchanged.
