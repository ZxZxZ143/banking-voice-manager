"""Live Docker HTTP product journeys and cross-pack state checks; no model fixtures."""

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new evidence path")
    rows = []

    def turn(flow, session, text, mode=None):
        payload = {"session_id": session, "text": text}
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
        assert body["response_text"].strip() and body["session_id"] == session
        assert body["trace"]["session_id"] == session
        rows.append({"flow": flow, "request": payload, "response": body})
        print(flow, body["trace"]["scenario_pack_id"], body["conversation_status"], flush=True)
        return body

    def terminal_closed(session):
        try:
            turn("closed", session, "Ещё один вопрос")
        except HTTPError as exc:
            assert exc.code == 409
        else:
            raise AssertionError("Terminal session accepted a new turn")

    with urlopen(args.base_url + "/health", timeout=10) as response:
        assert json.load(response)["status"] == "ok"
    try:
        session = str(uuid4())
        first = turn("A-deposit-discovery", session, "Хочу открыть депозит.", "product_promoter")
        assert first["state"]["last_question"] == "liquidity"
        second = turn(
            "A-deposit-preferences",
            session,
            "Нужно частичное снятие. Сумма 50000 тенге на 12 месяцев, хочу пополнять.",
        )
        assert second["state"]["preferences"]["amount"] == 50000
        assert second["state"]["products"][0]["id"] == "DEP-FLEX"
        interest = turn("A-deposit-interest", session, "Хочу оформить этот депозит.")
        assert interest["state"]["sales_lead"]["outcome"] == "interested"
        assert interest["state"]["sales_lead"]["selected_product_id"] == "DEP-FLEX"
        assert interest["conversation_status"] == "active"
        session = str(uuid4())
        card = turn("B-card", session, "Мне нужна карта с cashback.", "product_promoter")
        assert card["state"]["products"][0]["id"] == "CARD-REWARD"
        objection = turn(
            "C-objection",
            session,
            "700 тенге в месяц дорого. Нужна карта без платы за обслуживание.",
        )
        assert "fees" in objection["state"]["objections"]
        assert objection["state"]["products"][0]["id"] == "CARD-DAILY"
        compare = turn("B-card-comparison", session, "Сравните Повседневную и Бонусную карты.")
        assert set(compare["state"]["compared_products"]) == {"CARD-DAILY", "CARD-REWARD"}
        decline = turn("D-decline", session, "Не хочу никаких продуктов, прекратите предложения.")
        assert decline["state"]["sales_lead"]["outcome"] == "declined"
        assert "?" not in decline["response_text"] and decline["conversation_status"] == "active"
        neutral = turn("D-after-decline", session, "Понятно, спасибо за информацию.")
        assert neutral["state"]["sales_lead"]["interest_level"] == "declined"
        session = str(uuid4())
        insurance = turn("E-insurance-start", session, "Мне нужна страховка для поездки в Турцию.")
        assert insurance["state"]["active_scenario"] == "SC06"
        product = turn(
            "E-switch-to-product",
            session,
            "Подбираю депозит в тенге на 12 месяцев: 50000, нужно снимать часть.",
            "product_promoter",
        )
        assert product["state"]["preferences"]["amount"] == 50000
        assert "slots" not in product["state"] and "scenario_slots" not in product["state"]
        resumed = turn("G-resume-insurance", session, "На две недели.", "insurance_manager")
        assert resumed["trace"]["context_lifecycle"] == "resumed"
        for key, value in insurance["state"]["slots"].items():
            assert resumed["state"]["slots"].get(key) == value
        assert resumed["state"]["active_scenario"] == "SC06"
        assert resumed["routing"]["is_continuation"] is True
        assert "product_category" not in resumed["state"]
        back = turn("G-resume-product", session, "Сравните депозиты.", "product_promoter")
        assert back["trace"]["context_lifecycle"] == "resumed"
        assert back["state"]["preferences"]["amount"] == 50000
        assert back["state"]["preferences"]["currency"] == "KZT"
        session = str(uuid4())
        turn("F-product-start", session, "Карта с cashback нужна.", "product_promoter")
        turn(
            "F-switch-insurance",
            session,
            "Хочу добавить водителя в страховой полис.",
            "insurance_manager",
        )
        product = turn(
            "F-resume-product", session, "Хочу без платы за обслуживание.", "product_promoter"
        )
        assert product["state"]["preferences"]["cashback"] is True
        assert product["state"]["preferences"]["fee_sensitive"] is True
        assert product["trace"]["context_lifecycle"] == "resumed"
        session = str(uuid4())
        suggestion = turn(
            "natural-insurance-to-product", session, "Расскажите о банковском депозите."
        )
        assert suggestion["conversation_status"] == "awaiting_confirmation"
        confirmed = turn("natural-confirm-product", session, "Да, переключай.")
        assert confirmed["trace"]["scenario_pack_id"] == "product_promoter"
        suggestion = turn(
            "natural-product-to-insurance", session, "Мне нужна страховка для путешествия."
        )
        assert suggestion["conversation_status"] == "awaiting_confirmation"
        confirmed = turn("natural-confirm-insurance", session, "Да.")
        assert confirmed["trace"]["scenario_pack_id"] == "insurance_manager"
        session = str(uuid4())
        handoff = turn("H-product-handoff", session, "Соедините с оператором.", "product_promoter")
        assert handoff["response_text"] == "Конечно, передаю диалог оператору."
        assert handoff["conversation_status"] == "handoff"
        terminal_closed(session)
        session = str(uuid4())
        goodbye = turn("I-product-goodbye-KK", session, "Рақмет, сау болыңыз.", "product_promoter")
        assert goodbye["conversation_status"] == "ended"
        assert goodbye["state"]["response_language"] == "kk"
        terminal_closed(session)
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(rows, file, ensure_ascii=False, indent=2)
    print(
        f"PASS: {len(rows)} live turns; all nine required journeys plus natural switches",
        flush=True,
    )


if __name__ == "__main__":
    main()
