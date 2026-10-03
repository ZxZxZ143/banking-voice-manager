"""Local Docker dashboard API/restart smoke. Evidence stores safe IDs/counts only."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect


async def voice_boundary(base_url):
    url = base_url.replace("http://", "ws://") + "/api/v1/voice"
    async with connect(url, origin=base_url, open_timeout=10) as connection:
        # Invalid config is rejected before an external STT connection; validates WS proxy.
        await connection.send(
            json.dumps({"type": "invalid", "session_id": str(uuid4())})
        )
        data = json.loads(await asyncio.wait_for(connection.recv(), timeout=10))
        assert data["type"] == "error" and data["code"] == "voice_failed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["create", "verify", "benchmark"])
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=60) as client:

        def get(path, params=None):
            response = client.get("/api/analytics/" + path, params=params)
            response.raise_for_status()
            return response.json()

        if args.mode == "create":
            if args.manifest.exists():
                raise FileExistsError("Use a new manifest")
            session = str(uuid4())
            before = get("overview", {"source": "runtime"})["total_sessions"]
            start = client.post(
                "/api/conversation/start",
                json={"session_id": session, "scenario_mode": "insurance_manager"},
            )
            start.raise_for_status()
            response = client.post(
                "/api/message",
                json={
                    "session_id": session,
                    "text": "В какое время работает ваш офис в Астане?",
                },
            )
            response.raise_for_status()
            assert response.json()["response_text"]
            assert (
                get("overview", {"source": "runtime"})["total_sessions"] == before + 1
            )
            detail = get(f"sessions/{session}/detail")
            assert (
                detail["summary"]["source"] == "runtime"
                and detail["summary"]["turn_count"] == 2
            )
            asyncio.run(voice_boundary(args.base_url))
            as_of = datetime.now(UTC).isoformat()
            evidence = {"as_of": as_of, "runtime_session": session}
            for name in ("overview", "risk", "anomalies"):
                evidence[name] = get(name, {"as_of": as_of})
            assert evidence["anomalies"]["anomalies"], "Seed --with-anomaly first"
            evidence["ids"] = []
            offset = 0
            while True:
                page = get("events", {"limit": 500, "offset": offset})
                evidence["ids"] += [e["event_id"] for e in page["events"]]
                if page["next_offset"] is None:
                    break
                offset = page["next_offset"]
            args.manifest.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "runtime_events": detail["total"],
                        "total_events": len(evidence["ids"]),
                        "overview_sessions": evidence["overview"]["total_sessions"],
                        "anomalies": evidence["anomalies"]["total"],
                        "voice_ws_boundary": "passed",
                    }
                )
            )
        else:
            evidence = json.loads(args.manifest.read_text(encoding="utf-8"))
            if args.mode == "verify":
                for name in ("overview", "risk", "anomalies"):
                    assert get(name, {"as_of": evidence["as_of"]}) == evidence[name], (
                        name
                    )
                ids, offset = [], 0
                while True:
                    page = get("events", {"limit": 500, "offset": offset})
                    ids += [e["event_id"] for e in page["events"]]
                    if page["next_offset"] is None:
                        break
                    offset = page["next_offset"]
                assert ids == evidence["ids"]
                print(
                    json.dumps(
                        {"restart_equal_aggregates": True, "retained_events": len(ids)}
                    )
                )
            else:
                timings = {}
                for name in (
                    "overview",
                    "sessions",
                    "risk",
                    "anomalies",
                    f"sessions/{evidence['runtime_session']}/detail",
                ):
                    samples = []
                    for _ in range(30):
                        start = perf_counter()
                        get(name)
                        samples.append((perf_counter() - start) * 1000)
                    timings[name] = {
                        "p50_ms": round(median(samples), 2),
                        "p95_ms": round(
                            sorted(samples)[ceil(0.95 * len(samples)) - 1], 2
                        ),
                    }
                start = perf_counter()
                get("overview")
                get("anomalies", {"limit": 20})
                get("sessions", {"limit": 5})
                timings["initial_dashboard_API_reads_serial_ms"] = round(
                    (perf_counter() - start) * 1000, 2
                )
                print(
                    json.dumps(
                        {
                            "rows": len(evidence["ids"]),
                            "samples_per_endpoint": 30,
                            "timings": timings,
                        },
                        indent=2,
                    )
                )


if __name__ == "__main__":
    main()
