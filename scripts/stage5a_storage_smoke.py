"""Real API/model smoke and restart evidence. Manifest contains only safe IDs/counts.

create: call Docker's existing same-origin proxy and save committed event IDs.
verify: after restart/down/up, require exactly the same IDs for every smoke session.
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

import httpx


def create(client, output):
    if output.exists():
        raise FileExistsError("Use a new evidence path")
    prefix = "stage5a-" + uuid4().hex[:12]
    sessions = {
        name: prefix + "-" + name for name in ("insurance", "sales", "fraud", "ended")
    }
    timings = []

    def post(path, body):
        start = time.perf_counter()
        response = client.post(path, json=body)
        response.raise_for_status()
        data = response.json()
        assert data["response_text"] and data["session_id"] == body["session_id"]
        timings.append(round((time.perf_counter() - start) * 1000, 2))
        return data

    post(
        "/api/conversation/start",
        {"session_id": sessions["insurance"], "scenario_mode": "insurance_manager"},
    )
    post(
        "/api/message",
        {
            "session_id": sessions["insurance"],
            "text": "В какое время работает ваш офис в Астане?",
        },
    )
    post(
        "/api/conversation/start",
        {"session_id": sessions["sales"], "scenario_mode": "card_promoter"},
    )
    sales = post(
        "/api/message",
        {
            "session_id": sessions["sales"],
            "text": "Мне подходит эта карта. Хочу оформить заявку.",
        },
    )
    lead = sales["state"]["sales_lead"]
    risk = post(
        "/api/message",
        {
            "session_id": sessions["sales"],
            "channel": "voice",
            "text": "Мне звонят якобы из банка и просят назвать код из SMS.",
        },
    )
    assert (
        risk["risk"]["analysis_status"] == "analyzed" and risk["risk"]["risk_relevant"]
    )
    assert (
        risk["state"]["sales_lead"] == lead and risk["trace"].get("pack_switch") is None
    )
    post(
        "/api/conversation/start",
        {"session_id": sessions["fraud"], "scenario_mode": "fraud_security"},
    )
    fraud = post(
        "/api/message",
        {
            "session_id": sessions["fraud"],
            "text": "Звонящий представился сотрудником банка и просит код из SMS.",
        },
    )
    assert fraud["state"]["fraud_case"]["case_type"] == "social_engineering"
    handoff = post(
        "/api/message",
        {"session_id": sessions["fraud"], "text": "Да, я уже сообщил ему код."},
    )
    assert handoff["conversation_status"] == "handoff"
    post(
        "/api/conversation/start",
        {"session_id": sessions["ended"], "scenario_mode": "insurance_manager"},
    )
    ended = post(
        "/api/message",
        {"session_id": sessions["ended"], "text": "Спасибо за помощь, до свидания."},
    )
    assert ended["conversation_status"] == "ended"
    journeys = {}
    counts = Counter()
    for name, session in sessions.items():
        response = client.get(
            "/api/analytics/sessions/" + session, params={"limit": 500}
        )
        response.raise_for_status()
        page = response.json()
        assert page["total"] == len(page["events"])
        assert [(e["turn_number"], e["sequence"]) for e in page["events"]] == sorted(
            (e["turn_number"], e["sequence"]) for e in page["events"]
        )
        journeys[name] = {
            "session_id": session,
            "event_ids": [e["event_id"] for e in page["events"]],
        }
        counts.update(e["event_type"] for e in page["events"])
    for kind in (
        "insurance_result",
        "sales_lead",
        "risk_signal",
        "fraud_case",
        "operator_handoff",
        "conversation_ended",
    ):
        assert counts[kind] > 0
    assert client.get("/health").json()["analytics"]["status"] == "ok"
    summary = client.get("/api/analytics/summary").json()
    assert summary["conversations"] >= 4
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {"journeys": journeys, "counts": counts, "request_ms": timings}, indent=2
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "event_counts": counts,
                "total": sum(counts.values()),
                "customer_requests": len(timings),
                "business_state_preserved": True,
            }
        )
    )


def verify(client, output):
    manifest = json.loads(output.read_text(encoding="utf-8"))
    for expected in manifest["journeys"].values():
        response = client.get(
            "/api/analytics/sessions/" + expected["session_id"], params={"limit": 500}
        )
        response.raise_for_status()
        page = response.json()
        assert [e["event_id"] for e in page["events"]] == expected["event_ids"]
        assert page["total"] == len(expected["event_ids"])
    assert client.get("/health").json()["analytics"]["status"] == "ok"
    print(
        json.dumps(
            {
                "restart_persistence": True,
                "sessions": len(manifest["journeys"]),
                "events": sum(manifest["counts"].values()),
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("create", "verify"))
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--openapi-url", default="http://127.0.0.1:8000/openapi.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.phase == "create":
        spec_response = httpx.get(args.openapi_url, timeout=10)
        spec_response.raise_for_status()
        assert "/api/analytics/events" in spec_response.json()["paths"]
    with httpx.Client(base_url=args.base_url, timeout=90) as client:
        (create if args.phase == "create" else verify)(client, args.output)


if __name__ == "__main__":
    main()
