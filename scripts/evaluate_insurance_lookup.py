"""Focused live semantic identifier regressions; outputs statuses, never private values."""

import asyncio
import json

from app.core.config import Settings
from app.core.services import build_services
from app.packs.insurance_manager.state import ConversationState, DialogState, DialogTurn


async def main():
    built = build_services(Settings(demo_test_phone=None))
    cases = [
        ("ru_absent", "ru", "У меня его нет"),
        ("ru_memory", "ru", "Номер полиса не помню"),
        ("ru_unavailable", "ru", "Не могу сейчас найти документ с номером"),
        ("ru_alternative", "ru", "Нет под рукой, можно поискать по телефону?"),
        ("kk_absent", "kk", "Менде полис нөмірі жоқ"),
        ("kk_memory", "kk", "Полис нөмірін ұмытып қалдым"),
        ("kk_unavailable", "kk", "Қазір құжатым қолымда жоқ"),
        (
            "kk_alternative",
            "kk",
            "Телефон нөмірі арқылы тексере аласыз ба? Полис нөмірін білмеймін",
        ),
    ]
    rows = []
    for name, language, text in cases:
        question = (
            "Назовите номер полиса?" if language == "ru" else "Полис нөмірін айтыңызшы?"
        )
        state = DialogState(
            session_id=name,
            active_scenario="SC27",
            language=language,
            response_language=language,
            turn_number=2,
            conversation=ConversationState(
                expected_slot="policy_number",
                expected_answer_type="slot",
                last_question=question,
            ),
            history=[DialogTurn(role="assistant", text=question)],
        )
        decision = await built.insurance.processor.router.route(text, state)
        answer = decision.identifier_answer
        passed = bool(
            answer
            and answer.status == "unavailable"
            and answer.field == "policy_number"
            and built.policy.decide(decision, state).outcome == "continue"
            and decision.conversation_signal in {"answer", "partial_answer"}
        )
        rows.append({"case": name, "passed": passed})
        print(json.dumps(rows[-1]), flush=True)
    assert all(row["passed"] for row in rows), (
        "Focused identification regression failed"
    )


if __name__ == "__main__":
    asyncio.run(main())
