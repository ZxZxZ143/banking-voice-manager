"""Exercise real HTTP endpoints and LLM routing; never substitutes fixture replies."""

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--output", type=Path, default=Path("work/stage1-e2e.json"))
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    with urlopen(base + "/health", timeout=10) as response:
        assert json.load(response)["status"] == "ok"
    with urlopen(base + "/", timeout=10) as response:
        assert response.status == 200
    results = []

    def turn(name, text, expected, status=None, session=None):
        session = session or str(uuid4())
        payload = json.dumps(
            {"session_id": session, "text": text}, ensure_ascii=False
        ).encode()
        request = Request(
            base + "/api/message",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=65) as response:
            body = json.load(response)
        ids = [selection["scenario_id"] for selection in body["routing"]["scenarios"]]
        result = {
            "case": name,
            "text": text,
            "session_id": session,
            "scenarios": ids,
            "response_text": body["response_text"],
            "conversation_status": body["conversation_status"],
            "state": body["state"],
            "trace": body["trace"],
            "passed": False,
        }
        results.append(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            assert set(ids) == set(expected), (name, ids)
            assert body["response_text"].strip()
            assert not any(
                value in body["response_text"]
                for value in ("{", "}", "None", "null", "undefined")
            )
            assert body["trace"]["session_id"] == session
            if status:
                assert body["conversation_status"] == status, name
            result["passed"] = True
        finally:
            args.output.write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(name, ids, body["conversation_status"], flush=True)
        return session, body

    turn("RU", "Я оплатил страховку, но полис не появился.", ["SC30"])
    turn("KZ", "Маған саяхат сақтандыруы керек.", ["SC06"])
    turn(
        "mixed",
        "Маған полис керек, сколько это стоит?",
        ["SYS_UNCLEAR"],
        "awaiting_user",
    )
    turn("multi-intent", "Хочу продлить ОГПО и добавить туда сына.", ["SC27", "SC04"])
    turn(
        "clarification", "У меня проблема с полисом.", ["SYS_UNCLEAR"], "awaiting_user"
    )
    turn("operator-RU", "Соедините меня с оператором.", ["SC37"], "handoff")
    turn("operator-KZ", "Мені операторға қосыңызшы.", ["SC37"], "handoff")
    turn("goodbye", "Спасибо, до свидания.", ["SYS_GOODBYE"], "ended")
    turn("out-of-scope", "Какая завтра погода в Алматы?", ["SYS_OUT_OF_SCOPE"])
    for name, first, second in [
        ("continuation-RU", "Мне нужна туристическая страховка.", "На две недели."),
        ("continuation-KZ", "Түркияға саяхат сақтандыруы керек.", "Екі аптаға."),
        ("continuation-mixed", "Түркияға страховка керек.", "На две недели, екі адам."),
    ]:
        session, _ = turn(name + "-start", first, ["SC06"])
        _, body = turn(name, second, ["SC06"], session=session)
        assert body["trace"]["policy_outcome"] == "continue", name
        assert body["state"]["turn_number"] == 2
    session, body = turn(
        "grounded-quote",
        "Рассчитайте КАСКО: машина 2024 года, стоимость 10000000 тенге.",
        ["SC03"],
        "active",
    )
    assert "400000" in body["response_text"]
    assert body["trace"]["completed_scenario"] == "SC03"
    turn("next-action", "Как можно оплатить страховку?", ["SC31"], "active", session)
    turn(
        "same-session-handoff",
        "Хочу поговорить с человеком.",
        ["SC37"],
        "handoff",
        session,
    )
    print(f"Verified {len(results)} live API turns through {base}")


if __name__ == "__main__":
    main()
