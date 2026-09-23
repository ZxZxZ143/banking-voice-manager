"""Live smoke test through the same local WebSocket used by the browser."""

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from test_openai_stream import decode_pcm
from websockets.asyncio.client import connect


async def run(path):
    pcm = decode_pcm(path)
    done = asyncio.Event()
    events = []
    async with connect(
        "ws://127.0.0.1:5173/api/v1/voice", origin="http://127.0.0.1:5173"
    ) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "start",
                    "session_id": str(uuid4()),
                    "sample_rate": 24000,
                    "channels": 1,
                    "pause_ms": 2500,
                }
            )
        )
        ready = json.loads(await asyncio.wait_for(ws.recv(), 45))
        if ready["type"] != "ready":
            raise RuntimeError(ready.get("message", "Not ready"))

        async def send():
            # Additional tail is explicitly labeled synthetic silence, not source audio.
            audio = pcm + bytes(48000 * 4)
            started = perf_counter()
            for offset in range(0, len(audio), 4800):
                await asyncio.sleep(
                    max(0, started + (offset + 4800) / 48000 - perf_counter())
                )
                if done.is_set():
                    return
                await ws.send(audio[offset : offset + 4800])
            if not done.is_set():
                await ws.send(json.dumps({"type": "finish"}))

        async def receive():
            async for message in ws:
                event = json.loads(message)
                events.append(event)
                if event["type"] in ("committed", "empty", "utterance.final", "error"):
                    done.set()
                if event["type"] in ("empty", "utterance.final", "error"):
                    return event
            raise RuntimeError("Disconnected without result")

        async with asyncio.timeout(150):
            _, result = await asyncio.gather(send(), receive())
    output = Path("work/voice/backend-stream")
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{path.stem}.json").write_text(
        json.dumps(
            {
                "source_duration_s": len(pcm) / 48000,
                "appended_silence_s": 4,
                "result": result,
                "events": events,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"audio": path.stem, "result": result}, ensure_ascii=False))
    if result["type"] == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    asyncio.run(run(parser.parse_args().audio))
