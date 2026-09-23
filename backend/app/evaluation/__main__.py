import argparse
import asyncio
import hashlib
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.agent.errors import RouterError
from app.agent.prompts import build_router_instructions
from app.agent.router import RouterAgent
from app.core.config import Settings
from app.data.loaders import DataLoadError, load_starter_kit
from app.evaluation.runner import (
    EvaluationRunError,
    evaluate_predictions,
    preflight_output_paths,
    run_evaluation,
    write_evaluation,
)
from app.scenarios.catalog import ScenarioCatalog


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def bounded_concurrency(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 8:
        raise argparse.ArgumentTypeError("must be between 1 and 8")
    return number


def bounded_interval(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 60:
        raise argparse.ArgumentTypeError("must be a finite number between 0 and 60")
    return number


def print_progress(utterance_id: str, completed: int, total: int) -> None:
    print(f"Progress: {completed}/{total} completed ({utterance_id})", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Validate starter-kit data or evaluate Router v1")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-data", action="store_true")
    mode.add_argument("--run", action="store_true", help="Call the configured model once per input")
    parser.add_argument("--output", type=Path, help="New predictions JSON; never overwrites a run")
    parser.add_argument("--limit", type=positive_int, help="Evaluate only the first N utterances")
    parser.add_argument(
        "--concurrency", type=bounded_concurrency, help="Concurrent routing calls, 1–8 (default: 1)"
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Record RouterError failures as empty predictions and continue; no retries",
    )
    parser.add_argument(
        "--min-interval-seconds",
        type=bounded_interval,
        help="Minimum time between routing call starts, 0–60 seconds (default: 0)",
    )
    args = parser.parse_args(argv)
    if args.check_data and (
        args.continue_on_error
        or any(
            item is not None
            for item in (args.output, args.limit, args.concurrency, args.min_interval_seconds)
        )
    ):
        parser.error(
            "Evaluation output, limit, concurrency, error and pacing options require --run"
        )
    if args.run and args.output is None:
        parser.error("--run requires --output")

    settings = Settings()
    if args.run:
        missing = []
        if (
            settings.openai_api_key is None
            or not settings.openai_api_key.get_secret_value().strip()
        ):
            missing.append("OPENAI_API_KEY")
        if not settings.openai_router_model or not settings.openai_router_model.strip():
            missing.append("OPENAI_ROUTER_MODEL")
        if missing:
            parser.error(f"Configure {', '.join(missing)} before running live routing evaluation")
        try:
            _, report_path, details_path = preflight_output_paths(args.output)
        except OSError as exc:
            parser.error(str(exc))

    try:
        kit = load_starter_kit(settings.starter_kit_path)
    except DataLoadError as exc:
        parser.error(str(exc))
    if args.check_data:
        print(
            f"Validated {len(kit.scenarios.scenarios)} scenarios, "
            f"{len(kit.scenarios.system_intents)} system intents, "
            f"{len(kit.actions.actions)} actions, "
            f"{len(kit.dev_utterances.utterances)} dev utterances. "
            "Router evaluation was not run."
        )
        return

    dataset = kit.dev_utterances.model_copy(
        update={"utterances": kit.dev_utterances.utterances[: args.limit]}
    )
    try:
        concurrency = args.concurrency or 1
        min_interval_seconds = args.min_interval_seconds or 0
        catalog = ScenarioCatalog(kit.scenarios)
        instructions_sha256 = hashlib.sha256(
            build_router_instructions(catalog, kit.slots).encode("utf-8")
        ).hexdigest()
        dataset_sha256 = hashlib.sha256(
            (settings.starter_kit_path / "dev_utterances.json").read_bytes()
        ).hexdigest()
        started_at = datetime.now(UTC).isoformat()
        router = RouterAgent(catalog, settings=settings, slots=kit.slots)
        predictions, details = asyncio.run(
            run_evaluation(
                dataset,
                router,
                concurrency=concurrency,
                min_interval_seconds=min_interval_seconds,
                continue_on_error=args.continue_on_error,
                progress=print_progress,
            )
        )
        details.update(
            {
                "model": settings.openai_router_model,
                "instructions_sha256": instructions_sha256,
                "dataset_sha256": dataset_sha256,
                "dataset_version": dataset.meta.version,
                "started_at_utc": started_at,
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "evaluated": len(dataset.utterances),
                "dataset_total": len(kit.dev_utterances.utterances),
            }
        )
        scores = evaluate_predictions(
            predictions, dataset, settings.starter_kit_path / "evaluate.py"
        )
        provider_warning = (
            "WARNING: Provider failures reduce reported accuracy "
            "independently of routing quality.\n"
            if details["provider_failure_count"]
            else ""
        )
        report = (
            "Router v1 live evaluation\n"
            f"UTC: {started_at}\n"
            f"Model: {settings.openai_router_model}\n"
            f"Instructions SHA256: {instructions_sha256}\n"
            f"Dataset SHA256: {dataset_sha256}\n"
            f"Dataset version: {dataset.meta.version}\n"
            f"Evaluated: {len(dataset.utterances)}/"
            f"{len(kit.dev_utterances.utterances)} utterances\n"
            f"Concurrency: {concurrency}\n"
            f"Minimum call-start interval (seconds): {min_interval_seconds}\n"
            f"Continue on routing error: {args.continue_on_error}\n"
            f"Routing failures: {details['failure_count']}\n"
            f"Provider failures (including timeouts): {details['provider_failure_count']}\n"
            f"Invalid output failures: {details['invalid_output_count']}\n"
            f"Other routing failures: {details['other_failure_count']}\n"
            f"{provider_warning}"
            f"Total routing wall latency (ms): {details['total_latency_ms']}\n"
            "One fresh dialogue state and one routing call per utterance; no label inputs.\n"
            "Routing failures have null decisions and empty predictions; they count as errors.\n"
            "Metrics below are from the unchanged starter-kit evaluate.py.\n\n"
            f"{scores}"
        )
        write_evaluation(predictions, details, report, args.output)
    except EvaluationRunError as exc:
        detail = (
            f" {exc.__cause__.code}: {exc.__cause__.message}"
            if isinstance(exc.__cause__, RouterError)
            else " Check model credentials, provider availability and router validation."
        )
        parser.error(f"{exc}{detail}")
    except RouterError as exc:
        parser.error(f"{exc.code}: {exc.message}")
    except (OSError, subprocess.SubprocessError) as exc:
        parser.error(f"Could not score or save evaluation: {type(exc).__name__}")
    print(report, end="")
    print(f"Predictions: {args.output}\nReport: {report_path}\nDetails: {details_path}")


if __name__ == "__main__":
    main()
