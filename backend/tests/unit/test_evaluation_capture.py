"""Deterministic capture/concurrency checks, without model calls or accuracy claims."""

import asyncio
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.agent.errors import RouterOutputError, RouterProviderError
from app.agent.schemas import RouterDecision
from app.core.config import Settings
from app.data.loaders import load_starter_kit
from app.evaluation import __main__ as cli
from app.evaluation import runner


@pytest.fixture(scope="module")
def kit():
    return load_starter_kit(Settings(_env_file=None).starter_kit_path)


@pytest.fixture
def dataset(kit):
    return kit.dev_utterances.model_copy(update={"utterances": kit.dev_utterances.utterances[:7]})


def decision():
    return RouterDecision(
        language="ru",
        response_language="ru",
        scenarios=[{"scenario_id": "SC01", "confidence": 0.8, "reason": "Offline fixture"}],
        segments=[
            {
                "text": "Offline segment",
                "scenario_id": "SC01",
                "confidence": 0.8,
                "reason": "Offline fixture",
            }
        ],
        alternatives=[{"scenario_id": "SC02", "confidence": 0.1}],
        slots={"city": "Offline city"},
    )


@pytest.mark.parametrize("concurrency", [1, 3])
def test_capture_preserves_order_bounds_calls_and_never_supplies_labels(dataset, concurrency):
    received = []
    finished = []
    updates = []
    active = 0
    peak = 0

    class FixtureRouter:
        async def route(self, text, state):
            nonlocal active, peak
            index = len(received)
            received.append((text, state))
            active += 1
            peak = max(peak, active)
            assert state.history == [] and state.slots == {} and state.active_scenario is None
            assert state.language is None and state.turn_number == 0
            assert {"expected", "type", "lang"}.isdisjoint(state.model_dump())
            state.slots["city"] = "Independent state mutation"
            # Deterministic event-loop yields make the first concurrent group finish in reverse.
            for _ in range(concurrency - index % concurrency):
                await asyncio.sleep(0)
            active -= 1
            finished.append(state.session_id)
            return decision()

    predictions, details = asyncio.run(
        runner.run_evaluation(
            dataset,
            FixtureRouter(),
            concurrency=concurrency,
            progress=lambda *args: updates.append(args),
        )
    )
    ids = [item.id for item in dataset.utterances]
    assert peak == concurrency and active == 0
    assert [(text, state.session_id) for text, state in received] == [
        (item.text, item.id) for item in dataset.utterances
    ]
    assert len({id(state) for _, state in received}) == len(ids)
    assert list(predictions) == ids
    assert predictions == {utterance_id: ["SC01"] for utterance_id in ids}
    assert [item["utterance_id"] for item in details["utterances"]] == ids
    assert all(
        item["decision"] == decision().model_dump(mode="json") for item in details["utterances"]
    )
    assert all(item["router_latency_ms"] >= 0 for item in details["utterances"])
    assert details["concurrency"] == concurrency and details["total_latency_ms"] >= 0
    assert updates == [
        (utterance_id, index + 1, len(ids)) for index, utterance_id in enumerate(finished)
    ]
    assert finished[:concurrency] == list(reversed(ids[:concurrency]))


def test_capture_measures_route_wall_time_and_total_time(dataset, monkeypatch):
    dataset = dataset.model_copy(update={"utterances": dataset.utterances[:1]})
    ticks = iter([0.0, 1.0, 2.5, 4.0])
    monkeypatch.setattr(runner, "perf_counter", lambda: next(ticks))

    class FixtureRouter:
        async def route(self, text, state):
            return decision()

    _, details = asyncio.run(runner.run_evaluation(dataset, FixtureRouter()))
    assert details["utterances"][0]["router_latency_ms"] == 1500.0
    assert details["total_latency_ms"] == 4000.0


@pytest.mark.parametrize("concurrency", [1, 3])
def test_pacing_spaces_call_starts_across_workers(dataset, concurrency, monkeypatch):
    now = 0.0
    starts = []
    sleeps = []
    original_sleep = asyncio.sleep

    async def simulated_sleep(delay):
        nonlocal now
        sleeps.append(delay)
        now += delay
        await original_sleep(0)

    class FixtureRouter:
        async def route(self, text, state):
            starts.append(now)
            await original_sleep(0)
            return decision()

    monkeypatch.setattr(runner, "monotonic", lambda: now)
    monkeypatch.setattr(runner, "perf_counter", lambda: now)
    monkeypatch.setattr(runner.asyncio, "sleep", simulated_sleep)
    _, details = asyncio.run(
        runner.run_evaluation(
            dataset, FixtureRouter(), concurrency=concurrency, min_interval_seconds=3
        )
    )
    assert starts == [float(index * 3) for index in range(len(dataset.utterances))]
    assert sleeps == [3.0] * (len(dataset.utterances) - 1)
    assert details["min_interval_seconds"] == 3
    assert details["total_latency_ms"] == 18000


