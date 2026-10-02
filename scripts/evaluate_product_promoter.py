"""Separate live product/selector evaluation. Labels are consumed only after the model call."""

import argparse
import asyncio
import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.agent.errors import RouterError
from app.core.config import Settings
from app.core.services import build_services
from app.packs.contracts import GlobalConversationContext
from app.packs.product_promoter.models import SalesLeadResult


async def evaluate(output: Path):
    if output.exists():
        raise FileExistsError("Never overwrite evaluation evidence")
    settings = Settings()
    services = build_services(settings)
    pack = services.registry.get("product_promoter")
    source = settings.product_catalog_path.parent / "eval_cases.json"
    dataset = json.loads(source.read_text(encoding="utf-8"))
    rows = []
    counts = defaultdict(lambda: [0, 0])

    def measure(name, passed):
        counts[name][1] += 1
        counts[name][0] += int(passed)

    for case in dataset["cases"]:
        row = {"id": case["id"], "language": case["lang"], "passed": False, "turns": []}
        rows.append(row)
        case_passed = True
        if "selector" in case:
            spec = case["selector"]
            try:
                turn = await services.messages.process(
                    case["id"], spec["text"], spec["current"]
                )
                case_passed = (
                    turn.scenario_pack_id == spec["current"]
                    and turn.trace.pack_switch is None
                )
                row["policy"] = "manual_selection_only"
                row["pack"] = turn.scenario_pack_id
                measure("manual_only_policy", case_passed)
            except RouterError as exc:
                row["error"] = exc.code
                case_passed = False
                measure("manual_only_policy", False)
            measure("no_automatic_switch", case_passed)
        else:
            context = pack.new_context()
            for index, expected in enumerate(case["turns"]):
                try:
                    # Only utterance, own context and minimal global context are passed.
                    turn = await pack.handle_turn(
                        expected["text"],
                        GlobalConversationContext(
                            session_id=case["id"],
                            turn_number=index,
                            language=case["lang"] if index else None,
                        ),
                        context.model_copy(deep=True),
                    )
                    context = turn.context
                    SalesLeadResult.model_validate(turn.result.model_dump())
                    valid = turn.trace.routing_error is None
                    correct_intent = (
                        turn.routing.intent in expected["intents"] and valid
                    )
                    selected = turn.public_state.products
                    allowed_numbers = set()
                    for product in selected:
                        source_product = next(
                            p for p in pack.knowledge.products if p.id == product.id
                        )
                        if product.model_dump() != source_product.model_dump():
                            raise AssertionError(
                                "Displayed product differs from source"
                            )
                        numeric_values = [
                            float(v)
                            for v in re.findall(
                                r"\d+(?:\.\d+)?",
                                json.dumps(
                                    source_product.model_dump(), ensure_ascii=False
                                ),
                            )
                        ]
                        for value in numeric_values:
                            allowed_numbers.add(value)
                            if value >= 1000 and value % 1000 == 0:
                                allowed_numbers.add(value / 1000)
                            if value >= 1e6 and value % 1e6 == 0:
                                allowed_numbers.add(value / 1e6)
                    response_numbers = {
                        float(v.replace(",", "."))
                        for v in re.findall(r"\d+(?:[.,]\d+)?", turn.response_text)
                    }
                    grounded = not selected or response_numbers <= allowed_numbers
                    expected_language = expected.get(
                        "reply_language", case.get("reply_language", case["lang"])
                    )
                    language = turn.routing.response_language == expected_language
                    checks = {
                        "intent": correct_intent,
                        "structured_output": valid,
                        "grounding": grounded,
                        "reply_language": language,
                    }
                    if "question" in expected:
                        checks["question"] = (
                            context.last_question == expected["question"]
                        )
                    if "preferences" in expected:
                        checks["preferences"] = all(
                            getattr(context.preferences, k) == v
                            for k, v in expected["preferences"].items()
                        )
                    if "products" in expected:
                        checks["products"] = [
                            p.id for p in turn.public_state.products
                        ] == expected["products"]
                    if "compared" in expected:
                        checks["compared"] = set(turn.result.compared_products) == set(
                            expected["compared"]
                        )
                    for field, key in (
                        ("outcome", "outcome"),
                        ("selected", "selected_product_id"),
                        ("next_action", "next_action"),
                        ("status", "status"),
                    ):
                        if field in expected:
                            checks[field] = getattr(turn.result, key) == expected[field]
                    passed = all(checks.values())
                    row["turns"].append(
                        {
                            "text": expected["text"],
                            "checks": checks,
                            "routing": turn.routing.model_dump(),
                            "result": turn.result.model_dump(),
                            "response_text": turn.response_text,
                            "latency_ms": turn.trace.latency_ms.model_dump(),
                        }
                    )
                    for name in (
                        "intent",
                        "structured_output",
                        "grounding",
                        "reply_language",
                    ):
                        measure(name, checks[name])
                    measure(f"language_{case['lang']}", language)
                    if index:
                        measure("continuation", passed)
                    case_passed &= passed
                except RouterError as exc:
                    row["turns"].append({"text": expected["text"], "error": exc.code})
                    for name in (
                        "intent",
                        "structured_output",
                        "grounding",
                        "reply_language",
                    ):
                        measure(name, False)
                    if index:
                        measure("continuation", False)
                    case_passed = False
        row["passed"] = bool(case_passed)
        measure("flow", case_passed)
        print(f"{case['id']}: {'PASS' if case_passed else 'FAIL'}", flush=True)
    report = {
        "live": True,
        "started_model": settings.openai_router_model,
        "temperature": settings.router_temperature,
        "created_at": datetime.now(UTC).isoformat(),
        "prompt_sha256": hashlib.sha256(pack.prompt.encode()).hexdigest(),
        "data_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "catalog_sha256": hashlib.sha256(
            settings.product_catalog_path.read_bytes()
        ).hexdigest(),
        "metrics": {
            name: {
                "passed": correct,
                "total": total,
                "percent": round(100 * correct / total, 2),
            }
            for name, (correct, total) in counts.items()
        },
        "cases": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    print(json.dumps(report["metrics"], indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(evaluate(parser.parse_args().output))
