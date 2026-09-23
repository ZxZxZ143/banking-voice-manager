"""Transcribe the numbered voice test recordings locally, without reference hints."""

import argparse
import csv
import json
import re
from pathlib import Path
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("work/voice/small"))
    parser.add_argument("--model", default="small")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--cache", type=Path, default=Path("work/models"))
    args = parser.parse_args()
    files = sorted(p for p in args.input_dir.glob("A*.m4a")
                   if re.fullmatch(r"A(?:0[1-9]|1[0-9]|2[0-7])_[a-z0-9_]+", p.stem))
    ids = [p.stem.split("_")[0] for p in files]
    expected = [f"A{i:02d}" for i in range(1, 28)]
    if ids != expected:
        parser.error("Expected exactly one recording for each A01 through A27.")
    from faster_whisper import WhisperModel

    args.output.mkdir(parents=True, exist_ok=True)
    print(f"Loading {args.model} on {args.device}...", flush=True)
    started = perf_counter()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type,
                         download_root=str(args.cache), cpu_threads=4)
    report = {"model": args.model, "device": args.device,
              "compute_type": args.compute_type,
              "model_load_ms": round((perf_counter() - started) * 1000, 2),
              "mode": "offline; latency includes decoding, VAD and full transcription",
              "results": []}
    for index, path in enumerate(files, 1):
        started = perf_counter()
        row = {"audio_id": path.stem, "filename": path.name}
        try:
            segments, info = model.transcribe(
                str(path), task="transcribe", language=None, beam_size=5,
                vad_filter=True, condition_on_previous_text=False,
            )
            segments = list(segments)  # Lazy decoding must finish before stopping timer.
            row.update(
                text="".join(s.text for s in segments).strip(),
                detected_language=info.language,
                language_probability=info.language_probability,
                duration_s=info.duration,
                speech_duration_s=info.duration_after_vad,
                segments=[{"start": s.start, "end": s.end, "text": s.text}
                          for s in segments],
                status="ok",
            )
        except Exception as exc:
            row.update(status="error", error=str(exc))
        row["stt_latency_ms"] = round((perf_counter() - started) * 1000, 2)
        report["results"].append(row)
        (args.output / "transcripts.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{index}/27] {path.stem}: {row['status']} "
              f"({row['stt_latency_ms']} ms)", flush=True)
    with (args.output / "transcripts.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["audio_id", "status", "text", "detected_language", "duration_s",
                  "speech_duration_s", "stt_latency_ms", "error"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["results"])
    if any(r["status"] == "error" for r in report["results"]):
        raise SystemExit("Some recordings failed; inspect transcripts.json.")


if __name__ == "__main__":
    main()
