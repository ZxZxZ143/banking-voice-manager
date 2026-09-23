import asyncio
import json
import math
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from time import monotonic, perf_counter

from app.agent.errors import ROUTER_VALIDATION_REASONS, RouterError, RouterOutputError
from app.agent.router import Router
from app.agent.schemas import RouterDecision
from app.data.models import DevDataset
from app.dialog.models import DialogState


class EvaluationRunError(RuntimeError):
    """A stopped batch, with progress but no provider response or secret in the message."""

    def __init__(self, utterance_id: str, completed: int, total: int) -> None:
        self.utterance_id = utterance_id
        self.completed = completed
        self.total = total
        super().__init__(
            f"Routing failed at {utterance_id} after {completed}/{total} completed utterances. "
            "No predictions or accuracy report were saved."
        )


def safe_router_error(error: RouterError) -> dict:
    """Capture allowlisted provider metadata without serializing a provider exception/body."""
    details = {"code": error.code, "message": error.message}
    if isinstance(error, RouterOutputError):
        reason = error.validation_reason
        if isinstance(reason, str) and reason in ROUTER_VALIDATION_REASONS:
            details["validation_reason"] = reason
    cause = error.__cause__
    status = getattr(cause, "status_code", None)
    if type(status) is int and 400 <= status <= 599:
        details["http_status"] = status
    code = getattr(cause, "code", None)
    if isinstance(code, str) and code in {"rate_limit_exceeded", "insufficient_quota"}:
        details["provider_code"] = code
    response = getattr(cause, "response", None)
    headers = getattr(response, "headers", None)
    retry_after = headers.get("retry-after") if headers is not None else None
    if isinstance(retry_after, (str, int, float)) and not isinstance(retry_after, bool):
        try:
            seconds = float(retry_after)
        except (ValueError, OverflowError):
            pass
        else:
            if math.isfinite(seconds) and seconds >= 0:
                details["retry_after_seconds"] = seconds
    return details


async def generate_predictions(dataset: DevDataset, router: Router) -> dict[str, list[str]]:
    """Serial compatibility adapter; labels are never passed to the router."""
    predictions, _ = await run_evaluation(dataset, router)
    return predictions


async def run_evaluation(
    dataset: DevDataset,
    router: Router,
    *,
    concurrency: int = 1,
    min_interval_seconds: float = 0,
    continue_on_error: bool = False,
    progress: Callable[[str, int, int], None] | None = None,
) -> tuple[dict[str, list[str]], dict]:
    """Capture validated decisions in source order; cancel the entire batch on failure.

    A fixed worker pool bounds active calls and avoids queuing a task per input. Each
    input gets an independent, fresh dialogue state, with no reference labels or metadata.
    """
    if type(concurrency) is not int or not 1 <= concurrency <= 8:
        raise ValueError("concurrency must be an integer between 1 and 8")
    if (
        type(min_interval_seconds) not in (int, float)
        or not math.isfinite(min_interval_seconds)
        or not 0 <= min_interval_seconds <= 60
    ):
        raise ValueError("min_interval_seconds must be a finite number between 0 and 60")
    total = len(dataset.utterances)
    if len({item.id for item in dataset.utterances}) != total:
        raise ValueError("Evaluation utterance IDs must be unique")
    completed = 0
    stopped = False
    pending = iter(enumerate(dataset.utterances))
    captures: list[dict | None] = [None] * total
    started = perf_counter()
    start_lock = asyncio.Lock()
    next_start = 0.0

    async def pace_start() -> None:
        nonlocal next_start
        if not min_interval_seconds:
            return
        async with start_lock:
            delay = next_start - monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            next_start = monotonic() + min_interval_seconds

    async def worker() -> None:
        nonlocal completed, stopped
        while not stopped:
            item = next(pending, None)
            if item is None:
                return
            index, utterance = item
            await pace_start()
            if stopped:
                return
            try:
                call_started = perf_counter()
                decision = await router.route(utterance.text, DialogState(session_id=utterance.id))
                latency_ms = (perf_counter() - call_started) * 1000
                decision = RouterDecision.model_validate(decision)
                captures[index] = {
                    "utterance_id": utterance.id,
                    "router_latency_ms": round(latency_ms, 3),
                    "decision": decision.model_dump(mode="json"),
                }
            except Exception as exc:
                if not continue_on_error or not isinstance(exc, RouterError):
                    stopped = True
                    raise EvaluationRunError(utterance.id, completed, total) from exc
                captures[index] = {
                    "utterance_id": utterance.id,
                    "router_latency_ms": round((perf_counter() - call_started) * 1000, 3),
                    "decision": None,
                    "error": safe_router_error(exc),
                }
            completed += 1
            if progress is not None:
                progress(utterance.id, completed, total)

    workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, total))]
    try:
        await asyncio.gather(*workers)
    except BaseException:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise
    ordered = [capture for capture in captures if capture is not None]
    predictions = {
        capture["utterance_id"]: (
            [item["scenario_id"] for item in capture["decision"]["scenarios"]]
            if capture["decision"] is not None
            else []
        )
        for capture in ordered
    }
    failures = [capture["error"]["code"] for capture in ordered if capture["decision"] is None]
    provider_failures = sum(
        code in {"router_provider_error", "router_timeout"} for code in failures
    )
    invalid_outputs = failures.count("router_invalid_output")
    return predictions, {
        "schema_version": 1,
        "concurrency": concurrency,
        "min_interval_seconds": min_interval_seconds,
        "continue_on_error": continue_on_error,
        "failure_count": len(failures),
        "provider_failure_count": provider_failures,
        "invalid_output_count": invalid_outputs,
        "other_failure_count": len(failures) - provider_failures - invalid_outputs,
        "total_latency_ms": round((perf_counter() - started) * 1000, 3),
        "utterances": ordered,
    }


