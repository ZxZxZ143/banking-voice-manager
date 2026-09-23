"""Compare complete saved router runs offline, using the official evaluator's formulas.

Usage: python scripts/compare_router_evals.py before.details.json after.details.json
No model calls are made. Provider messages/bodies are never read or printed.
"""

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

EXPECTED_SIZE = 104
SAFE_ERROR_CODES = {
    "router_not_configured",
    "router_timeout",
    "router_provider_error",
    "router_invalid_output",
}
GROUPS = [
    ("overall", None, None),
    ("ru", "lang", "ru"),
    ("kk", "lang", "kk"),
    ("mixed", "lang", "mixed"),
    ("single", "type", "single"),
    ("multi", "type", "multi_intent"),
    ("unclear", "type", "unclear"),
    ("outscope", "type", "out_of_scope"),
]


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path.name}")
    return value


def scenario_ids(values: object) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValueError("Expected a nonempty scenario-ID list")
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9_]{1,64}", value)
        for value in values
    ):
        raise ValueError("Invalid scenario ID in a saved decision or dataset label")
    if len(set(values)) != len(values):
        raise ValueError("Duplicate scenario IDs in a saved decision or dataset label")
    return values


def load_dataset(path: Path) -> tuple[list[dict], str]:
    data = read_object(path)
    utterances = data.get("utterances")
    if not isinstance(utterances, list) or len(utterances) != EXPECTED_SIZE:
        raise ValueError(
            f"Canonical dataset must contain exactly {EXPECTED_SIZE} utterances"
        )
    ids = set()
    for item in utterances:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise TypeError("Dataset has an invalid utterance record")
        if item["id"] in ids:
            raise ValueError("Dataset contains duplicate utterance IDs")
        ids.add(item["id"])
        scenario_ids(item.get("expected"))
        if item.get("lang") not in {"ru", "kk", "mixed"}:
            raise ValueError("Dataset has an unsupported language label")
        if item.get("type") not in {
            "single",
            "multi_intent",
            "unclear",
            "out_of_scope",
        }:
            raise ValueError("Dataset has an unsupported utterance type")
    return utterances, hashlib.sha256(path.read_bytes()).hexdigest()


def validate_run(
    details: dict, dataset: list[dict], dataset_hash: str
) -> dict[str, dict]:
    if details.get("schema_version") != 1:
        raise ValueError("Unsupported evaluation details schema")
    if details.get("dataset_sha256") != dataset_hash:
        raise ValueError("Saved run dataset hash does not match the canonical dataset")
    if (
        details.get("evaluated") != EXPECTED_SIZE
        or details.get("dataset_total") != EXPECTED_SIZE
    ):
        raise ValueError(
            f"Saved run must explicitly report all {EXPECTED_SIZE} inputs evaluated"
        )
    captures = details.get("utterances")
    if not isinstance(captures, list) or len(captures) != EXPECTED_SIZE:
        raise ValueError(
            f"Saved run must contain exactly {EXPECTED_SIZE} capture records"
        )
    known_ids = {item["id"] for item in dataset}
    by_id = {}
    for capture in captures:
        if not isinstance(capture, dict):
            raise TypeError("Saved run contains an invalid capture record")
        utterance_id = capture.get("utterance_id")
        if not isinstance(utterance_id, str) or utterance_id not in known_ids:
            raise ValueError("Saved run contains an unknown utterance ID")
        if utterance_id in by_id:
            raise ValueError("Saved run contains duplicate utterance IDs")
        latency = capture.get("router_latency_ms")
        if (
            type(latency) not in (int, float)
            or not math.isfinite(latency)
            or latency < 0
        ):
            raise ValueError("Saved run contains a missing or invalid routing latency")
        if "decision" not in capture:
            raise ValueError("Saved capture has no decision field")
        decision = capture["decision"]
        if decision is None:
            if not isinstance(capture.get("error"), dict):
                raise ValueError(
                    "A null decision must include a structured routing error"
                )
        else:
            if not isinstance(decision, dict) or not isinstance(
                decision.get("scenarios"), list
            ):
                raise ValueError("Saved capture has an invalid decision")
            if any(not isinstance(item, dict) for item in decision["scenarios"]):
                raise ValueError("Saved decision has an invalid scenario selection")
            scenario_ids([item.get("scenario_id") for item in decision["scenarios"]])
            if decision.get("language") not in {"ru", "kk", "mixed"}:
                raise ValueError("Saved decision has an invalid language")
            if decision.get("response_language") not in {None, "ru", "kk"}:
                raise ValueError("Saved decision has an invalid response language")
        by_id[utterance_id] = capture
    if set(by_id) != known_ids:
        raise ValueError("Saved run is missing canonical utterance IDs")
    actual_failures = sum(item["decision"] is None for item in captures)
    if details.get("failure_count") != actual_failures:
        raise ValueError("Saved run failure count does not match its capture records")
    return by_id


def predictions(capture: dict) -> list[str]:
    decision = capture["decision"]
    return [item["scenario_id"] for item in decision["scenarios"]] if decision else []


