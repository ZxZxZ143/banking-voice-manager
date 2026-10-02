"""Live private-state preservation checks using production composition and model calls."""

import argparse
import asyncio
import json
from pathlib import Path

from app.core.config import Settings
from app.core.services import build_services


async def smoke(output):
    if output.exists():
        raise FileExistsError("Never overwrite evidence")
    built = build_services(Settings(demo_test_phone=None))
    rows, captured = [], []
    actual = built.messages.risk.agent.analyze

    async def observe(payload):
        captured.append(payload.model_dump(mode="json"))
        return await actual(payload)

    built.messages.risk.agent.analyze = observe
    for mode, first, incident, continuation in [
        (
            "card_promoter",
            "Для меня главное — кешбэк за покупки.",
            "Мне карта подходит, но звонят якобы из банка и просят код из SMS.",
            "Продолжим оформление этой карты. Как ее открыть?",
        ),
        (
            "insurance_manager",
            "Хочу страховку для поездки в Турцию на семь дней.",
            "От имени страховщика прислали подозрительную ссылку и просят перейти.",
            "Поездка начинается десятого октября 2026 года.",
        ),
    ]:
        session = "stage4-cross-" + mode
        await built.messages.process(session, "", mode, start_scenario=True)
        await built.messages.process(session, first)
        before = (
            built.dialogs.get_conversation(session)
            .scenario_contexts[mode]
            .model_copy(deep=True)
        )
        risk = await built.messages.process(session, incident)
        after = built.dialogs.get_conversation(session)
        resumed = await built.messages.process(session, continuation)
        checks = {
            "incident_analyzed": risk.risk.analysis_status == "analyzed"
            and risk.risk.risk_relevant,
            "expected_risk_level": risk.risk.level
            == ("high" if mode == "card_promoter" else "medium"),
            "state_exact": before.state == after.scenario_contexts[mode].state,
            "result_exact": before.result == after.scenario_contexts[mode].result,
            "lifecycle_exact": before.lifecycle
            == after.scenario_contexts[mode].lifecycle,
            "no_automatic_switch": after.active_scenario_pack == mode
            and "fraud_security" not in after.scenario_contexts
            and risk.trace.pack_switch is None,
            "no_business_actions_on_warning": not risk.trace.actions
            and risk.trace.latency_ms.router is None,
            "continuation_same_pack": resumed.scenario_pack_id == mode
            and resumed.trace.pack_switch is None,
            "continuation_skips_risk": resumed.risk is None,
            "one_turn_per_message": resumed.trace.turn == 4,
        }
        rows.append(
            {
                "mode": mode,
                "checks": checks,
                "risk_reply": risk.response_text,
                "risk": risk.risk.model_dump(mode="json"),
                "resume_reply": resumed.response_text,
                "risk_latency_ms": risk.trace.latency_ms.model_dump(),
                "normal_latency_ms": resumed.trace.latency_ms.model_dump(),
            }
        )
    await built.messages.process(
        "stage4-manual", "", "card_promoter", start_scenario=True
    )
    one = await built.messages.process(
        "stage4-manual", "Звонящий просит назвать код из SMS.", "fraud_security"
    )
    two = await built.messages.process("stage4-manual", "Да, я уже сообщил код.")
    rows.append(
        {
            "mode": "manual_fraud",
            "checks": {
                "explicit_switch_only": one.trace.pack_switch.source == "explicit",
                "safe_question": one.state.pending_question == "exposure",
                "exposure_handoff": two.risk.level == "critical"
                and two.conversation_status == "handoff",
                "case_result": two.state.fraud_case.case_status == "needs_review",
                "terminal_phrase": two.response_text.endswith(
                    "Конечно, передаю диалог оператору."
                ),
            },
            "reply": two.response_text,
        }
    )
    await built.messages.process(
        "stage4-negative", "", "card_promoter", start_scenario=True
    )
    routine = await built.messages.process(
        "stage4-negative", "Нужно ли подтверждение по SMS для оплаты?"
    )
    rows.append(
        {
            "mode": "routine_sms",
            "checks": {
                "no_high_risk": routine.risk.analysis_status == "analyzed"
                and routine.risk.level == "none",
                "campaign_stays": routine.scenario_pack_id == "card_promoter",
            },
            "reply": routine.response_text,
            "latency_ms": routine.trace.latency_ms.model_dump(),
        }
    )
    report = {
        "rows": rows,
        "risk_inputs": captured,
        "passed": all(all(row["checks"].values()) for row in rows),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {"passed": report["passed"], "checks": [row["checks"] for row in rows]},
            indent=2,
        )
    )
    return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(0 if asyncio.run(smoke(parser.parse_args().output)) else 1)
