"""Live Stage 3.2 dialogue checks. Only redacted evidence is saved to ignored work/."""

import argparse
import asyncio
import json
from pathlib import Path

from app.agent.errors import RouterError
from app.core.config import Settings
from app.core.services import build_services
from app.packs.insurance_manager.data.demo_profile import normalize_phone
from app.packs.insurance_manager.privacy import redact_text


async def main(output, only=()):
    if output.exists():
        raise FileExistsError("Never overwrite validation evidence")
    settings = Settings()
    if not settings.demo_test_phone:
        raise ValueError("Configure the local demo phone first")
    phone = normalize_phone(settings.demo_test_phone.get_secret_value())
    built = build_services(settings)
    cases = {
        "domestic_phone": ["Проверьте срок моего полиса", "8" + phone[2:]],
        "international_phone": ["Проверьте срок моего полиса", phone],
        "unknown": [
            "Проверьте мой полис SQ-OGPO-990001",
            "+77075551234",
            "000101399999",
        ],
        "contextual": [
            "У меня проблема с полисом",
            "С существующим",
            "Не появился",
            "Полис не появился в приложении после оплаты",
            "Оплатил первого октября",
            phone,
        ],
        "scope_return": [
            "Оплатил первого октября, деньги списались, полис не выпущен",
            "Как у тебя дела?",
            "Ты настоящий человек?",
            "Какая погода?",
            "Хочу узнать про депозит",
            phone,
        ],
        "write_update": [
            "Хочу добавить водителя в полис SQ-OGPO-990001, его ИИН 000101300000",
            phone,
        ],
        "purchase": [
            "Хочу оформить ОГПО, номер автомобиля 999DEM02",
            "ИИН водителя 000101300000",
            phone,
            "Алматы, легковой автомобиль",
        ],
        "claim": ["Проверьте статус заявления CL-990001", phone],
        "explicit_operator": ["Позовите оператора"],
    }
    rows = []
    if only:
        cases = {key: value for key, value in cases.items() if key in only}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.touch(exist_ok=False)
    for case, utterances in cases.items():
        session = "stage32-" + case
        row = {"case": case, "turns": []}
        rows.append(row)
        await built.messages.process(
            session, "", "insurance_manager", start_scenario=True
        )
        for utterance in utterances:
            await asyncio.sleep(1)
            try:
                turn = await built.messages.process(session, utterance)
                row["turns"].append(
                    {
                        "utterance": redact_text(utterance),
                        "response": turn.response_text,
                        "trace": turn.trace.model_dump(mode="json"),
                        "status": turn.conversation_status,
                    }
                )
                assert turn.scenario_pack_id == "insurance_manager"
                assert turn.trace.pack_switch is None
                assert "Product Promoter" not in turn.response_text
                if turn.conversation_status == "handoff":
                    break
            except (RouterError, AssertionError, ValueError) as exc:
                row["error"] = type(exc).__name__
                cause = exc.__cause__
                row["provider_cause"] = type(cause).__name__ if cause else None
                row["provider_status"] = getattr(cause, "status_code", None)
                break
            finally:
                output.write_text(
                    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        print(
            case,
            row.get("error", row["turns"][-1]["status"] if row["turns"] else "empty"),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    asyncio.run(main(args.output, args.case))