def metric_counts(rows: list[dict], run: dict[str, dict]) -> tuple[int, int, int]:
    # Identical primary/full-match definitions to data/starter_kit/evaluate.py.
    primary = full = 0
    for item in rows:
        got = predictions(run[item["id"]])
        primary += bool(got) and got[0] == item["expected"][0]
        full += set(got) == set(item["expected"])
    return primary, full, len(rows)


def ratio(hit: int, total: int) -> str:
    return f"{hit}/{total} ({100 * hit / total:.3f}%)" if total else "n/a (0 inputs)"


def failures(run: dict[str, dict]) -> Counter:
    counts = Counter()
    for capture in run.values():
        if capture["decision"] is not None:
            continue
        error = capture["error"]
        code = error.get("code")
        code = (
            code
            if isinstance(code, str) and code in SAFE_ERROR_CODES
            else "unknown_router_error"
        )
        status = error.get("http_status")
        status = (
            str(status)
            if type(status) is int and 400 <= status <= 599
            else "unavailable"
        )
        counts[(code, status)] += 1
    return counts


def latency_summary(run: dict[str, dict]) -> str:
    values = sorted(
        item["router_latency_ms"]
        for item in run.values()
        if item["decision"] is not None
    )
    if not values:
        return "n=0, median=n/a, p95=n/a"
    p95 = values[math.ceil(0.95 * len(values)) - 1]
    return (
        f"n={len(values)}, median={statistics.median(values):.3f} ms, p95={p95:.3f} ms"
    )


def compare(
    dataset: list[dict], before: dict[str, dict], after: dict[str, dict]
) -> None:
    print("Complete offline comparison: 104/104 distinct canonical inputs in each run.")
    print(
        "Accuracy includes failed calls as empty predictions; formulas match evaluate.py."
    )
    print(f"{'Group':<12} {'Metric':<9} {'Before':>23} {'After':>23}")
    for name, field, value in GROUPS:
        rows = [item for item in dataset if field is None or item[field] == value]
        left = metric_counts(rows, before)
        right = metric_counts(rows, after)
        for index, metric in enumerate(("primary", "full")):
            print(
                f"{name:<12} {metric:<9} {ratio(left[index], left[2]):>23} "
                f"{ratio(right[index], right[2]):>23}"
            )

    multi = [item for item in dataset if item["type"] == "multi_intent"]
    denominator = sum(len(item["expected"]) for item in multi)
    recalls = [
        sum(
            len(set(item["expected"]) & set(predictions(run[item["id"]])))
            for item in multi
        )
        for run in (before, after)
    ]
    print(
        f"\nMulti-intent recall: before={ratio(recalls[0], denominator)}; "
        f"after={ratio(recalls[1], denominator)}"
    )

    left_failures, right_failures = failures(before), failures(after)
    print(
        f"\nRouting failures: before={sum(left_failures.values())}; "
        f"after={sum(right_failures.values())}"
    )
    for code, status in sorted(left_failures.keys() | right_failures.keys()):
        key = code, status
        print(
            f"  {code}, HTTP {status}: before={left_failures[key]}; after={right_failures[key]}"
        )
    print(
        "Provider failures and invalid output reduce accuracy independently of semantic mistakes."
    )

    print(
        "\nValid routing latency (excludes failed calls and pacing; p95 uses nearest rank):"
    )
    print(f"  Before: {latency_summary(before)}")
    print(f"  After:  {latency_summary(after)}")
    mono = [item for item in dataset if item["lang"] in {"ru", "kk"}]
    print(
        "\nLanguage metrics: monolingual gold only; correctness denominator is valid decisions."
    )
    for name, run in (("Before", before), ("After", after)):
        valid = [item for item in mono if run[item["id"]]["decision"] is not None]
        detection = sum(
            run[item["id"]]["decision"]["language"] == item["lang"] for item in valid
        )
        reply = sum(
            run[item["id"]]["decision"].get("response_language") == item["lang"]
            for item in valid
        )
        print(
            f"  {name}: coverage={ratio(len(valid), len(mono))}; "
            f"detection={ratio(detection, len(valid))}; reply={ratio(reply, len(valid))}"
        )

    remaining = []
    for item in dataset:
        capture = after[item["id"]]
        if capture["decision"] is None:
            continue
        got = predictions(capture)
        if got[0] != item["expected"][0] or set(got) != set(item["expected"]):
            remaining.append((item["id"], item["expected"], got))
    print(
        f"\nRemaining semantic errors (after, valid decisions; primary or set mismatch): {len(remaining)}"
    )
    for utterance_id, expected, got in remaining:
        print(f"  {utterance_id}: expected={expected}; predicted={got}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data/starter_kit/dev_utterances.json",
    )
    args = parser.parse_args(argv)
    try:
        dataset, dataset_hash = load_dataset(args.dataset)
        before = validate_run(read_object(args.before), dataset, dataset_hash)
        after = validate_run(read_object(args.after), dataset, dataset_hash)
        compare(dataset, before, after)
    except (OSError, ValueError, TypeError, KeyError) as error:
        # Validation messages are locally generated; never print arbitrary stored error fields.
        if isinstance(error, json.JSONDecodeError):
            parser.error("Invalid JSON in an input file")
        if type(error) is ValueError:
            parser.error(str(error))
        parser.error(f"Unable to compare saved evaluations: {type(error).__name__}")


if __name__ == "__main__":
    main()
