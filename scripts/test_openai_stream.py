"""Replay one recording at real-time speed to OpenAI transcription over WebSocket."""

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
RATE = 24000
FRAME_BYTES = 4800  # 100 ms, mono PCM16.


def decode_pcm(path):
    import av

    chunks = []
    resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                chunks.append(converted.to_ndarray().astype("<i2").tobytes())
                if sum(map(len, chunks)) > RATE * 2 * 120:
                    raise ValueError("Recording exceeds 120 seconds.")
        for converted in resampler.resample(None):
            chunks.append(converted.to_ndarray().astype("<i2").tobytes())
    pcm = b"".join(chunks)
    if len(pcm) < FRAME_BYTES:
        raise ValueError("Recording must contain at least 100 ms of audio.")
    return pcm


async def replay(pcm, key, report):
    from websockets.asyncio.client import connect

    started = perf_counter()
    async with connect(
        "wss://api.openai.com/v1/realtime?intent=transcription",
        additional_headers={"Authorization": f"Bearer {key}"},
        open_timeout=20, close_timeout=5, max_size=2_000_000,
    ) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {"type": "transcription", "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": RATE},
                "transcription": {
                    "model": "gpt-live-transcribe", "languages": ["kk", "ru"],
                    "prompt": "Insurance customer speech in Kazakh and Russian, sometimes mixed.",
                    "delay": "medium",
                },
                "turn_detection": None,
            }}},
        }))
        async with asyncio.timeout(30):
            while True:
                event = json.loads(await ws.recv())
                if event["type"] == "error":
                    raise RuntimeError("OpenAI rejected session configuration; check model access.")
                if event["type"] == "session.updated":
                    break
        report["setup_ms"] = round((perf_counter() - started) * 1000, 2)
        streaming_started = perf_counter()
        committed_at = None

        async def send_audio():
            nonlocal committed_at
            for offset in range(0, len(pcm), FRAME_BYTES):
                chunk = pcm[offset:offset + FRAME_BYTES]
                # Pace like capture: a frame is available only after its audio duration.
                target = streaming_started + (offset + len(chunk)) / (RATE * 2)
                await asyncio.sleep(max(0, target - perf_counter()))
                await ws.send(json.dumps({"type": "input_audio_buffer.append",
                                          "audio": base64.b64encode(chunk).decode("ascii")}))
            committed_at = perf_counter()
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

        async def receive_text():
            while True:
                event = json.loads(await ws.recv())
                kind = event.get("type", "")
                if kind == "error" or kind.endswith(".failed"):
                    raise RuntimeError("OpenAI transcription failed; inspect account access/quota.")
                if kind.endswith("input_audio_transcription.delta"):
                    report["partials"].append({
                        "received_ms": round((perf_counter() - streaming_started) * 1000, 2),
                        "item_id": event.get("item_id"), "delta": event.get("delta", ""),
                    })
                if kind.endswith("input_audio_transcription.completed"):
                    report["text"] = event["transcript"]
                    report["item_id"] = event.get("item_id")
                    report["final_after_commit_ms"] = (
                        round((perf_counter() - committed_at) * 1000, 2)
                        if committed_at is not None else None
                    )
                    return

        async with asyncio.timeout(len(pcm) / (RATE * 2) + 60):
            async with asyncio.TaskGroup() as group:
                group.create_task(send_audio())
                group.create_task(receive_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    args = parser.parse_args()
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        parser.error("Add OPENAI_API_KEY to the root .env file. Never paste it into chat.")
    if not args.audio.is_file() or args.audio.stat().st_size > 25_000_000:
        parser.error("Audio must exist and be under 25 MB.")
    pcm = decode_pcm(args.audio)
    report = {"audio_id": args.audio.stem, "model": "gpt-live-transcribe",
              "duration_s": len(pcm) / (RATE * 2), "partials": [],
              "note": "Manual commit at file end; no automatic endpointing or TTS measured."}
    try:
        asyncio.run(replay(pcm, key, report))
        report["status"] = "ok"
    except Exception:
        # Avoid logging headers, API keys or raw server errors.
        report["status"] = "error"
        print("Cloud test failed: check API key, model access, quota and connectivity.")
    output = ROOT / "work/voice/openai-stream"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{args.audio.stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {args.audio.stem}: {report['status']}")
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
