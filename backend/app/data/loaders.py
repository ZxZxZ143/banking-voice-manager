"""Load each canonical JSON file once at application startup and validate links."""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.data.models import (
    ActionDataset,
    DevDataset,
    DialogDataset,
    KnowledgeDataset,
    MockBackendDataset,
    ScenarioDataset,
    SlotDataset,
)


class DataLoadError(ValueError):
    """Missing, invalid, or internally inconsistent starter-kit input."""


@dataclass(frozen=True)
class StarterKit:
    scenarios: ScenarioDataset
    slots: SlotDataset
    actions: ActionDataset
    knowledge: KnowledgeDataset
    mock_backend: MockBackendDataset
    dialogs: DialogDataset
    dev_utterances: DevDataset


ModelT = TypeVar("ModelT", bound=BaseModel)


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-JSON numeric constant: {value}")


def _read(path: Path, model: type[ModelT]) -> ModelT:
    try:
        with path.open(encoding="utf-8") as source:
            data = json.load(source, parse_constant=_reject_constant)
        return model.model_validate(data)
    except ValidationError as exc:
        # Avoid putting complete business records into startup logs.
        problem = exc.errors(include_input=False)[0]
        location = ".".join(map(str, problem["loc"]))
        raise DataLoadError(f"{path.name}: invalid {location}: {problem['msg']}") from exc
    except (OSError, UnicodeError, ValueError) as exc:
        raise DataLoadError(f"Cannot load {path.name}: {exc}") from exc


def _unique(values: Iterable[str], label: str) -> set[str]:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise DataLoadError(f"Duplicate {label}: {value}")
        seen.add(value)
    return seen


def _references(values: Iterable[str], known: set[str], label: str) -> None:
    missing = set(values) - known
    if missing:
        raise DataLoadError(f"Unknown {label}: {', '.join(sorted(missing))}")


def _validate_links(kit: StarterKit) -> None:
    scenario_ids = _unique(
        [s.scenario_id for s in kit.scenarios.scenarios]
        + [s.id for s in kit.scenarios.system_intents],
        "scenario/system intent ID",
    )
    _unique((s.slug for s in kit.scenarios.scenarios), "scenario slug")
    slots = _unique((s.name for s in kit.slots.slots), "slot name")
    actions = _unique((a.name for a in kit.actions.actions), "action name")
    queues = _unique(kit.actions.queues, "queue")
    for dataset in (
        kit.slots,
        kit.actions,
        kit.knowledge,
        kit.mock_backend,
        kit.dialogs,
        kit.dev_utterances,
    ):
        if dataset.meta != kit.scenarios.meta:
            raise DataLoadError("Starter-kit dataset metadata does not match")
    for slot in kit.slots.slots:
        if slot.type == "enum" and not slot.values:
            raise DataLoadError(f"Enum slot {slot.name} has no allowed values")
        if slot.pattern:
            try:
                re.compile(slot.pattern)
            except re.error as exc:
                raise DataLoadError(f"Invalid slot pattern: {slot.name}") from exc
    for action in kit.actions.actions:
        _references(action.errors, set(kit.actions.error_codes), "action error code")
    for scenario in kit.scenarios.scenarios:
        _references(scenario.slots.required + scenario.slots.optional, slots, "scenario slot")
        _references(scenario.actions, actions, "scenario action")
        _references((rule.use_instead for rule in scenario.not_this_if), scenario_ids, "scenario")
        if scenario.handoff:
            _references([scenario.handoff.queue], queues, "handoff queue")
    mock = kit.mock_backend
    clients = _unique((c.client_id for c in mock.clients), "client ID")
    _unique((c.phone for c in mock.clients), "client phone")
    _unique((c.iin for c in mock.clients), "client IIN")
    policies = _unique((p.policy_number for p in mock.policies), "policy number")
    _unique((c.claim_number for c in mock.claims), "claim number")
    _unique((p.payment_id for p in mock.payments), "payment ID")
    for record in [*mock.policies, *mock.claims, *mock.payments]:
        _references([record.client_id], clients, "record client")
    for record in [*mock.claims, *mock.payments]:
        if record.policy_number:
            _references([record.policy_number], policies, "record policy")
    for policy in mock.policies:
        _references([policy.product], set(kit.knowledge.products), "policy product")
        if policy.start_date > policy.end_date:
            raise DataLoadError(f"Policy dates are reversed: {policy.policy_number}")
    _unique((d.dialog_id for d in kit.dialogs.dialogs), "dialog ID")
    for dialog in kit.dialogs.dialogs:
        if dialog.client_id:
            _references([dialog.client_id], clients, "dialog client")
        for turn in dialog.turns:
            _references(turn.scenarios, scenario_ids, "dialog scenario")
            _references(turn.slots, slots, "dialog slot")
            _references((a.name for a in turn.actions), actions, "dialog action")
            _references((a.queue for a in turn.actions if a.queue), queues, "dialog queue")
    _unique((u.id for u in kit.dev_utterances.utterances), "utterance ID")
    for utterance in kit.dev_utterances.utterances:
        _references(utterance.expected, scenario_ids, "expected scenario")


def load_starter_kit(path: Path | str) -> StarterKit:
    """Explicit per-app load, with no request-time disk reads or global cache."""
    root = Path(path)
    kit = StarterKit(
        scenarios=_read(root / "scenarios.json", ScenarioDataset),
        slots=_read(root / "slots.json", SlotDataset),
        actions=_read(root / "actions.json", ActionDataset),
        knowledge=_read(root / "knowledge_base.json", KnowledgeDataset),
        mock_backend=_read(root / "mock_backend.json", MockBackendDataset),
        dialogs=_read(root / "dialogs_sample.json", DialogDataset),
        dev_utterances=_read(root / "dev_utterances.json", DevDataset),
    )
    _validate_links(kit)
    return kit
