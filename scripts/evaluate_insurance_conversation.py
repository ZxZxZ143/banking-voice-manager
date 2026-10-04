"""Live dialogue eval, separate from canonical routing. No retries or subjective style judge."""

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
from app.packs.insurance_manager.composer import normalized_question
from app.packs.insurance_manager.conversation_flow import is_relationship_question
from app.packs.insurance_manager.privacy import redact_text


def completion_checks(spec, turn):
    """Gold expectations stay in evaluation only; never enter Router/Composer input."""
    meta = turn.state.conversation
    checks = {}
    if "relationship" in spec:
        checks["context_relationship_retention"] = meta.policy_relationship == spec["relationship"]
    if "wrap_up" in spec:
        checks["wrap_up_correctness"] = (meta.phase == "wrap_up") == spec["wrap_up"]
    if spec.get("resolved_acknowledgement"):
        checks["resolved_acknowledgement_correctness"] = (
            meta.phase == "wrap_up"
            and meta.last_assistant_act == "ask_followup"
            and meta.expected_answer_type == "more_questions"
            and meta.repair_attempts == 0
            and not turn.routing.scenarios
            and not turn.trace.scenarios
            and turn.conversation_status == "awaiting_user"
        )
    if spec.get("no_more_questions"):
        checks["conversation_end_after_no_more_questions"] = turn.conversation_status == "ended"
    if "allow_relationship_question" in spec:
        checks["no_unnecessary_new_existing_question"] = spec[
            "allow_relationship_question"
        ] or not is_relationship_question(turn.response_text)
    if spec.get("open_followup"):
        checks["open_followup_correctness"] = (
            meta.last_assistant_act == "ask_followup"
            and meta.expected_answer_type == "problem_description"
            and not is_relationship_question(turn.response_text)
        )
    if spec.get("scenario"):
        checks["direct_request_routing"] = (
            turn.trace.completed_scenario or turn.state.active_scenario
        ) == spec["scenario"]
    return checks


async def evaluate(output: Path, only=(), source=None):
    if output.exists():
        raise FileExistsError("Never overwrite evaluation evidence")
    source = source or (
        Path(__file__).resolve().parents[1] / "data/insurance_conversation/eval_cases.json"
    )
    dataset = json.loads(source.read_text(encoding="utf-8"))
    services = build_services(Settings(demo_test_phone=None))
    counts, rows, latencies = defaultdict(lambda: [0, 0]), [], defaultdict(list)
    composer = services.insurance.processor.composer
    actual_run = composer.agent.run
    observed = {}

    async def observe(payload):
        observed.clear()
        observed.update(payload)
        return await actual_run(payload)

    composer.agent.run = observe

    def measure(name, passed):
        counts[name][1] += 1
        counts[name][0] += bool(passed)
        return bool(passed)

    def save():
        data = {
            "started_at": started,
            "dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "cases": rows,
            "metrics": dict(counts),
            "unnecessary_new_existing_question_count": (
                counts["no_unnecessary_new_existing_question"][1]
                - counts["no_unnecessary_new_existing_question"][0]
            ),
            "latency_ms": dict(latencies),
            "model": services.insurance.processor.router.settings.openai_router_model,
            "response_model": composer.agent.settings.openai_router_model,
            "style_judge": "not used; metrics are deterministic contract checks",
        }
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    started = datetime.now(UTC).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.touch(exist_ok=False)
    for case in dataset["cases"]:
        if only and case["id"] not in only:
            continue
        session = "conversation-eval-" + case["id"]
        row = {"id": case["id"], "language": case["lang"], "turns": []}
        rows.append(row)
        opening = await services.messages.process(
            session, "", "insurance_manager", start_scenario=True
        )
        # A fresh opener is Russian by default, language follows the first customer turn.
        last_question = opening.state.conversation.last_question
        for spec in case["turns"]:
            await asyncio.sleep(1)
            observed.clear()
            try:
                turn = await services.messages.process(session, spec["text"])
            except RouterError as exc:
                row["error"] = exc.code
                measure("provider_success", False)
                save()
                break
            meta, trace = turn.state.conversation, turn.trace
            checks = {}
            for name, passed in completion_checks(spec, turn).items():
                checks[name] = measure(name, passed)
            checks["provider_success"] = measure(
                "provider_success",
                trace.routing_error not in {"router_provider_error", "router_timeout"}
                and trace.composer_error
                not in {"router_provider_error", "router_timeout", "composer_timeout"},
            )
            premature = turn.conversation_status in {
                "handoff",
                "ended",
            } and not spec.get("terminal")
            if not spec.get("terminal"):
                checks["no_premature_handoff"] = measure("no_premature_handoff", not premature)
            if spec.get("terminal"):
                checks["terminal_correctness"] = measure(
                    "terminal_correctness", turn.conversation_status == spec["terminal"]
                )
            if spec.get("progress"):
                checks["progress_reset"] = measure(
                    "progress_reset",
                    meta.repair_attempts == 0
                    and turn.state.unclear_count == turn.state.consecutive_low_confidence == 0,
                )
                checks["no_repeated_question"] = measure(
                    "no_repeated_question",
                    not meta.last_question
                    or normalized_question(meta.last_question)
                    != normalized_question(last_question),
                )
            if spec.get("collected"):
                own = (
                    services.dialogs.get_conversation(session)
                    .scenario_contexts["insurance_manager"]
                    .state
                )
                checks["expected_slot_continuation"] = measure(
                    "expected_slot_continuation",
                    bool(own.slots.get(spec["collected"]))
                    or bool(
                        turn.trace.completed_scenario and turn.routing.slots.get(spec["collected"])
                    ),
                )
            if spec.get("slot"):
                checks["next_slot"] = measure("next_slot", meta.expected_slot == spec["slot"])
            if spec.get("acts"):
                checks["act_progression"] = measure(
                    "act_progression", meta.last_assistant_act in spec["acts"]
                )
            if spec.get("facts"):
                offered_facts = [
                    observed.get("grounded_facts"),
                    *observed.get("grounded_variants", {}).values(),
                ]
                checks["grounded_fact_preservation"] = measure(
                    "grounded_fact_preservation",
                    any(fact and fact in turn.response_text for fact in offered_facts)
                    and bool(trace.source_keys),
                )
            expected_language = spec.get("language", case["lang"])
            lang_ok = (
                turn.state.response_language in {"ru", "kk"}
                if expected_language == "mixed"
                else turn.state.response_language == expected_language
            )
            if expected_language == "kk":
                lang_ok = lang_ok and bool(re.search(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]", turn.response_text))
            checks["language_correctness"] = measure("language_correctness", lang_ok)
            checks["composer_validity"] = measure("composer_validity", not trace.composer_error)
            row["turns"].append(
                {
                    "utterance": redact_text(spec["text"]),
                    "response": turn.response_text,
                    "trace": trace.model_dump(mode="json"),
                    "checks": checks,
                }
            )
            for name in ("router", "business", "composer", "total"):
                value = getattr(trace.latency_ms, name)
                if value is not None:
                    latencies[name].append(value)
            last_question = meta.last_question
            save()
            if turn.conversation_status in {"handoff", "ended"}:
                break
        row["passed"] = (
            len(row["turns"]) == len(case["turns"])
            and not row.get("error")
            and all(all(t["checks"].values()) for t in row["turns"])
        )
        save()
        print(f"{case['id']}: {'PASS' if row['passed'] else 'FAIL'}", flush=True)
    print(json.dumps(dict(counts), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    asyncio.run(evaluate(args.output, args.case, args.dataset))
