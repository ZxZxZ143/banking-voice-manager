"""Real streaming STT → one Insurance turn per final, with synthetic audio only."""

import argparse
import asyncio
import json
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

from stage1_voice_smoke import transcribe


def post(base, endpoint, payload):
    request = Request(
        base + endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=60) as response:
        return json.load(response)


async def main(args):
    if args.output.exists():
        raise FileExistsError("Never overwrite evidence")
    rows = []
    for name, seed, expected in [
        ("phone", "Закажите мне обратный звонок", "phone"),
        ("iin", "Проверьте мой класс бонус-малус", "iin"),
        ("existing", "У меня проблема со страховкой", None),
    ]:
        session = str(uuid4())
        await asyncio.to_thread(
            post,
            args.base_url,
            "/api/conversation/start",
            {"session_id": session, "scenario_mode": "insurance_manager"},
        )
        seeded = await asyncio.to_thread(
            post, args.base_url, "/api/message", {"session_id": session, "text": seed}
        )
        seed_row = {
            "case": name,
            "seed_response": seeded["response_text"],
            "seed_trace": seeded["trace"],
        }
        rows.append(seed_row)
        args.output.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if expected:
            assert seeded["trace"]["expected_slot"] == expected, seeded["trace"]
        final, events = await transcribe(
            args.base_url,
            session,
            args.audio_directory / f"voice-{name}.wav",
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
        assert body["trace"]["turn"] == seeded["trace"]["turn"] + 1
        assert body["conversation_status"] not in {"handoff", "ended"}
        if expected:
            assert (
                expected in body["state"]["slots"]
                or body["trace"]["completed_scenario"]
            )
        assert body["trace"]["repair_attempts"] == 0
        print(f"{name}: PASS", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--audio-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
