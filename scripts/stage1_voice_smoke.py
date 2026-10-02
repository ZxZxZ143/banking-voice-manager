"""Real PCM/WebSocket/OpenAI/Agent smoke; supply locally generated test WAVs."""

import argparse
import asyncio
import json
import wave
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

from websockets.asyncio.client import connect


async def transcribe(base, session, audio, *, pause_ms=500):
    with wave.open(str(audio), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (
            24000,
            1,
            2,
        )
        pcm = wav.readframes(wav.getnframes())
    committed = asyncio.Event()
    counts = {}
    async with connect(
        base.replace("http", "ws", 1) + "/api/v1/voice",
        origin=base,
        open_timeout=30,
    ) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "start",
                    "session_id": session,
                    "sample_rate": 24000,
                    "channels": 1,
                    "pause_ms": pause_ms,
                }
            )
        )
        ready = json.loads(await asyncio.wait_for(ws.recv(), 45))
        assert ready["type"] == "ready", ready

        async def send_audio():
            # Real-time pacing matches the browser. Silence exercises VAD endpointing.
            stream = pcm + bytes(48000)
            for offset in range(0, len(stream), 2400):
                if committed.is_set():
                    return
                await ws.send(stream[offset : offset + 2400])
                await asyncio.sleep(0.05)
            if not committed.is_set():
                await ws.send(json.dumps({"type": "finish"}))

        async def receive_final():
            async for raw in ws:
                event = json.loads(raw)
                kind = event["type"]
                counts[kind] = counts.get(kind, 0) + 1
                assert kind not in {"error", "empty"}, event
                if kind == "committed":
                    committed.set()
                if kind == "utterance.final":
                    assert event["text"].strip()
                    return event
            raise AssertionError("Voice socket closed without a final transcript")

        sender = asyncio.create_task(send_audio())
        try:
            final = await asyncio.wait_for(receive_final(), 60)
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
    return final, counts


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--audio-directory", type=Path, default=Path("work"))
    parser.add_argument("--output", type=Path, default=Path("work/docker-voice.json"))
    args = parser.parse_args()
    results = []
    for name, scenario, status in [
        ("payment", "SC31", "active"),
        ("operator", "SC37", "handoff"),
        ("goodbye", "SYS_GOODBYE", "ended"),
    ]:
        session = str(uuid4())
        final, events = await transcribe(
            args.base_url, session, args.audio_directory / f"voice-{name}.wav"
        )
        # Only the actual final transcript becomes one Agent turn in the same session.
        request = Request(
            args.base_url + "/api/message",
            data=json.dumps({"session_id": session, "text": final["text"]}).encode(),
            headers={"Content-Type": "application/json"},
        )

        def read_response(current_request=request):
            with urlopen(current_request, timeout=60) as response:
                return json.load(response)

        body = await asyncio.to_thread(read_response)
        assert [s["scenario_id"] for s in body["routing"]["scenarios"]] == [scenario]
        assert body["conversation_status"] == status
        assert body["trace"]["session_id"] == session
        assert body["state"]["turn_number"] == 1
        results.append(
            {
                "case": name,
                "source": "synthetic Windows speech fixture",
                "session_id": session,
                "final": final,
                "events": events,
                "response_text": body["response_text"],
                "status": status,
            }
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(name, repr(final["text"]), status, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
