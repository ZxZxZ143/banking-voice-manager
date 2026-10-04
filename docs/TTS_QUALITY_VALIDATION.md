# Product language and TTS quality validation

Current 2026-10-04 decision: retain the configured `gpt-4o-mini-tts` alias and the user's
preferred **cedar**, including `BACKEND_TTS_VOICE_RU`, `BACKEND_TTS_VOICE_KK` and default
override names. No dated snapshot or silent voice migration was introduced.
[Official deprecations](https://developers.openai.com/api/docs/deprecations) now list
the dated mini-TTS snapshots for removal on **2027-01-06**, recommending
`gpt-realtime-2.1-mini`; the [model page](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)
also marks the family deprecated. The alias is not a promise of continued availability.
A separate migration must verify Cedar RU/KK quality, cancellation, phone conversion
and the read-back/echo contract before replacing this implementation.

Fresh real-Chrome prototype measurements: RU buffered first-audio 3732/1919/1758 ms;
RU streaming 1966/1476/1693 ms; KK streaming 1782 ms (one sample). Streaming cancellation
stopped playback. These small samples do not establish a network SLA. Production stays
buffered for this release: the new near-end echo gate needs a decoded playback reference,
and incremental reference alignment/cancellation would require a separate acoustic gate.
Full details: [voice latency and correction validation](VOICE_LATENCY_AND_CORRECTION_VALIDATION.md).
The historical quality/listening results below remain unchanged.

Date: 2026-10-03. Branch: `codex/stage6-telephony-integration`; starting commit
`7bb0f35`. This hotfix preserves Stage 6. No main merge, public tunnel, outbound call,
live PSTN test, new credentials or O11 campaign-routing tuning is included.
Implementation commits: `fc96fd2` (Product language + regressions), `d66c2d1` (speech +
regressions/evaluation). This report and the affected architecture/runbook pages are
committed separately on the same integration branch.

## Decision and quality gate

`TTS_PROVIDER=auto` currently selects configured OpenAI, otherwise web uses browser
SpeechSynthesis. Default backend model/voice: `gpt-4o-mini-tts` / `cedar`, both configurable.
Silero and Piper were actually run on CPU on Windows and Linux Docker, for both RU and KK.
Their latency/deployment checks passed, but **human RU/KK intelligibility, naturalness,
pronunciation and cadence have not been assessed**. They therefore have not passed the
complete free-provider acceptance gate and remain isolated evaluation dependencies.
This is not evidence that their speech is poor. Silero is a promising fast candidate.

OpenAI is the provisional primary under the requested fallback rule, not a claim of
verified human-like quality. Both `marin` and `cedar` generated the same 20 synthetic samples;
cedar had a smaller observed latency tail in these sequential runs. This was not a
controlled voice-quality comparison. Human listening may change the voice/provider choice.
Do not assign subjective scores from the automatic checks below.

## Language defect and ownership

Before the fix, actual Docker browser session `e80390f3-daaf-4f0f-98e3-473e25e0244c`
started a Russian deposit offer. `меня интересует накопительный депозит` produced a
Kazakh liquidity question; the structured model label was `kk` (router 2.54 s). The next
`ответь на русском` returned Russian in this particular run, but was misclassified as
`general_discovery` (3.75 s), not a control action. We do not claim it stayed Kazakh on
that second turn. A deliberately wrong-label regression initially failed **54/60** cases.

The former `reply_language` accepted the model label except for a few marker corrections.
There was no typed persistent preference. The fix leaves that helper for other packs and
adds a Product-specific policy in `conversation/language.py`:

| Owner | Responsibility |
| --- | --- |
| Product model | Utterance language evidence and business intent; no final language authority |
| Product context/policy | `response_language` continuity and nullable typed `preferred_response_language` |
| Narrow language-control parser | Complete explicit RU/KK clauses; unmatched business text still goes to the existing model |
| Product deterministic renderers | Use the authorized language for pitch, details, questions, refusal, scope and terminal replies |
| Shared Risk guidance | Honors an existing Product preference without changing sales state or Risk classification |
| Browser/phone runtime | Uses the final response language for TTS; current Risk routing takes priority over retained business metadata |

Explicit preference persists until another explicit command. Strong bounded RU/KK
function-word, morphology and Kazakh-letter evidence can change language only without
that preference. Dominant mixed evidence wins; short neutral/numeric answers retain
continuity. The initial model hint applies only before an application reply establishes
language. No intent regex, evaluation-sentence special case or prompt change was added.

A pure language command emits typed `ProductLanguageControl`, bypasses Product Agent,
and re-renders the same pending question. Preferences, campaign, sales phase, refusal and
customer-turn counters are unchanged. The global exchange/analytics turn still advances.
The HTTP `ProductMessageResponse.routing` union explicitly accepts this control type.
Browser testing caught a missing union member (HTTP 500) after core tests had passed;
it was fixed and a three-campaign HTTP serialization regression added.

Dataset: `data/product_promoter/language_regressions.json`; tests also cover preferences,
switch-back, all three campaigns, Risk detours, business clauses, and avoiding interception
of negative/quoted text. The generic LLM routing/prompt datasets were not rerun: no prompt
or Agent SDK decision schema changed. Focused real model/browser turns exercise the fix.

## Free candidate provenance and licenses

Inspected official sources and actual voice model cards, not engine licensing alone:

- [Silero official models](https://github.com/snakers4/silero-models), inspected revision
  `d9355348e2781dc8fa25a135d1602c530afae24c`, and its
  [CIS license](https://github.com/snakers4/silero-models/blob/d9355348e2781dc8fa25a135d1602c530afae24c/LICENSE_CIS).
  Modern standalone Russian `v5_5_ru` and CIS extended candidates carry noncommercial
  restrictions in the catalog and were not selected. The actual prototype is MIT CIS base
  `v5_cis_base_nostress`, separate `ru_zhadyra` and `kaz_zhadyra` speakers. MIT permits
  commercial/demo use with notices. The no-stress model expects stress support for Slavic
  languages; no automatic Russian stress annotation was added, so pronunciation needs listening.
- [Maintained Piper engine](https://github.com/OHF-Voice/piper1-gpl), `piper-tts==1.8.0`,
  GPL-3.0-or-later. Engine redistribution requires its license obligations; it is not a
  permissive drop-in production dependency. The older rhasspy engine is not the selected runtime.
- [Denis model card](https://huggingface.co/rhasspy/piper-voices/blob/c10ece1aade47bb51c153c893d14e5bf8e5b7117/ru/ru_RU/denis/medium/MODEL_CARD):
  Russian `ru_RU-denis-medium`, CC0. Irina's unknown model license and Ruslan's
  noncommercial terms were reasons not to select those alternatives.
- [ISSAI model card](https://huggingface.co/rhasspy/piper-voices/blob/c10ece1aade47bb51c153c893d14e5bf8e5b7117/kk/kk_KZ/issai/high/MODEL_CARD):
  Kazakh `kk_KZ-issai-high`, speaker `0`, CC BY 4.0; attribution to ISSAI is required.
  Both selected voice licenses permit commercial/demo use subject to their terms.
- [OpenAI Speech guide](https://developers.openai.com/api/docs/guides/text-to-speech):
  the installed SDK supports `gpt-4o-mini-tts`, `marin`, `cedar`, streamed MP3 and optional
  delivery instructions. Actual account requests succeeded; no voice cloning is used.

Predownloaded cache: ignored `work/tts-eval/models/`. The script requires an explicit
matching SHA-256 before loading a local model and never downloads hub code during a request.
Silero's Torch package is executable trusted model content: only use the pinned official
artifact. These are provenance pins, not a mechanism for trusting arbitrary user uploads.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `v5_cis_base_nostress.pt` | 91,685,438 | `0405777e332906f0644e08a680f7cfdc2137ea864090079c1fdd30a43c1b8761` |
| `ru_RU-denis-medium.onnx` | 63,201,294 | `15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a` |
| `ru_RU-denis-medium.onnx.json` | 4,823 | `831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8` |
| `kk_KZ-issai-high.onnx` | 127,864,258 | `4dee767c893e8535da821447d12cb030e3569e11254c14030a1da5d8b2222c16` |
| `kk_KZ-issai-high.onnx.json` | 4,358 | `eb145ac8712b87beda9f0266e95b98cad76acce89d4626cd8b1408234e9842f0` |

Silero download: `https://models.silero.ai/models/tts/ru/v5_cis_base_nostress.pt`.
Piper files use the model-card repository revision above via `/resolve/<revision>/...`.
One interrupted Denis download was rejected by ONNX and then repaired/verified against
the upstream LFS SHA before measurements. No model weights, generated audio or evaluation
environments are committed or copied into the normal image.

## Measured CPU and network results

Host: Windows, Python 3.13, AMD Ryzen 5 6600H, 6 cores / 12 threads. Docker Linux engine:
12 visible CPUs, 7,899,127,808 bytes memory. Optional evaluation environment:
Torch `2.14.1+cpu` (4 threads for Silero), Piper `1.8.0`, psutil `7.2.2`, NumPy `2.4.3`,
PyAV `16.1.0`. No GPU. Each local row generated 10 samples, 3.7–9.8 seconds of speech.
Warm means the remaining nine samples after the first synthesis; initialization is separate.
Measurements include ordinary host load and are not an isolated performance benchmark.

| Provider / locale / OS | Initialization ms | First synthesis ms | Warm full audio ms | First chunk ms, all samples | Max observed RSS MiB |
| --- | ---: | ---: | --- | --- | ---: |
| Silero RU / Windows | 2,100 | 914 | 82–179 | Not streaming | 513.5 |
| Silero KK / Windows | 2,710 | 1,312 | 94–169 | Not streaming | 513.3 |
| Silero RU / Linux | 2,857 | 949 | 64–209 | Not streaming | 519.8 |
| Silero KK / Linux | 4,821 | 1,777 | 113–357 | Not streaming | 511.8 |
| Piper RU / Windows | 3,008 | 449 | 243–528 | 120–374 | 319.9 |
| Piper KK / Windows | 2,505 | 1,310 | 961–1,738 | 336–1,425 | 371.6 |
| Piper RU / Linux | 1,970 | 261 | 247–553 | 92–271 | 289.3 |
| Piper KK / Linux | 2,756 | 1,584 | 1,108–2,215 | 281–1,443 | 383.3 |

Silero: mono WAV 24 kHz. Piper: mono WAV 22.05 kHz, `length_scale=1.05`, `volume=0.9`.
The initial Piper volume 1 trial reached 0.99997 at a few samples per utterance; the final
volume 0.9 rerun peaked at 0.89996 with no near-full-scale samples. This does not prove
absence of every audible artifact. Silero samples had no detected clipping.

| OpenAI / Windows, 20 samples each (10 RU + 10 KK) | Upstream first chunk | Complete MP3 | Duration | Total output bytes |
| --- | --- | --- | --- | ---: |
| `gpt-4o-mini-tts` / `marin` | 0.998–13.658 s | 1.668–14.201 s | 4.464–11.904 s | 2,533,248 |
| `gpt-4o-mini-tts` / `cedar` | 0.879–5.400 s | 1.550–6.151 s | 4.704–13.104 s | 2,501,376 |

All 40 MP3s decode at 24 kHz, with finite samples, positive duration and zero measured
near-full-scale samples. Both real phone conversions succeeded for every MP3 (40 Twilio
mu-law 8 kHz + 40 Vonage PCM16LE 16 kHz conversions), preserving duration within 20 ms.
OpenAI client RSS was not measured by the evaluation environment. Network tail latency is
real and retained in the report. An upstream chunk is **not browser first audible audio**:
the production adapter currently buffers complete audio before returning it.

Evaluation image size (Docker inspect): base 223,912,303 bytes; optional local evaluation
image 498,734,617 bytes, **+274,822,314 bytes** excluding models. The normal application
does not acquire Torch/Piper TTS dependencies. Its final rebuilt image is 223,946,231 bytes,
33,928 bytes above baseline. No optional local TTS
profile is advertised as production-ready before listening approval.

## Runtime contract, cancellation and privacy

`BackendTtsService` calls same-origin `POST /api/speech/tts` with only `{text, language}`.
The endpoint accepts configured local origins, strict JSON, 20,000-byte body / 5-second
body deadline, 4,000 display characters and RU/KK/mixed. Prepared speech is separately
capped at 4,000 characters. No browser voice/model/provider/key override is accepted.
Response is bounded MP3/WAV only, at most 8 MB, `Cache-Control: no-store`, `nosniff`.
Unavailable provider is 503, invalid input 422 without echoed speech, invalid origin 403,
bounded provider failure 502. Shared OpenAI capacity is two active syntheses without a queue.

Application-owned RU/KK instructions are configurable and contain no customer data.
Legacy `tts-1` models omit unsupported instructions. Display text stays untouched;
the server's deterministic speech preparation expands numbers, precision-preserving
percentages, grouped currency, valid dates and phone digits without business calculations.
It does not use float rounding or SSML. Invalid dates stay literal. Date/identifier grammar
and Kazakh pronunciation still need human review; this is not a general linguistic engine.

The browser plays a temporary object URL, releases it after end/error, and cancels both
fetch and playback on stop/reset. Late replies are ignored. A 35-second request timeout
or pre-playback backend error invokes browser fallback; a partly played reply is never
repeated via fallback. The backend cancels synthesis on disconnect/timeout and releases
capacity. Phone uses the same provider factory/instance and existing codecs/acknowledgements;
there is no browser fallback for phone. Missing backend speech makes enabled gateways
unavailable. Terminal/cleanup semantics and shared STT remain unchanged.

Fallback voice ranking prefers Natural/Neural/Online metadata **within the correct locale**,
caches the chosen voice per language, and uses rate 0.97 / pitch 1 / volume 1. A missing KK
voice is disclosed and no Russian/English voice is explicitly forced onto KK. Actual old
browser baseline selected Microsoft Irina RU even for KK (806 ms onset, 5,089 ms total for
the short KK test); that machine had no matching KK voice exposed to the selector. Metadata
ranking and 0.97 rate are conservative choices, not listening-validated quality ratings.

Origin checking is browser access control, **not authentication**. The app remains bound
to loopback in Compose. A future public reverse proxy/tunnel must allow only signed provider
telephony paths, never `/api/speech/tts`, message, dashboard, analytics or generic app routes.
Runtime synthesis writes no audio to disk/SQLite and logs no submitted/generated text.
Only explicitly synthetic evaluation audio is saved under ignored `work/tts-eval/`.

## Five-voice refinement and streaming investigation (2026-10-03)

The existing OpenAI/backend MP3 architecture remains. Optional BACKEND_TTS_VOICE_RU
and BACKEND_TTS_VOICE_KK override BACKEND_TTS_VOICE for those languages; blank overrides,
mixed and unknown language retain the legacy choice. Server-only configuration and
browser fallback/phone codec behavior remain intact. RU/KK instructions request calm,
warm, feminine-presenting manager delivery, natural sentence rhythm/moderate pace,
clear numbers and brief pauses. This is an instruction intent, not a measured gender
property. Visible assistant facts and deterministic speech preparation are unchanged.

New gpt-4o-mini-tts comparisons used coral, nova, shimmer, marin and cedar: 20 samples
per voice, ten RU/ten KK, including ordinary replies, financial numbers, Risk and handoff.
All 100 files completed on Windows in ignored
`work/tts-eval/openai-gpt-4o-mini-tts-{voice}-windows/`. These are provider timings;
first chunk does not mean browser audible start. Runs were sequential and time-varying,
so the table is not a statistically controlled voice-performance ranking.

| Voice | First chunk p50/p95 ms | Full synthesis p50/p95 ms | Duration p50/p95 seconds |
|---|---:|---:|---:|
| coral | 2536 / 9142 | 4232 / 10464 | 8.52 / 12.17 |
| nova | 2151 / 3829 | 3716 / 7363 | 8.16 / 11.95 |
| shimmer | 1270 / 2523 | 2459 / 4141 | 8.30 / 12.17 |
| marin | 1068 / 1408 | 2045 / 2683 | 8.40 / 11.57 |
| cedar | 1303 / 2590 | 2392 / 3654 | 8.02 / 11.86 |

The user reported **«cedar звучит лучше всего»** on 2026-10-03 after the listening
question. Cedar remains the existing default; no real .env edit was needed. This records
an overall preference, not separate RU/KK ratings or feminine approval. All numeric
naturalness/clarity/feminine scores remain blank. The comparison index is ignored
`work/tts-eval/VOICE_LISTENING.md`; per-voice sheets now include a blank feminine
presentation column. Evaluator resume preserves human listening notes. OpenAI does not
officially gender-label these built-in voices; their names do not establish gender.
The previous Silero/Piper measurements, pins, audio and limitations remain above/below
as dated historical evidence. No large optional TTS packages were added to production.

`scripts/evaluate_tts_streaming.py` is a separate localhost-only synthetic prototype,
with fixed sample IDs, key on server, cancellation, 60-second/8-MB bound and no arbitrary
customer text ingress. An actual browser played progressive MP3 before synthesis completed.

| Browser run | First audible proxy ms | Provider first chunk ms | Full synthesis ms | Audio seconds |
|---|---:|---:|---:|---:|
| Buffered RU greeting | 3400.9 | 1985.3 | 2997.5 | 4.752 |
| Streamed RU greeting | 2408.4 | 1752.2 | 2173.1 | 5.088 |
| Streamed KK greeting | 2744.3 | 2155.5 | 2756.6 | 6.576 |

The audible proxy is HTMLAudio's first `playing` event, not a hardware/audio-loopback
measurement. These are single runs with variable provider output, not latency percentiles
or subjective listening scores. RU onset was about 993 ms earlier in this experiment.
Cancellation paused the element, removed its source and produced a safe upstream
cancelled flag. No repeated fallback speech occurred in the prototype. Existing production
fallback/cancellation/terminal and phone-conversion regressions passed independently.
Production `/api/speech/tts` still buffers full MP3; progressive playback was not promoted
because fallback/terminal/phone semantics would need further integration evidence.

Reproduce candidate generation with the existing evaluator (configured API usage):
`python scripts/evaluate_tts.py --provider openai --voice cedar --resume`, repeating for
the other four names. Start `python -m uvicorn scripts.evaluate_tts_streaming:app --host
127.0.0.1 --port 8011` from the root for the isolated browser experiment. Current model
guidance: [speech API](https://developers.openai.com/api/docs/guides/text-to-speech) and
[deprecations](https://developers.openai.com/api/docs/deprecations). Model stays configurable.
Structured STT/phone/privacy evidence: `STRUCTURED_SPEECH_RECOGNITION_VALIDATION.md`.

## Earlier reproduction and listening handoff

`data/tts/eval_samples.json` has 20 public synthetic RU/KK samples covering greetings,
deposit rate, cashback, loan amount, insurance/date, zero-only demonstration phone number,
currency, questions, handoff, Risk warnings and mixed banking text. Evaluation outputs
include `measurements.json` and a blank `LISTENING.md` per provider. The internal 1–5 sheet
covers naturalness, clarity, numbers, pauses, pronunciation and robotic artifacts; it is
not a scientific MOS benchmark. **All listening scores remain blank.**

```powershell
# Existing backend environment: configured OpenAI reference (paid API usage).
.venv\Scripts\python.exe scripts/evaluate_tts.py --provider openai --voice cedar
.venv\Scripts\python.exe scripts/evaluate_tts.py --provider openai --voice marin

# Optional isolated environment only; predownload and verify model/config files above.
work\tts-eval-env\Scripts\python.exe scripts/evaluate_tts.py --provider piper `
  --model-path work/tts-eval/models/ru_RU-denis-medium.onnx `
  --sha256 15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a `
  --voice 0 --language ru
```

For Silero use `--provider silero`, the pinned `.pt`/SHA, and `--voice ru_zhadyra --language ru`
or `--voice kaz_zhadyra --language kk`. Piper KK uses the pinned ISSAI file/SHA and voice 0.
The script now includes model identity in output directory names, avoiding RU/KK Piper
report collisions. Existing full OpenAI reports are in `work/tts-eval/openai-{voice}-windows/`;
future script runs add model identity to those names. Listen to at least three RU, three KK,
one Risk and one financial-rate sample before approving a provider's subjective quality.

## Final application validation

Actual rebuilt Docker application: `http://127.0.0.1:5173`. Final language session:
`cca2268e-4195-4cd8-8dde-36a26bf2f8ac` (7 turns), real HTTP/model calls and browser playback
events, text input with microphone disabled. These are runtime events, not seeded fixtures.

| Browser action | Measured result |
| --- | --- |
| Start deposit | Russian branded offer, backend RU audio |
| `меня интересует накопительный депозит` | Model again labeled KK, but visible liquidity question stayed RU; backend RU audio; router 6.21 s, browser audio onset 3.61 s |
| `ответь на русском` | HTTP 200, identical pending RU question; `language_control`, phase `needs`, router 0 ms; browser onset 9.68 s |
| `қазақша жауап беріңіз` | Same pending liquidity question in KK; backend KK audio; no campaign/state reset |
| `Какая минимальная сумма?` | Explicit KK preference persisted despite RU business text; KK amount/conditions reply and backend KK audio |
| `говорите по-русски` | Same now-pending opening question in RU; phase stayed `conditions` |
| KK SMS-code concern with explicit RU preference | RU advisory, active deposit retained; HIGH signal remains advisory; Risk Agent 1.88 s, safety audio onset 3.17 s, final audio onset 3.14 s |
| Overview → Conversation Demo | Same UUID/history retained; overview showed the new 7-turn runtime session and explicit synthetic/runtime source counts |
| Force `TTS_PROVIDER=browser` using an ignored Compose override | RU fallback Microsoft Irina, 800 ms onset / 5,262 ms total; KK browser default, matching voice unavailable explicitly shown, 801 ms / 5,894 ms |
| Restore `auto`, rebuild final frontend | Actual `gpt-4o-mini-tts` / `cedar`; backend RU test playback 2,906 ms onset / 6,423 ms total |
| Backend restart, Overview refresh | Dashboard loaded; 993 events / 195 sessions unchanged; SQLite healthy, both phone providers disabled |

The switch-back turn encountered one real HTTP 502 from backend TTS and successfully
fell back to Irina. Subsequent Risk and debug audio succeeded through the backend. This
transient upstream failure and the observed latency tail are not hidden by success claims.
Playback events/timings do not establish audible language quality in this tool environment.

Browser review also led to a small voice-cache correction: a missing-locale default is
not cached over a matching voice that becomes available later (covered by regression).
The actual backend UI, Risk panel, source labels and preserved-session navigation were
checked. This task did not repeat every historical Stage 5B dashboard release gate.
All three Product campaigns have deterministic and HTTP language tests; the manual
language dialogue above used the deposit campaign.

Ignored evidence: `work/tts-eval/browser-regression.txt`, `browser-regression.png`,
`backend-tts-browser.png`, provider audio/measurements and blank listening sheets.
Actual response/body language and unchanged sales fields are additionally asserted by
`tests/integration/test_product_language_api.py`; the trace's utterance language is allowed
to show the model's wrong label while the response/TTS language stays authoritative.

Persistence check before/after Compose recreation and explicit `docker compose restart backend`:
all event data plus fixed-clock anomaly response (`as_of=2026-10-03T15:00:00Z`) are identical,
SHA-256 `5d84cf32b7f3a8c94b8a9dff37f15f3a4d158be442e1e4bc3da6dd0083b084d4`.
In-memory conversation state still resets on backend restart as previously designed.
The original `.env` was never modified; normal Compose is restored with healthy loopback
frontend 5173 / backend 8000. No live phone call was attempted.

## Security review and checks

Focused review covered endpoint/input/Origin bounds, server-only key and instructions,
trusted pinned model cache, cancellation/concurrency, audio responses/temporary URLs,
logging/storage, built frontend, Docker bindings and signed telephony boundary. No
unresolved high-impact issue was found within the local/private deployment scope.
Actual local secret values had **zero matches** in tracked/new source or production bundle;
no `.env`, private keys, model weights or generated TTS audio were added to Git.
Unauthenticated public exposure and live PSTN remain outside the validated deployment.

| Final check | Result |
| --- | --- |
| Full backend pytest | **1045 passed**, 40.73 s; baseline 929 + 116 new |
| Full frontend | **96 passed**, 0 failed/skipped/cancelled, 1.335 s; baseline 80 + 16 new |
| TypeScript / Vite production build | Passed; 2036 modules; JS 420.39 kB, CSS 55.65 kB |
| Ruff backend + new evaluation script | Passed; 206 Python files formatted |
| Existing four phone smoke scripts, Ruff/format | Passed |
| Prettier dashboard + changed speech files | Passed with `--end-of-line auto` for Windows checkout |
| `git diff --check` | Passed |
| Four offline phone/core smoke scripts | Passed on Windows and Linux Docker; no live providers; runtime, Twilio, Vonage, current-core/Risk/SQLite/restart |
| Automatic audio checks | 120 final samples across providers/OS; valid nonempty decoded containers, duration > 0, finite PCM, no detected near-full-scale clipping |
| Real MP3 → phone adapters | All 40 OpenAI samples passed both codecs |
| Secrets / focused security review | Passed within local/private deployment scope; public authentication/live PSTN not claimed |

All pre-existing backend/frontend test files are unchanged. Initial Windows sandbox
temp-directory/child-process restrictions were resolved by running the same commands with
the required permissions; Vonage smoke needed UTF-8 console mode. Linux smoke requires
the same data-path environment variables as Compose. Those setup failures were not counted
as passing tests. A broader legacy `scripts/` lint/format scan still reports the pre-existing
Stage 3/transcription script issues documented in Stage 6 validation; they were not edited.
No expensive conversational evaluation dataset was rerun. O11 remains known backlog.
Skills actually used: agent-debugging, agent-evals, security-review, demo-readiness.
