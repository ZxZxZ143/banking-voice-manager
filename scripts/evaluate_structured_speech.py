"""Separate deterministic text evaluation from synthetic audio ASR benchmarks."""

import argparse
import asyncio
import json
import platform
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from time import perf_counter, process_time

from websockets.exceptions import WebSocketException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def percentile(values, percent):
    if not values:
        return None
    return sorted(values)[min(len(values) - 1, round((len(values) - 1) * percent))]


def summary(rows):
    positive = [r for r in rows if r["expected"] is not None]
    accepted = [r for r in rows if r["accepted"]]
    second = [r for r in positive if r.get("second_pass_used")]
    available = [r for r in rows if not r.get("provider_failed")]
    structured_available = [r for r in available if r["kind"] != "none"]
    positive_available = [r for r in positive if not r.get("provider_failed")]
    pending = [r for r in rows if r.get("outcome") == "confirmation_required"]
    consensus = [r for r in pending if r.get("consensus")]
    sensitive_accepted = [r for r in accepted if r["kind"] not in {"region_code", "none"}]
    timings = [r["latency_ms"] for r in available]
    return dict(
        cases=len(rows),
        outcome_counts=dict(Counter(r.get("outcome", "legacy") for r in available)),
        accepted_count=len(accepted),
        sensitive_accepted_count=len(sensitive_accepted),
        sensitive_accepted_precision=(
            sum(r["correct"] for r in sensitive_accepted) / len(sensitive_accepted)
            if sensitive_accepted
            else None
        ),
        wrong_accepted_count=sum(not r["correct"] for r in accepted),
        confirmation_candidate_accuracy=(
            sum(r.get("candidate_correct", False) for r in pending) / len(pending)
            if pending
            else None
        ),
        consensus_candidate_accuracy=(
            sum(r.get("candidate_correct", False) for r in consensus) / len(consensus)
            if consensus
            else None
        ),
        consensus_count=len(consensus),
        bounded_wait_p50_ms=percentile(
            [
                r["second_pass_wait_ms"]
                for r in available
                if r.get("second_pass_wait_ms") is not None
            ],
            0.5,
        ),
        bounded_wait_p95_ms=percentile(
            [
                r["second_pass_wait_ms"]
                for r in available
                if r.get("second_pass_wait_ms") is not None
            ],
            0.95,
        ),
        counts=dict(Counter(r["kind"] for r in positive)),
        canonical_accuracy=sum(r["correct"] for r in positive) / len(positive)
        if positive
        else None,
        canonical_accuracy_when_available=sum(r["correct"] for r in positive_available)
        / len(positive_available)
        if positive_available
        else None,
        raw_transcript_exactness=sum(r.get("raw_exact", False) for r in rows) / len(rows),
        first_pass_accuracy=sum(r.get("first_correct", False) for r in positive) / len(positive)
        if positive
        else None,
        second_pass_recovery_rate=sum(r["correct"] for r in second) / len(second)
        if second
        else None,
        final_accepted_accuracy=sum(r["correct"] for r in accepted) / len(accepted)
        if accepted
        else None,
        false_acceptance_rate=sum(not r["correct"] for r in accepted) / len(accepted)
        if accepted
        else None,
        confirmation_rate=len(pending) / len(structured_available)
        if structured_available
        else None,
        repair_rate=sum(
            r.get("outcome") == "repair_required" if "outcome" in r else not r["accepted"]
            for r in structured_available
        )
        / len(structured_available)
        if structured_available
        else None,
        nonacceptance_rate=sum(not r["accepted"] for r in structured_available)
        / len(structured_available)
        if structured_available
        else None,
        provider_outage_rate=1 - len(available) / len(rows) if rows else None,
        latency_p50_ms=percentile(timings, 0.5),
        latency_p95_ms=percentile(timings, 0.95),
        first_pass_p50_ms=percentile(
            [r["first_pass_ms"] for r in rows if "first_pass_ms" in r], 0.5
        ),
        first_pass_p95_ms=percentile(
            [r["first_pass_ms"] for r in rows if "first_pass_ms" in r], 0.95
        ),
        provider_failures=sum(r.get("provider_failed", False) for r in rows),
        cpu_seconds=sum(r.get("cpu_seconds", 0) for r in rows),
        peak_rss_mib=max((r.get("rss_mib") or 0 for r in rows), default=0),
        by_kind={
            k: sum(r["correct"] for r in positive if r["kind"] == k)
            / sum(r["kind"] == k for r in positive)
            for k in {r["kind"] for r in positive}
        },
        by_language={
            k: sum(r["correct"] for r in positive if r["language"] == k)
            / sum(r["language"] == k for r in positive)
            for k in {r["language"] for r in positive}
        },
    )


