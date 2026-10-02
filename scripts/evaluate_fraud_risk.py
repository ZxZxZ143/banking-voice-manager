"""Live Stage 4 evidence: labels never enter production RiskInput or pack context."""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.core.services import build_services
from app.risk.models import RiskContext


def expected_action(level):
    return {
        "none": "none",
        "low": "show_security_guidance",
        "medium": "show_security_guidance",
        "high": "security_review",
        "critical": "urgent_security_review",
    }[level]


async def evaluate(output):
    if output.exists():
        raise FileExistsError("Never overwrite live evidence")
    settings = Settings(demo_test_phone=None)
    source = settings.security_policy_path.parent / "eval_cases.json"
    dataset = json.loads(source.read_text(encoding="utf-8"))
    built = build_services(settings)
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "model": settings.openai_router_model,
        "dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "risk": [],
        "fraud": [],
        "metrics": {},
        "latency_ms": {"risk_precheck": [], "risk_agent": [], "fraud_total": []},
    }
    counts = Counter()

    def measure(name, ok):
        counts[name + "_total"] += 1
        counts[name + "_passed"] += int(ok)
        return bool(ok)

    def save():
        report["metrics"] = dict(counts)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.touch(exist_ok=False)
    for case in dataset["cases"]:
        spec = case["turns"][0]
        run = await built.messages.risk.analyze(
            spec["text"], active_assistant=case["mode"], context=RiskContext()
        )
        risk = run.assessment
        valid = risk is None or risk.analysis_status == "analyzed"
        relevant = bool(risk and risk.risk_relevant)
        if valid:
            counts[
                ("tp" if relevant else "fn")
                if spec["risk"]
                else ("fp" if relevant else "tn")
            ] += 1
        else:
            counts[
                "positive_unavailable" if spec["risk"] else "negative_unavailable"
            ] += 1
        counts["high_risk_false_positive"] += int(
            not spec["risk"] and risk is not None and risk.level in ("high", "critical")
        )
        expected, actual = (
            set(spec["signals"]),
            {s.value for s in risk.signals} if risk else set(),
        )
        counts["signal_tp"] += len(expected & actual)
        counts["signal_fp"] += len(actual - expected)
        counts["signal_fn"] += len(expected - actual)
        row = {
            "id": case["id"],
            "gate_called_model": run.agent_ms is not None,
            "assessment": risk.model_dump(mode="json") if risk else None,
            "checks": {
                "structured": measure("risk_structured", valid),
                "relevance": measure(
                    "risk_relevance", valid and relevant == spec["risk"]
                ),
                "signals": measure("risk_signals", valid and actual == expected),
                "level": measure(
                    "risk_level",
                    valid and (risk.level if risk else "none") == spec["level"],
                ),
                "action": measure(
                    "risk_action",
                    valid
                    and (risk.recommended_action if risk else "none")
                    == expected_action(spec["level"]),
                ),
                "language": run.agent_ms is None
                or measure(
                    "risk_language",
                    run.decision is None
                    and risk is None
                    or run.decision is not None
                    and run.decision.response_language == case["lang"],
                ),
            },
        }
        report["risk"].append(row)
        report["latency_ms"]["risk_precheck"].append(run.precheck_ms)
        if run.agent_ms is not None:
            report["latency_ms"]["risk_agent"].append(run.agent_ms)
        session = "stage4-fraud-" + case["id"]
        await built.messages.process(session, "", "fraud_security", start_scenario=True)
        fraud_row = {"id": case["id"], "turns": [], "passed": True}
        report["fraud"].append(fraud_row)
        for index, turn_spec in enumerate(case["turns"]):
            turn = await built.messages.process(session, turn_spec["text"])
            decision = turn.routing
            checks = {
                "structured": measure(
                    "fraud_structured", turn.risk.analysis_status == "analyzed"
                ),
                "intent": measure(
                    "fraud_intent", decision.intent == turn_spec["intent"]
                ),
                "language": measure(
                    "fraud_language", decision.response_language == case["lang"]
                ),
                "risk": measure(
                    "fraud_risk", turn.risk.risk_relevant == turn_spec["risk"]
                ),
                "fixed_pack": measure(
                    "fraud_fixed_pack",
                    turn.scenario_pack_id == "fraud_security"
                    and turn.trace.pack_switch is None,
                ),
                "status": measure(
                    "fraud_status",
                    turn.conversation_status == turn_spec.get("status", "active"),
                ),
                "guidance_grounded": measure(
                    "fraud_guidance_grounded",
                    all(
                        built.messages.risk.policy.text(k, decision.response_language)
                        in turn.response_text
                        for k in turn.risk.guidance_shown
                    ),
                ),
                "one_question": measure(
                    "fraud_one_question", turn.response_text.count("?") <= 1
                ),
            }
            if "question" in turn_spec:
                checks["question"] = measure(
                    "fraud_question",
                    turn.state.pending_question == turn_spec["question"],
                )
            fraud_row["turns"].append(
                {
                    "turn": index + 1,
                    "response": turn.response_text,
                    "decision": decision.model_dump(mode="json"),
                    "risk": turn.risk.model_dump(mode="json"),
                    "result": turn.scenario_result.model_dump(mode="json"),
                    "checks": checks,
                }
            )
            fraud_row["passed"] &= all(checks.values())
            report["latency_ms"]["fraud_total"].append(turn.trace.latency_ms.total)
            if turn.conversation_status in ("handoff", "ended") and index + 1 < len(
                case["turns"]
            ):
                fraud_row["passed"] = False
                fraud_row["premature_terminal"] = True
                break
        measure(
            "fraud_complete_case",
            fraud_row["passed"] and len(fraud_row["turns"]) == len(case["turns"]),
        )
        save()
        print(
            f"{case['id']}: risk={'PASS' if all(row['checks'].values()) else 'FAIL'} fraud={'PASS' if fraud_row['passed'] else 'FAIL'}",
            flush=True,
        )
    report["completed_at"] = datetime.now(UTC).isoformat()
    save()
    print(json.dumps(report["metrics"], indent=2), flush=True)


