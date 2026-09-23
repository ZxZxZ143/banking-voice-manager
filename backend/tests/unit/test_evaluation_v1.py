"""Offline evaluation plumbing checks; these results do not measure model quality."""

import asyncio
import json
from unittest.mock import Mock

import pytest

from app.agent.schemas import RouterDecision
from app.core.config import Settings
from app.data.loaders import load_starter_kit
from app.data.models import DevDataset
from app.evaluation import __main__ as cli
from app.evaluation.runner import (
    EvaluationRunError,
    evaluate_predictions,
    generate_predictions,
    report_path_for,
    write_predictions,
    write_report,
)


@pytest.fixture(scope="module")
def kit():
    return load_starter_kit(Settings(_env_file=None).starter_kit_path)


def fixture_decision(*ids):
    return RouterDecision(
        language="ru",
        scenarios=[
            {"scenario_id": value, "confidence": 0.8, "reason": "Offline fixture"} for value in ids
        ],
    )


def test_adapter_passes_only_text_and_fresh_state_without_gold_labels(kit):
    received = []

    class RecordingRouter:
        async def route(self, text, state):
            assert state.history == [] and state.slots == {} and state.active_scenario is None
            assert state.language is None and state.turn_number == 0
            assert {"expected", "type", "lang"}.isdisjoint(state.model_dump())
            received.append((text, state.session_id, state))
            state.slots["city"] = "Offline mutation"
            return fixture_decision("SC27", "SC04")

    predictions = asyncio.run(generate_predictions(kit.dev_utterances, RecordingRouter()))
    assert len(received) == 104
    assert len({id(item[2]) for item in received}) == 104
    assert [(text, session_id) for text, session_id, _ in received] == [
        (item.text, item.id) for item in kit.dev_utterances.utterances
    ]
    assert predictions == {item.id: ["SC27", "SC04"] for item in kit.dev_utterances.utterances}


def test_failed_batch_stops_without_retry_or_exposing_provider_error(kit):
    calls = []

    class FailingRouter:
        async def route(self, text, state):
            calls.append(state.session_id)
            if len(calls) == 2:
                raise RuntimeError("do-not-expose-provider-body-or-key")
            return fixture_decision("SC01")

    with pytest.raises(EvaluationRunError) as error:
        asyncio.run(generate_predictions(kit.dev_utterances, FailingRouter()))
    assert calls == ["U001", "U002"]
    assert error.value.completed == 1 and error.value.total == 104
    assert error.value.utterance_id == "U002"
    assert "do-not-expose" not in str(error.value)


def test_prediction_and_report_writers_refuse_overwrite(tmp_path):
    target = tmp_path / "predictions.json"
    report = report_path_for(target)
    write_predictions({"U001": ["SC01"]}, target)
    write_report("Fixture report only\n", report)
    with pytest.raises(FileExistsError):
        write_predictions({"U001": ["SYS_UNCLEAR"]}, target)
    with pytest.raises(FileExistsError):
        write_report("changed", report)
    assert json.loads(target.read_text(encoding="utf-8")) == {"U001": ["SC01"]}
    assert report.read_text(encoding="utf-8") == "Fixture report only\n"


def test_supplied_evaluator_scores_primary_full_and_multi_intent_recall(kit):
    dataset = DevDataset.model_validate(
        {
            "meta": kit.dev_utterances.meta.model_dump(mode="json"),
            "utterances": [
                {
                    "id": "a",
                    "text": "Fixture A",
                    "lang": "ru",
                    "type": "single",
                    "expected": ["SC01"],
                },
                {
                    "id": "b",
                    "text": "Fixture B",
                    "lang": "kk",
                    "type": "single",
                    "expected": ["SC02"],
                },
                {
                    "id": "c",
                    "text": "Fixture C",
                    "lang": "mixed",
                    "type": "multi_intent",
                    "expected": ["SC27", "SC04"],
                },
                {
                    "id": "d",
                    "text": "Fixture D",
                    "lang": "ru",
                    "type": "multi_intent",
                    "expected": ["SC11", "SC25"],
                },
            ],
        }
    )
    scores = evaluate_predictions(
        {"a": ["SC01"], "b": ["SC03"], "c": ["SC04", "SC27"], "d": ["SC11"]},
        dataset,
        Settings(_env_file=None).starter_kit_path / "evaluate.py",
    )
    overall = next(line for line in scores.splitlines() if line.startswith("all "))
    assert overall.split() == ["all", "4", "0.500", "0.500"]
    assert "intent_recall (multi-intent): 0.750" in scores
    assert "Errors (2):" in scores
    assert "expected=['SC02']  got=['SC03']" in scores
    assert "expected=['SC11', 'SC25']  got=['SC11']" in scores