async def run(args):
    from app.core.config import Settings
    from app.speech.conversion import speech_to_pcm
    from app.speech.structured.context import TranscriptionContext, context_for_slot
    from app.speech.structured.normalization import normalize_spoken
    from app.speech.tts.openai_provider import OpenAITTSProvider

    dataset = ROOT / "data/speech/structured_utterances.json"
    fixtures = json.loads(dataset.read_text(encoding="utf-8"))
    if args.paced:
        paired = []
        for kind in dict.fromkeys(r["kind"] for r in fixtures if r["expected"] is not None):
            for language in ("ru", "kk"):
                source = next(
                    r
                    for r in fixtures
                    if r["kind"] == kind
                    and r["language"] == language
                    and r["style"] != "asr_artifact"
                    and r["expected"] is not None
                )
                for pace in ("fast", "slow"):
                    paired.append(dict(source, id=source["id"] + "-" + pace, style=pace))
        fixtures = paired
    if args.limit:
        fixtures = fixtures[: args.limit]
    if args.ordinary:
        ordinary = json.loads((ROOT / "data/tts/eval_samples.json").read_text("utf-8"))
        wanted = {
            "ru_greeting",
            "ru_deposit",
            "ru_risk",
            "kk_greeting",
            "kk_deposit",
            "kk_risk",
        }
        fixtures = [
            dict(
                id=r["id"],
                kind="none",
                language=r["language"],
                text=r["text"],
                expected=None,
                synthetic=True,
                style="ordinary",
                voice="coral",
            )
            for r in ordinary
            if r["id"] in wanted
        ]
    output = ROOT / "work/structured-speech"
    output.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    if args.generate_audio:
        if not key:
            raise RuntimeError("Synthetic audio generation requires the configured server key")
        for row in fixtures:
            target = output / (row["id"] + ".pcm")
            if target.exists():
                continue
            tts = OpenAITTSProvider(
                api_key=key,
                model=settings.backend_tts_model,
                voice=row["voice"],
                timeout_seconds=90,
                instructions_ru=settings.backend_tts_instructions_ru
                + (
                    " Read quickly with short pauses while preserving every digit and letter."
                    if args.paced and row["style"] == "fast"
                    else " Read slowly with clear pauses between digit groups and letters."
                    if args.paced
                    else ""
                ),
                instructions_kk=settings.backend_tts_instructions_kk
                + (
                    " Read quickly with short pauses while preserving every digit and letter."
                    if args.paced and row["style"] == "fast"
                    else " Read slowly with clear pauses between digit groups and letters."
                    if args.paced
                    else ""
                ),
            )
            result = await tts.synthesize(row["text"], "kk" if row["language"] == "kk" else "ru")
            (output / (row["id"] + ".mp3")).write_bytes(result.audio)
            target.write_bytes(speech_to_pcm(result, rate=24000, max_seconds=120))
            print(json.dumps({"generated": row["id"], "voice": row["voice"]}), flush=True)
        return
    model = None
    initialization_ms = None
    model_bytes = None
    if args.provider == "vosk":
        from vosk import Model, SetLogLevel

        SetLogLevel(-1)
        start = perf_counter()
        model = Model(str(Path(args.model_path).resolve()))
        model_kk = Model(str(Path(args.model_path_kk).resolve())) if args.model_path_kk else model
        initialization_ms = (perf_counter() - start) * 1000
    elif args.provider == "faster-whisper":
        from faster_whisper import WhisperModel

        start = perf_counter()
        model = WhisperModel(
            args.model_path,
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            local_files_only=True,
        )
        initialization_ms = (perf_counter() - start) * 1000
    if args.model_path and Path(args.model_path).exists():
        model_bytes = sum(p.stat().st_size for p in Path(args.model_path).rglob("*") if p.is_file())
        if args.provider == "vosk" and args.model_path_kk:
            model_bytes += sum(
                p.stat().st_size for p in Path(args.model_path_kk).rglob("*") if p.is_file()
            )
    report_path = output / (
        f"{args.provider}{'-constrained' if args.constrained else ''}"
        f"{'-baseline' if args.baseline else ''}.json"
    )
    if args.ordinary or args.report_tag or args.paced:
        suffix = "-ordinary" if args.ordinary else ""
        suffix += "-paced" if args.paced else ""
        suffix += "-" + args.report_tag if args.report_tag else ""
        report_path = report_path.with_stem(report_path.stem + suffix)
    rows = []
    if args.resume and report_path.exists():
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        for item in saved["rows"]:
            fixture = next((r for r in fixtures if r["id"] == item["id"]), None)
            if (
                fixture
                and all(item[k] == v for k, v in fixture.items())
                and not item.get("provider_failed")
            ):
                rows.append(item)
    completed = {r["id"] for r in rows}

    def save():
        report = dict(
            provider=args.provider,
            baseline=args.baseline,
            dataset_sha256=sha256(dataset.read_bytes()).hexdigest(),
            platform=platform.platform(),
            python=platform.python_version(),
            initialization_ms=initialization_ms,
            model_bytes=model_bytes,
            summary=summary(rows),
            rows=rows,
        )
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    async def evaluate_row(row):
        context = context_for_slot(
            "region" if row["kind"] == "region_code" else row["kind"], row["language"]
        )
        if args.baseline:
            context = TranscriptionContext()
        start = perf_counter()
        cpu = process_time()
        transcript = row["text"]
        recognition = None
        meta = {}
        if args.provider != "text":
            if args.ordinary:
                from app.speech.tts.base import SpeechResult

                source = (
                    ROOT
                    / "work/tts-eval/openai-gpt-4o-mini-tts-coral-windows"
                    / (row["id"] + ".mp3")
                )
                pcm = speech_to_pcm(
                    SpeechResult(
                        audio=source.read_bytes(),
                        content_type="audio/mpeg",
                        language=row["language"],
                    ),
                    rate=24000,
                    max_seconds=120,
                )
            else:
                pcm = (output / (row["id"] + ".pcm")).read_bytes()
            if args.provider == "openai":
                from types import SimpleNamespace

                from websockets.asyncio.client import connect

                from app.speech.structured.recognition import BoundedTranscriber
                from app.speech.stt.streaming import StreamInput, relay_stream
                from app.speech.stt.streaming_provider import configure_transcription

                queue = asyncio.Queue()
                for i in range(0, len(pcm), 4800):
                    queue.put_nowait(StreamInput("audio", pcm[i : i + 4800]))
                queue.put_nowait(StreamInput("finish"))
                final = {}

                def record(text, result):
                    nonlocal recognition
                    recognition = result
                    return "synthetic-evaluation"

                async def emit(event):
                    if event["type"] == "utterance.final":
                        final.update(event)

                class ManualEndpoint:
                    tracker = SimpleNamespace(has_speech=True, silence_ms=0)

                    def feed(self, frame):
                        return False, 0.9

                async with connect(
                    "wss://api.openai.com/v1/realtime?intent=transcription",
                    additional_headers={"Authorization": f"Bearer {key}"},
                    open_timeout=20,
                    close_timeout=3,
                    max_size=2_000_000,
                ) as upstream:
                    await configure_transcription(upstream, context, settings.streaming_stt_model)
                    await relay_stream(
                        queue.get,
                        emit,
                        upstream,
                        ManualEndpoint(),
                        context=context,
                        second_pass=None
                        if args.baseline
                        else BoundedTranscriber(key, settings.structured_stt_model),
                        record_recognition=record,
                    )
                transcript = final["text"]
                meta = (
                    recognition.metadata.model_dump()
                    if recognition
                    else dict(first_pass_ms=final["stt_after_commit_ms"])
                )
            elif args.provider == "vosk":
                import av
                from vosk import KaldiRecognizer

                frame = av.AudioFrame(format="s16", layout="mono", samples=len(pcm) // 2)
                frame.sample_rate = 24000
                frame.planes[0].update(pcm)
                converted = b"".join(
                    bytes(f.planes[0])[: f.samples * 2]
                    for f in av.AudioResampler(format="s16", layout="mono", rate=16000).resample(
                        frame
                    )
                )
                grammar = None
                # Vocabulary comes from public number/letter lexicons, never expected answers.
                if args.constrained:
                    from app.speech.structured.normalization import (
                        FILLERS,
                        HUNDREDS,
                        LETTERS,
                        NUMBERS,
                        PREFIX_ALIASES,
                        TENS,
                    )

                    grammar = sorted(
                        set(NUMBERS)
                        | set(TENS)
                        | set(HUNDREDS)
                        | set(LETTERS)
                        | set(PREFIX_ALIASES)
                        | FILLERS
                        | {"[unk]", "жүз", "мың"}
                    )
                active_model = model_kk if row["language"] == "kk" else model
                if grammar:
                    grammar = [
                        word
                        for word in grammar
                        if word == "[unk]" or active_model.vosk_model_find_word(word) >= 0
                    ]
                recognizer = (
                    KaldiRecognizer(active_model, 16000, json.dumps(grammar, ensure_ascii=False))
                    if grammar
                    else KaldiRecognizer(active_model, 16000)
                )
                recognizer.AcceptWaveform(converted)
                transcript = json.loads(recognizer.FinalResult())["text"]
            else:
                import av
                import numpy as np

                frame = av.AudioFrame(format="s16", layout="mono", samples=len(pcm) // 2)
                frame.sample_rate = 24000
                frame.planes[0].update(pcm)
                frames = av.AudioResampler(format="flt", layout="mono", rate=16000).resample(frame)
                audio = np.concatenate([f.to_ndarray().flatten() for f in frames])
                segments, _ = model.transcribe(
                    audio,
                    language="ru" if row["language"] == "ru" else None,
                    initial_prompt=context.prompt,
                    hotwords=" ".join(context.keywords),
                    beam_size=5,
                    condition_on_previous_text=False,
                )
                transcript = " ".join(s.text.strip() for s in segments)
        parsed = normalize_spoken(transcript, row["kind"])
        value = recognition.value if recognition and not args.baseline else parsed.value
        accepted = (
            recognition.metadata.accepted if recognition and not args.baseline else parsed.accepted
        )
        candidate = (
            recognition.candidate.canonical_candidate
            if recognition and recognition.candidate
            else None
        )
        item = {
            **row,
            "transcript": transcript,
            "value": value,
            "accepted": accepted,
            "candidate": candidate,
            "candidate_correct": candidate is not None and candidate == row["expected"],
            "correct": value == row["expected"],
            "first_correct": parsed.value == row["expected"],
            "raw_exact": transcript.strip() == row["text"].strip(),
            "latency_ms": (perf_counter() - start) * 1000,
            "cpu_seconds": process_time() - cpu,
            **meta,
        }
        try:
            import psutil

            item["rss_mib"] = psutil.Process().memory_info().rss / 1024**2
        except ImportError:
            item["rss_mib"] = None
        rows.append(item)
        save()
        print(
            json.dumps({"id": row["id"], "correct": item["correct"], "accepted": accepted}),
            flush=True,
        )

    semaphore = asyncio.Semaphore(args.concurrency if args.provider == "openai" else 1)

    async def bounded_case(row):
        async with semaphore:
            case_started = perf_counter()
            try:
                async with asyncio.timeout(70):
                    await evaluate_row(row)
            except (
                TimeoutError,
                OSError,
                ValueError,
                KeyError,
                RuntimeError,
                WebSocketException,
            ) as error:
                # Evaluation records outages; production transcription never gains retries.
                rows.append(
                    {
                        **row,
                        "accepted": False,
                        "correct": False,
                        "raw_exact": False,
                        "first_correct": False,
                        "provider_failed": True,
                        "latency_ms": 0,
                        "failure_latency_ms": (perf_counter() - case_started) * 1000,
                        "failure_kind": type(error).__name__,
                    }
                )
                save()
                print(json.dumps({"id": row["id"], "provider_failed": True}), flush=True)

    await asyncio.gather(*(bounded_case(row) for row in fixtures if row["id"] not in completed))
    print(json.dumps(summary(rows)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=["text", "openai", "vosk", "faster-whisper"],
        default="text",
    )
    parser.add_argument("--generate-audio", action="store_true")
    parser.add_argument("--model-path")
    parser.add_argument("--model-path-kk")
    parser.add_argument("--constrained", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Balanced generic STT without second pass",
    )
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=3)
    parser.add_argument(
        "--paced",
        action="store_true",
        help="24 RU/KK paired fast/slow audio pilot cases",
    )
    parser.add_argument(
        "--ordinary",
        action="store_true",
        help="Six ordinary RU/KK TTS samples, medium delay",
    )
    parser.add_argument("--report-tag", choices=["linux", "paced", "precision"])
    asyncio.run(run(parser.parse_args()))