def write_predictions(predictions: dict[str, list[str]], path: Path) -> None:
    """Exclusive creation protects previous runs from accidental overwrite."""
    with path.open("x", encoding="utf-8") as output:
        json.dump(predictions, output, ensure_ascii=False, indent=2)
        output.write("\n")


def evaluate_predictions(
    predictions: dict[str, list[str]], dataset: DevDataset, evaluator: Path
) -> str:
    """Use the supplied evaluator unchanged, including for an explicitly limited batch."""
    with tempfile.TemporaryDirectory(prefix="voice-router-eval-") as temporary:
        root = Path(temporary)
        predictions_path = root / "predictions.json"
        dataset_path = root / "dev_utterances.json"
        write_predictions(predictions, predictions_path)
        with dataset_path.open("x", encoding="utf-8") as output:
            output.write(dataset.model_dump_json(indent=2))
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                str(evaluator),
                str(predictions_path),
                str(dataset_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    return result.stdout


def report_path_for(predictions_path: Path) -> Path:
    return predictions_path.with_name(f"{predictions_path.stem}.report.txt")


def details_path_for(predictions_path: Path) -> Path:
    return predictions_path.with_name(f"{predictions_path.stem}.details.json")


def preflight_output_paths(predictions_path: Path) -> tuple[Path, Path, Path]:
    paths = (
        predictions_path,
        report_path_for(predictions_path),
        details_path_for(predictions_path),
    )
    for path in paths:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Refusing to overwrite existing output: {path}")
        if not path.parent.is_dir():
            raise FileNotFoundError(f"Output directory does not exist: {path.parent}")
    return paths


def write_evaluation(
    predictions: dict[str, list[str]], details: dict, report: str, predictions_path: Path
) -> None:
    """Stage complete artifacts, publish exclusively, and roll back on publication failure.

    Hard links expose each complete file atomically and fail if a destination appeared
    after preflight. Only links created by this call are removed if the bundle fails.
    """
    paths = preflight_output_paths(predictions_path)
    published: list[Path] = []
    with tempfile.TemporaryDirectory(
        prefix=".voice-router-eval-", dir=predictions_path.parent
    ) as temporary:
        staging = Path(temporary)
        staged = (staging / "predictions.json", staging / "report.txt", staging / "details.json")
        write_predictions(predictions, staged[0])
        write_report(report, staged[1])
        with staged[2].open("x", encoding="utf-8") as output:
            json.dump(details, output, ensure_ascii=False, indent=2)
            output.write("\n")
        try:
            for source, target in zip(staged, paths, strict=True):
                os.link(source, target)
                published.append(target)
        except BaseException:
            for target in reversed(published):
                target.unlink()
            raise


def write_report(report: str, path: Path) -> None:
    with path.open("x", encoding="utf-8") as output:
        output.write(report)