def rescore(source, output):
    """Rescore existing calls; unavailable is unknown, never a successful negative."""
    if output.exists():
        raise FileExistsError("Never overwrite evidence")
    report = json.loads(source.read_text(encoding="utf-8"))
    settings = Settings()
    dataset = json.loads(
        (settings.security_policy_path.parent / "eval_cases.json").read_text(
            encoding="utf-8"
        )
    )
    specs = {case["id"]: case["turns"][0] for case in dataset["cases"]}
    matrix = Counter(
        tp=0, fp=0, fn=0, tn=0, positive_unavailable=0, negative_unavailable=0
    )
    scores = Counter()

    def measure(name, passed):
        scores[name + "_total"] += 1
        scores[name + "_passed"] += int(passed)

    for row in report["risk"]:
        assessment, spec = row["assessment"], specs[row["id"]]
        valid = assessment is None or assessment["analysis_status"] == "analyzed"
        relevant = bool(assessment and assessment["risk_relevant"])
        if valid:
            matrix[
                ("tp" if relevant else "fn")
                if spec["risk"]
                else ("fp" if relevant else "tn")
            ] += 1
        else:
            matrix[
                "positive_unavailable" if spec["risk"] else "negative_unavailable"
            ] += 1
        for name in ("relevance", "signals", "level", "action", "structured"):
            passed = row["checks"][name]
            if name == "action":
                passed = (
                    assessment["recommended_action"] if assessment else "none"
                ) == expected_action(spec["level"])
            measure("risk_" + name, valid and passed)
        if row["gate_called_model"]:
            measure("risk_language", valid and row["checks"]["language"])
    report["corrected_risk_metrics"] = dict(scores)
    report["valid_risk_confusion"] = dict(matrix)
    report["scoring_note"] = (
        "Original call evidence retained. Unavailable is excluded from valid confusion and counts as failed end-to-end assessment. Language measured only on model-called cases. No additional model calls."
    )
    report["rescored_from"] = source.name
    with output.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    print(json.dumps({"metrics": dict(scores), "confusion": dict(matrix)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rescore", type=Path)
    args = parser.parse_args()
    if args.rescore:
        rescore(args.rescore, args.output)
    else:
        asyncio.run(evaluate(args.output))