def test_pacing_wait_is_excluded_from_route_latency(dataset, monkeypatch):
    now = 0.0
    starts = []
    dataset = dataset.model_copy(update={"utterances": dataset.utterances[:3]})

    async def simulated_sleep(delay):
        nonlocal now
        now += delay

    class FixtureRouter:
        async def route(self, text, state):
            nonlocal now
            starts.append(now)
            now += 0.25
            return decision()

    monkeypatch.setattr(runner, "monotonic", lambda: now)
    monkeypatch.setattr(runner, "perf_counter", lambda: now)
    monkeypatch.setattr(runner.asyncio, "sleep", simulated_sleep)
    _, details = asyncio.run(
        runner.run_evaluation(dataset, FixtureRouter(), min_interval_seconds=3)
    )
    assert starts == [0, 3, 6]
    assert [item["router_latency_ms"] for item in details["utterances"]] == [250.0] * 3
    assert details["total_latency_ms"] == 6250


@pytest.mark.parametrize("interval", [-1, 61, float("nan"), float("inf"), True, "3"])
def test_runner_rejects_invalid_interval_before_calls(dataset, interval):
    router = Mock()
    with pytest.raises(ValueError, match="finite number between 0 and 60"):
        asyncio.run(runner.run_evaluation(dataset, router, min_interval_seconds=interval))
    router.route.assert_not_called()


@pytest.mark.parametrize("code", ["rate_limit_exceeded", "insufficient_quota"])
def test_provider_diagnostics_include_only_allowlisted_metadata(dataset, code):
    cause = RuntimeError("private provider exception")
    cause.status_code = 429
    cause.code = code
    cause.body = {"api_key": "private provider body"}
    cause.response = SimpleNamespace(
        headers={"retry-after": "3.5", "authorization": "private header"}
    )
    failure = RouterProviderError()
    failure.__cause__ = cause

    class FixtureRouter:
        async def route(self, text, state):
            if state.session_id == "U001":
                raise failure
            if state.session_id == "U002":
                raise RouterOutputError()
            return decision()

    _, details = asyncio.run(
        runner.run_evaluation(dataset, FixtureRouter(), continue_on_error=True)
    )
    assert details["failure_count"] == 2
    assert details["provider_failure_count"] == details["invalid_output_count"] == 1
    assert details["other_failure_count"] == 0
    assert details["utterances"][0]["error"] == {
        "code": failure.code,
        "message": failure.message,
        "http_status": 429,
        "provider_code": code,
        "retry_after_seconds": 3.5,
    }
    assert "private" not in json.dumps(details)


@pytest.mark.parametrize(
    ("status", "retry_after"),
    [(200, "private header"), (600, "nan"), ("429", "inf"), (True, "-1"), (429.0, True)],
)
def test_provider_diagnostics_reject_untrusted_status_code_and_retry_headers(status, retry_after):
    cause = RuntimeError("private provider exception")
    cause.status_code = status
    cause.code = "private unknown code"
    cause.response = SimpleNamespace(headers={"retry-after": retry_after})
    failure = RouterProviderError()
    failure.__cause__ = cause
    assert runner.safe_router_error(failure) == {"code": failure.code, "message": failure.message}


def test_continue_on_error_records_safe_failure_and_does_not_retry(dataset):
    calls = []
    failure = RouterOutputError()
    failure.__cause__ = RuntimeError("private-provider-body")

    class FixtureRouter:
        async def route(self, text, state):
            calls.append(state.session_id)
            if state.session_id == "U002":
                raise failure
            return decision()

    predictions, details = asyncio.run(
        runner.run_evaluation(dataset, FixtureRouter(), concurrency=3, continue_on_error=True)
    )
    assert calls == [item.id for item in dataset.utterances]
    assert predictions["U002"] == [] and predictions["U003"] == ["SC01"]
    assert details["failure_count"] == 1 and details["continue_on_error"] is True
    capture = details["utterances"][1]
    assert capture["decision"] is None and capture["router_latency_ms"] >= 0
    assert capture["error"] == {"code": failure.code, "message": failure.message}
    assert "private-provider-body" not in json.dumps(details)