@pytest.mark.parametrize(
    ("key", "model", "missing"),
    [(None, "fixture-model", "OPENAI_API_KEY"), ("fixture-key", None, "OPENAI_ROUTER_MODEL")],
)
def test_cli_missing_configuration_never_calls_router_or_writes(
    key, model, missing, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: Settings(_env_file=None, openai_api_key=key, openai_router_model=model),
    )
    router = Mock()
    monkeypatch.setattr(cli, "RouterAgent", router)
    target = tmp_path / "missing.json"
    with pytest.raises(SystemExit) as error:
        cli.main(["--run", "--output", str(target)])
    assert error.value.code == 2 and missing in capsys.readouterr().err
    router.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_cli_check_data_needs_no_credentials(kit, monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: Settings(_env_file=None, openai_api_key=None, openai_router_model=None),
    )
    router = Mock()
    monkeypatch.setattr(cli, "RouterAgent", router)
    cli.main(["--check-data"])
    router.assert_not_called()
    assert "104 dev utterances. Router evaluation was not run." in capsys.readouterr().out


@pytest.mark.parametrize("value", ["0", "-1"])
def test_cli_rejects_nonpositive_limit(value, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--run", "--output", "unused.json", "--limit", value])
    assert error.value.code == 2
    assert "must be a positive integer" in capsys.readouterr().err


@pytest.fixture
def configured_cli(monkeypatch):
    settings = Settings(
        _env_file=None, openai_api_key="offline-fixture-key", openai_router_model="offline-fixture"
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    return settings


@pytest.mark.parametrize("existing_target", ["predictions", "report"])
def test_cli_output_preflight_prevents_paid_calls(
    existing_target, configured_cli, monkeypatch, tmp_path, capsys
):
    target = tmp_path / "predictions.json"
    existing_path = target if existing_target == "predictions" else report_path_for(target)
    write_report("Existing fixture output", existing_path)
    router = Mock()
    monkeypatch.setattr(cli, "RouterAgent", router)
    with pytest.raises(SystemExit) as error:
        cli.main(["--run", "--output", str(target)])
    assert error.value.code == 2
    assert "Refusing to overwrite" in capsys.readouterr().err
    router.assert_not_called()
    assert existing_path.read_text(encoding="utf-8") == "Existing fixture output"


def test_cli_limit_scores_only_selected_inputs(kit, configured_cli, monkeypatch, tmp_path, capsys):
    calls = []

    class FixtureRouter:
        def __init__(self, catalog, *, settings, slots):
            assert catalog.get_by_id("SC01") is not None
            assert settings is configured_cli and slots == kit.slots

        async def route(self, text, state):
            calls.append(state.session_id)
            return fixture_decision("SYS_UNCLEAR")

    monkeypatch.setattr(cli, "RouterAgent", FixtureRouter)
    target = tmp_path / "fixture-predictions.json"
    cli.main(["--run", "--output", str(target), "--limit", "2"])
    assert calls == ["U001", "U002"]
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "U001": ["SYS_UNCLEAR"],
        "U002": ["SYS_UNCLEAR"],
    }
    report = report_path_for(target).read_text(encoding="utf-8")
    assert "Evaluated: 2/104 utterances" in report
    assert "Model: offline-fixture" in report
    assert "Errors (2):" in report and "Errors (104):" not in report
    assert "Evaluated: 2/104 utterances" in capsys.readouterr().out


def test_cli_routing_failure_does_not_write_partial_predictions(
    configured_cli, monkeypatch, tmp_path, capsys
):
    class FailingRouter:
        def __init__(self, *args, **kwargs):
            pass

        async def route(self, text, state):
            raise RuntimeError("provider-body-is-private")

    monkeypatch.setattr(cli, "RouterAgent", FailingRouter)
    target = tmp_path / "failed.json"
    with pytest.raises(SystemExit) as error:
        cli.main(["--run", "--output", str(target), "--limit", "2"])
    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert "failed at U001 after 0/2" in stderr
    assert "provider-body-is-private" not in stderr
    assert list(tmp_path.iterdir()) == []
