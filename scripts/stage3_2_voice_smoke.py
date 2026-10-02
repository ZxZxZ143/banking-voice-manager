"""Actual voice websocket -> final transcript -> one Insurance turn. Synthetic audio only."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from stage1_voice_smoke import transcribe
from stage3_1_voice_smoke import post


async def main(args):
    if args.output.exists():
        raise FileExistsError("Never overwrite evidence")
    rows = []
    args.output.touch(exist_ok=False)
    for name, seed, files in [
        ("phone", "Проверьте срок моего полиса", ["phone"]),
        (
            "context_scope_return",
            "У меня проблема с существующим полисом",
            ["short", "social", "return"],
        ),
    ]:
        if args.case and name not in args.case:
            continue
        session = str(uuid4())
        await asyncio.to_thread(
            post,
            args.base_url,
            "/api/conversation/start",
            {"session_id": session, "scenario_mode": "insurance_manager"},
        )
        previous = await asyncio.to_thread(
            post, args.base_url, "/api/message", {"session_id": session, "text": seed}
        )
        for audio in files:
            final, events = await transcribe(
                args.base_url,
                session,
                args.audio_directory / f"voice-{audio}.wav",
                pause_ms=2500,
            )
            body = await asyncio.to_thread(
                post,
                args.base_url,
                "/api/message",
                {"session_id": session, "text": final["text"]},
            )
            row = {
                "case": name,
                "audio": audio,
                "events": events,
                "stt_ms": final.get("stt_after_commit_ms"),
                "response": body["response_text"],
                "trace": body["trace"],
                "status": body["conversation_status"],
            }
            rows.append(row)
            args.output.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            assert events.get("utterance.final") == 1
            assert body["trace"]["turn"] == previous["trace"]["turn"] + 1
            assert body["conversation_status"] not in {"handoff", "ended"}
            assert body["trace"]["scenario_pack_id"] == "insurance_manager"
            assert body["trace"]["pack_switch"] is None
            if audio == "phone":
                assert body["trace"]["expected_slot"] != "phone"
            if audio == "return":
                assert body["trace"]["active_scenario"] == "SC30"
            previous = body
            print(audio + ": PASS", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--audio-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--case", action="append", choices=["phone", "context_scope_return"], default=[]
    )
    asyncio.run(main(parser.parse_args()))