def test_continue_on_error_still_aborts_on_unexpected_exceptions(dataset):
    class FailingRouter:
        async def route(self, text, state):
            raise RuntimeError("Unexpected programmer error")

    with pytest.raises(runner.EvaluationRunError):
        asyncio.run(runner.run_evaluation(dataset, FailingRouter(), continue_on_error=True))


def test_failed_concurrent_batch_cancels_pending_calls_and_preserves_original_cause(dataset):
    calls = []
    cancelled = []
    original = RuntimeError("private-provider-body-and-secret")

    async def run():
        started = asyncio.Event()
        never = asyncio.Event()

        class FailingRouter:
            async def route(self, text, state):
                calls.append(state.session_id)
                if len(calls) == 3:
                    started.set()
                await started.wait()
                if state.session_id == "U002":
                    raise original
                try:
                    await never.wait()
                except asyncio.CancelledError:
                    cancelled.append(state.session_id)
                    raise

        with pytest.raises(runner.EvaluationRunError) as error:
            await runner.run_evaluation(dataset, FailingRouter(), concurrency=3)
        assert error.value.__cause__ is original
        assert error.value.utterance_id == "U002"
        assert error.value.completed == 0 and error.value.total == len(dataset.utterances)
        assert "private-provider" not in str(error.value)

    asyncio.run(run())
    assert calls == ["U001", "U002", "U003"]
    assert set(cancelled) == {"U001", "U003"}


@pytest.mark.parametrize("concurrency", [0, 9, -1, True, 1.5])
def test_runner_rejects_invalid_concurrency_before_calls(dataset, concurrency):
    router = Mock()
    with pytest.raises(ValueError, match="between 1 and 8"):
        asyncio.run(runner.run_evaluation(dataset, router, concurrency=concurrency))
    router.route.assert_not_called()


@pytest.fixture
def configured_cli(monkeypatch):
    settings = Settings(
        _env_file=None, openai_api_key="offline-fixture-secret", openai_router_model="offline-model"
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    return settings


@pytest.mark.parametrize("target_kind", ["predictions", "report", "details"])
def test_all_output_paths_preflight_before_router_creation(
    target_kind, configured_cli, monkeypatch, tmp_path, capsys
):
    target = tmp_path / "predictions.json"
    paths = {
        "predictions": target,
        "report": runner.report_path_for(target),
        "details": runner.details_path_for(target),
    }
    existing = paths[target_kind]
    existing.write_text("Existing fixture", encoding="utf-8")
    router = Mock()
    monkeypatch.setattr(cli, "RouterAgent", router)
    with pytest.raises(SystemExit) as error:
        cli.main(["--run", "--output", str(target), "--concurrency", "3"])
    assert error.value.code == 2
    assert "Refusing to overwrite" in capsys.readouterr().err
    router.assert_not_called()
    assert list(tmp_path.iterdir()) == [existing]
    assert existing.read_text(encoding="utf-8") == "Existing fixture"


@pytest.mark.parametrize("concurrency", [1, 3])
def test_cli_captures_decisions_metadata_and_safe_progress(
    concurrency, configured_cli, monkeypatch, tmp_path, capsys, kit
):
    class FixtureRouter:
        def __init__(self, *args, **kwargs):
            pass

        async def route(self, text, state):
            await asyncio.sleep(0)
            return decision()

    monkeypatch.setattr(cli, "RouterAgent", FixtureRouter)
    target = tmp_path / "capture.json"
    cli.main(["--run", "--output", str(target), "--limit", "3", "--concurrency", str(concurrency)])
    outputs = capsys.readouterr()
    details = json.loads(runner.details_path_for(target).read_text(encoding="utf-8"))
    report = runner.report_path_for(target).read_text(encoding="utf-8")
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "U001": ["SC01"],
        "U002": ["SC01"],
        "U003": ["SC01"],
    }
    assert details["model"] == "offline-model" and details["schema_version"] == 1
    assert details["evaluated"] == 3 and details["dataset_total"] == 104
    assert details["concurrency"] == concurrency
    assert len(details["instructions_sha256"]) == len(details["dataset_sha256"]) == 64
    assert details["started_at_utc"] <= details["completed_at_utc"]
    assert [item["utterance_id"] for item in details["utterances"]] == ["U001", "U002", "U003"]
    for item in details["utterances"]:
        assert item["decision"] == decision().model_dump(mode="json")
        assert set(item) == {"utterance_id", "router_latency_ms", "decision"}
    assert "Instructions SHA256:" in report and "Dataset SHA256:" in report
    assert outputs.err.splitlines() == [
        f"Progress: {index}/3 completed (U{index:03d})" for index in range(1, 4)
    ]
    assert all(item.text not in outputs.err for item in kit.dev_utterances.utterances[:3])
    assert "offline-fixture-secret" not in outputs.out + outputs.err + json.dumps(details) + report
    assert len(list(tmp_path.iterdir())) == 3


