"""Real STT finals routed through the shared HTTP path into the selected/current pack."""

import argparse
import asyncio
import json
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

from stage1_voice_smoke import transcribe


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--audio-directory", type=Path, default=Path("work"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new evidence path")
    session = str(uuid4())
    rows = []
    for name, mode, expected in [
        ("product", "product_promoter", "product_promoter"),
        ("product-prefs", None, "product_promoter"),
        ("payment", "insurance_manager", "insurance_manager"),
    ]:
        final, events = await transcribe(
            args.base_url, session, args.audio_directory / f"voice-{name}.wav"
        )
        payload = {"session_id": session, "text": final["text"]}
        if mode:
            payload["scenario_mode"] = mode
        with urlopen(
            Request(
                args.base_url + "/api/message",
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
            ),
            timeout=100,
        ) as response:
            body = json.load(response)
        rows.append(
            {"audio": name, "final": final, "events": events, "request": payload, "response": body}
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        assert events["utterance.final"] == 1
        assert body["trace"]["scenario_pack_id"] == expected and body["session_id"] == session
        assert body["trace"]["turn"] == len(rows)
        if name == "product-prefs":
            assert body["state"]["preferences"]["liquidity"] is True
            assert body["state"]["preferences"]["amount"] == 50000
        if name == "payment":
            assert body["routing"]["scenarios"][0]["scenario_id"] == "SC31"
        print(name, expected, "STT", final.get("stt_after_commit_ms"), flush=True)
    print(
        "PASS: product discovery, continued product preferences and switch to Insurance; one UUID",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
