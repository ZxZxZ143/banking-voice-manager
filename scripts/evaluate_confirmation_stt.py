"""Synthetic-only short confirmation benchmark. Customer audio is never saved here."""

# ruff: noqa: E402
import argparse
import asyncio
import base64
import json
import random
import struct
import sys
from pathlib import Path
from time import perf_counter
from unittest.mock import AsyncMock

from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import Settings
from app.speech.conversion import speech_to_pcm
from app.speech.structured.capture import StructuredCapture
from app.speech.structured.context import context_for_capture
from app.speech.structured.correction import parse_confirmation
from app.speech.structured.recognition import BoundedTranscriber, resolve_recognition
from app.speech.stt.streaming_provider import configure_transcription
from app.speech.tts.base import SpeechResult
from app.speech.tts.openai_provider import OpenAITTSProvider

OUTPUT = ROOT / "work/confirmation-stt"


def context_for_confirmation(language):
    # The prompt has no value even when a private capture is pending.
    return context_for_capture(
        "phone", language, StructuredCapture("phone", "phone", "SC25", "confirmation")
    )


def decision(kind):
    return kind if kind in {"confirm", "reject"} else "unresolved"


def metrics(rows):
    available = [r for r in rows if not r.get("provider_failed")]
    first_available = [r for r in rows if "first" in r]
    recovered = [r for r in first_available if r["recovery_used"]]
    delays = sorted(r["recovery_ms"] for r in recovered)
    return {
        "cases": len(rows),
        "provider_failures": len(rows) - len(available),
        "first_pass_accuracy": sum(r["first_correct"] for r in first_available)
        / len(first_available)
        if first_available
        else None,
        "recovery_cases": len(recovered),
        "recovery_pass_accuracy": sum(r["correct"] for r in recovered) / len(recovered)
        if recovered
        else None,
        "final_accuracy": sum(r.get("correct", False) for r in rows) / len(rows) if rows else None,
        "final_accuracy_when_available": sum(r["correct"] for r in available) / len(available)
        if available
        else None,
        "false_confirm": sum(
            r["final"] == "confirm" and r["expected"] != "confirm" for r in available
        ),
        "false_reject": sum(
            r["final"] == "reject" and r["expected"] != "reject" for r in available
        ),
        "unresolved_rate": sum(r.get("final", "unresolved") == "unresolved" for r in rows)
        / len(rows)
        if rows
        else None,
        "recovery_added_p50_ms": delays[len(delays) // 2] if delays else None,
        "recovery_added_max_ms": max(delays) if delays else None,
        "fast_path_recovery_calls": sum(
            r["recovery_used"] for r in available if r["first"] in {"confirm", "reject"}
        ),
    }


async def first_pass(pcm, context, settings):
    key = settings.openai_api_key.get_secret_value()
    async with asyncio.timeout(45):
        async with connect(
            "wss://api.openai.com/v1/realtime?intent=transcription",
            additional_headers={"Authorization": f"Bearer {key}"},
            open_timeout=20,
            close_timeout=3,
        ) as upstream:
            await configure_transcription(upstream, context, settings.streaming_stt_model)
            started = perf_counter()
            for offset in range(0, len(pcm), 4800):
                await upstream.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(pcm[offset : offset + 4800]).decode(),
                        }
                    )
                )
            await upstream.send(json.dumps({"type": "input_audio_buffer.commit"}))
            async for raw in upstream:
                event = json.loads(raw)
                if event.get("type", "").endswith("input_audio_transcription.completed"):
                    return event["transcript"], (perf_counter() - started) * 1000
                if event.get("type") == "error" or event.get("type", "").endswith(".failed"):
                    raise ValueError("Realtime provider failure")
    raise ValueError("Realtime provider disconnected")


async def run(args):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fixtures = json.loads((ROOT / "data/speech/confirmation_utterances.json").read_text("utf-8"))
    if args.case_ids:
        fixtures = [f for f in fixtures if f["id"] in args.case_ids.split(",")]
    settings = Settings()
    if args.live and not settings.openai_api_key:
        raise ValueError("Live benchmark requires server credentials")
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    rows = []
    for voice in args.voices.split(","):
        tts = OpenAITTSProvider(
            api_key=key,
            model=settings.backend_tts_model,
            voice=voice,
            max_retries=0,
            timeout_seconds=60,
            instructions_ru="Speak the Russian text exactly and clearly.",
            instructions_kk="Speak the Kazakh text exactly and clearly.",
        )
        for fixture in fixtures:
            row = {"id": fixture["id"], "voice": voice, "expected": fixture["expected"]}
            context = context_for_confirmation(fixture["language"])
            try:
                if args.live:
                    path = OUTPUT / f"{fixture['id']}-{voice}.mp3"
                    if not path.exists():
                        audio = await tts.synthesize(fixture["text"], fixture["language"])
                        path.write_bytes(audio.audio)
                    pcm = speech_to_pcm(
                        SpeechResult(
                            audio=path.read_bytes(),
                            content_type="audio/mpeg",
                            language=fixture["language"],
                        ),
                        rate=24000,
                        max_seconds=10,
                    )
                    if fixture.get("noise"):
                        rng = random.Random(41)
                        samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
                        pcm = struct.pack(
                            f"<{len(samples)}h",
                            *(max(-32768, min(32767, s + rng.randint(-180, 180))) for s in samples),
                        )
                    pcm += bytes(24000)
                    text, first_ms = await first_pass(pcm, context, settings)
                    bounded = BoundedTranscriber(key, settings.structured_stt_model)
                else:
                    # Explicit deterministic contamination fixtures, never a live ASR score.
                    text = "No." if fixture.get("noise") else fixture["text"]
                    pcm, first_ms = b"xx", 0
                    bounded = AsyncMock()
                    bounded.transcribe.return_value = fixture["text"]
                result = await resolve_recognition(text, pcm, context, bounded, first_ms)
                first = decision(parse_confirmation(text, "phone").kind)
                final = decision(result.confirmation.kind)
                row.update(
                    first=first,
                    final=final,
                    first_correct=first == fixture["expected"],
                    correct=final == fixture["expected"],
                    recovery_used=result.metadata.second_pass_used,
                    recovery_ms=result.metadata.second_pass_ms or 0,
                    first_pass_ms=first_ms,
                    provider_failed=result.metadata.second_pass_failed,
                )
            except Exception as error:
                row.update(provider_failed=True, error_type=type(error).__name__)
            rows.append(row)
            report = {
                "mode": "live synthetic RT + conditional bounded"
                if args.live
                else "deterministic fixtures",
                "models": {
                    "realtime": settings.streaming_stt_model,
                    "bounded": settings.structured_stt_model,
                },
                "summary": metrics(rows),
                "rows": rows,
            }
            (
                OUTPUT
                / (f"live-results-{args.run_label}.json" if args.live else "fixture-results.json")
            ).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
            print(json.dumps(row, ensure_ascii=False), flush=True)
    report_summary = metrics(rows)
    print(json.dumps(report_summary, indent=2), flush=True)
    return (
        1
        if report_summary["false_confirm"]
        or report_summary["false_reject"]
        or report_summary["provider_failures"]
        else 0
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--voices", default="cedar,coral")
    parser.add_argument("--case-ids", default="")
    parser.add_argument("--run-label", default="main")
    sys.exit(asyncio.run(run(parser.parse_args())))
