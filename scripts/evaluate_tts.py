"""Generate PUBLIC SYNTHETIC samples only; no customer data or runtime audio storage.

Optional local engines are installed in a separate evaluation environment. Model files
must be predownloaded from the documented sources and match an explicit SHA-256.
No hub code/download executes implicitly. Subjective scores require human listening.
"""

import argparse
import asyncio
import hashlib
import io
import json
import platform
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def audio_metrics(data):
    import av
    import numpy as np

    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.audio[0]
        frames = list(container.decode(stream))
        assert frames
        samples = np.concatenate([frame.to_ndarray().reshape(-1) for frame in frames])
        if np.issubdtype(samples.dtype, np.integer):
            samples = samples.astype(float) / max(
                abs(np.iinfo(samples.dtype).min), np.iinfo(samples.dtype).max
            )
        duration = sum(frame.samples / frame.sample_rate for frame in frames)
        assert duration > 0 and np.isfinite(samples).all()
        return {
            "sample_rate": frames[0].sample_rate,
            "duration_seconds": round(duration, 3),
            "peak": round(float(np.max(np.abs(samples))), 5),
            "clipped_samples": int(np.sum(np.abs(samples) >= 0.999)),
            "bytes": len(data),
        }


def checked_path(args):
    path = Path(args.model_path)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if not args.sha256 or actual != args.sha256:
        raise ValueError("Predownloaded model SHA-256 does not match explicit expected digest")
    return path


async def run(args):
    from app.speech.tts.normalization import prepare_speech

    started = time.perf_counter()
    if args.provider == "silero":
        import torch

        torch.set_num_threads(4)
        model = torch.package.PackageImporter(str(checked_path(args))).load_pickle(
            "tts_models", "model"
        )
        model.to(torch.device("cpu"))
        print(json.dumps({"speakers": model.speakers}), flush=True)

        async def synthesize(text, language):
            audio = model.apply_tts(text=text, speaker=args.voice, sample_rate=24000)
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav:
                wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                wav.writeframes((audio.clamp(-1, 1).numpy() * 32767).astype("<i2").tobytes())
            return buffer.getvalue(), None, "wav"
    elif args.provider == "piper":
        from piper import PiperVoice, SynthesisConfig

        model = PiperVoice.load(str(checked_path(args)))

        async def synthesize(text, language):
            buffer = io.BytesIO()
            first = None
            start = time.perf_counter()
            with wave.open(buffer, "wb") as wav:
                for chunk in model.synthesize(
                    text,
                    syn_config=SynthesisConfig(
                        speaker_id=int(args.voice), length_scale=1.05, volume=0.9
                    ),
                ):
                    if first is None:
                        first = (time.perf_counter() - start) * 1000
                        wav.setparams(
                            (
                                chunk.sample_channels,
                                chunk.sample_width,
                                chunk.sample_rate,
                                0,
                                "NONE",
                                "not compressed",
                            )
                        )
                    wav.writeframes(chunk.audio_int16_bytes)
            return buffer.getvalue(), first, "wav"
    else:
        from app.core.config import Settings
        from app.speech.tts.openai_provider import OpenAITTSProvider

        config = Settings()
        model = OpenAITTSProvider(
            api_key=config.openai_api_key.get_secret_value() if config.openai_api_key else None,
            model=args.model,
            voice=args.voice,
            timeout_seconds=90,
            instructions_ru=config.backend_tts_instructions_ru,
            instructions_kk=config.backend_tts_instructions_kk,
        )

        async def synthesize(text, language):
            result = await model.synthesize(text, language)
            return result.audio, result.first_audio_latency_ms, "mp3"

    cold_ms = (time.perf_counter() - started) * 1000
    identity = args.model if args.provider == "openai" else Path(args.model_path).stem
    output = (
        ROOT
        / "work"
        / "tts-eval"
        / f"{args.provider}-{identity}-{args.voice}-{platform.system().lower()}"
    )
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    if args.resume and (output / "measurements.json").exists():
        rows = json.loads((output / "measurements.json").read_text(encoding="utf-8"))
    samples = json.loads((ROOT / "data/tts/eval_samples.json").read_text(encoding="utf-8"))
    samples = [row for row in samples if not args.language or row["language"] == args.language]
    if args.limit:
        samples = samples[: args.limit]
    for sample in samples:
        if args.resume and any(row["id"] == sample["id"] for row in rows):
            continue
        start = time.perf_counter()
        text = prepare_speech(sample["text"], sample["language"])
        audio, first_ms, extension = await synthesize(text, sample["language"])
        full_ms = (time.perf_counter() - start) * 1000
        path = output / f"{sample['id']}.{extension}"
        path.write_bytes(audio)
        row = dict(
            id=sample["id"],
            language=sample["language"],
            provider=args.provider,
            model=args.model if args.provider == "openai" else Path(args.model_path).name,
            voice=args.voice,
            initialization_ms=round(cold_ms, 2),
            first_chunk_ms=round(first_ms, 2) if first_ms is not None else None,
            full_audio_ms=round(full_ms, 2),
            file=path.name,
            **audio_metrics(audio),
        )
        try:
            import psutil

            row["rss_mib"] = round(psutil.Process().memory_info().rss / 1024**2, 1)
        except ImportError:
            row["rss_mib"] = None
        rows.append(row)
        (output / "measurements.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(row, ensure_ascii=True), flush=True)
    listening = output / "LISTENING.md"
    if listening.exists():
        return  # Preserve human notes and scores when resuming or regenerating audio.
    listening.write_text(
        "# Human listening required\n\nInternal 1–5 scale, not MOS. "
        "No scores assigned automatically.\n\n"
        "| Sample | Naturalness | Feminine presentation | Clarity | Numbers | Pauses | "
        "Pronunciation | Robotic artifacts | Listener/date |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        + "".join(f"| {row['file']} | | | | | | | | |\n" for row in rows),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=["silero", "piper", "openai"])
    parser.add_argument("--model-path")
    parser.add_argument("--sha256")
    parser.add_argument("--model", default="gpt-4o-mini-tts")
    parser.add_argument("--voice", required=True)
    parser.add_argument("--language", choices=["ru", "kk"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    asyncio.run(run(parser.parse_args()))