@pytest.mark.parametrize("value", ["0", "9", "-1"])
def test_cli_rejects_out_of_bounds_concurrency(value, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--run", "--output", "unused.json", "--concurrency", value])
    assert error.value.code == 2 and "between 1 and 8" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["-1", "61", "nan", "inf"])
def test_cli_rejects_out_of_bounds_interval(value, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--run", "--output", "unused.json", "--min-interval-seconds", value])
    assert error.value.code == 2 and "finite number between 0 and 60" in capsys.readouterr().err


@pytest.mark.parametrize("failure", [RuntimeError("private-provider-body"), RouterOutputError()])
def test_cli_routing_failure_has_no_artifacts_or_private_error_body(
    failure, configured_cli, monkeypatch, tmp_path, capsys
):
    class FailingRouter:
        def __init__(self, *args, **kwargs):
            pass

        async def route(self, text, state):
            raise failure

    monkeypatch.setattr(cli, "RouterAgent", FailingRouter)
    with pytest.raises(SystemExit) as error:
        cli.main(["--run", "--output", str(tmp_path / "failed.json"), "--concurrency", "3"])
    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert "Routing failed at U001 after 0/104" in stderr
    assert "private-provider-body" not in stderr
    if isinstance(failure, RouterOutputError):
        assert "router_invalid_output" in stderr
    assert list(tmp_path.iterdir()) == []


def test_scoring_failure_writes_no_outputs(configured_cli, monkeypatch, tmp_path, capsys):
    class FixtureRouter:
        def __init__(self, *args, **kwargs):
            pass

        async def route(self, text, state):
            return decision()

    monkeypatch.setattr(cli, "RouterAgent", FixtureRouter)
    monkeypatch.setattr(
        cli,
        "evaluate_predictions",
        Mock(side_effect=subprocess.CalledProcessError(1, "fixture", stderr="private-body")),
    )
    with pytest.raises(SystemExit):
        cli.main(["--run", "--output", str(tmp_path / "failed.json"), "--limit", "1"])
    assert "private-body" not in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_cli_continue_on_error_reports_failure_counts(
    configured_cli, monkeypatch, tmp_path, capsys
):
    class FixtureRouter:
        def __init__(self, *args, **kwargs):
            pass

        async def route(self, text, state):
            if state.session_id == "U001":
                raise RouterOutputError()
            return decision()

    monkeypatch.setattr(cli, "RouterAgent", FixtureRouter)
    target = tmp_path / "with-failure.json"
    cli.main(["--run", "--output", str(target), "--limit", "2", "--continue-on-error"])
    details = json.loads(runner.details_path_for(target).read_text(encoding="utf-8"))
    report = runner.report_path_for(target).read_text(encoding="utf-8")
    assert details["failure_count"] == 1
    assert json.loads(target.read_text(encoding="utf-8")) == {"U001": [], "U002": ["SC01"]}
    assert "Routing failures: 1" in report and "Continue on routing error: True" in report
    assert "got=[]" in report
    assert "Progress: 2/2 completed (U002)" in capsys.readouterr().err


def test_bundle_publication_race_preserves_existing_file_and_rolls_back(tmp_path, monkeypatch):
    target = tmp_path / "race.json"
    report = runner.report_path_for(target)
    original_link = runner.os.link

    def racing_link(source, destination):
        if destination == report:
            report.write_text("Other process report", encoding="utf-8")
        original_link(source, destination)

    monkeypatch.setattr(runner.os, "link", racing_link)
    with pytest.raises(FileExistsError):
        runner.write_evaluation({"U001": ["SC01"]}, {"utterances": []}, "Fixture report", target)
    assert list(tmp_path.iterdir()) == [report]
    assert report.read_text(encoding="utf-8") == "Other process report"


def test_bundle_serialization_failure_publishes_nothing(tmp_path):
    with pytest.raises(TypeError):
        runner.write_evaluation({}, {"invalid": object()}, "Fixture report", tmp_path / "bad.json")
    assert list(tmp_path.iterdir()) == []
