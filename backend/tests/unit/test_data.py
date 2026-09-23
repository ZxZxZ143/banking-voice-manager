import json
import shutil
from pathlib import Path

import pytest

from app.data.loaders import DataLoadError, load_starter_kit
from app.data.repositories import KnowledgeRepository, MockBackendRepository
from app.scenarios.catalog import ScenarioCatalog

STARTER_KIT = Path(__file__).resolve().parents[3] / "data" / "starter_kit"


@pytest.fixture
def kit():
    return load_starter_kit(STARTER_KIT)


def test_canonical_data_loads_with_real_wrappers(kit):
    assert len(kit.scenarios.scenarios) == 40
    assert len(kit.scenarios.system_intents) == 3
    assert len(kit.slots.slots) == 43
    assert len(kit.actions.actions) == 31
    assert len(kit.mock_backend.clients) == 11
    assert len(kit.mock_backend.policies) == 11
    assert len(kit.mock_backend.claims) == 4
    assert len(kit.mock_backend.payments) == 2
    assert len(kit.dialogs.dialogs) == 10
    assert len(kit.dev_utterances.utterances) == 104
    assert str(kit.scenarios.meta.as_of_date) == "2026-10-01"
    # The victim of an OGPO incident need not own the liable driver's policy.
    victim_claim = next(c for c in kit.mock_backend.claims if c.claim_type == "ogpo_victim")
    policy = next(
        p for p in kit.mock_backend.policies if p.policy_number == victim_claim.policy_number
    )
    assert victim_claim.client_id != policy.client_id


def test_compact_catalog_keeps_all_routing_context_without_execution_details(kit):
    catalog = ScenarioCatalog(kit.scenarios)
    compact = catalog.get_compact_router_catalog()
    assert len(compact["scenarios"]) == 40
    assert {intent["id"] for intent in compact["system_intents"]} == {
        "SYS_UNCLEAR",
        "SYS_OUT_OF_SCOPE",
        "SYS_GOODBYE",
    }
    first = compact["scenarios"][0]
    assert first["not_this_if"][0]["use_instead"] == "SC02"
    assert first["examples"]["ru"] and first["examples"]["kk"]
    assert "actions" not in first and "responses" not in first
    assert catalog.get_by_id("unknown") is None
    assert catalog.get_system_intent("SYS_UNCLEAR").id == "SYS_UNCLEAR"


def test_catalog_and_repositories_are_isolated_from_caller_mutation(kit):
    catalog = ScenarioCatalog(kit.scenarios)
    knowledge = KnowledgeRepository(kit.knowledge)
    backend = MockBackendRepository(kit.mock_backend)
    kit.scenarios.scenarios[0].name = "changed after constructing catalog"
    catalog.get_by_id("SC01").slots.required.clear()
    catalog.get_all()[0].not_this_if.clear()
    catalog.get_compact_router_catalog()["scenarios"][0]["examples"]["ru"].clear()
    assert catalog.get_by_id("SC01").name == "OGPO price quote"
    assert catalog.get_by_id("SC01").slots.required
    assert catalog.get_by_id("SC01").not_this_if
    assert catalog.get_compact_router_catalog()["scenarios"][0]["examples"]["ru"]
    knowledge.get("payments.installments")["ogpo"] = "mutated"
    knowledge.get_all()["company"]["name"] = "mutated"
    assert knowledge.get("payments.installments.ogpo") == "Full payment only"
    assert knowledge.get("company.name") == "Saqta Insurance"
    backend.get_all("policies")[0]["details"].clear()
    backend.find("clients", client_id="C001")[0]["full_name"] = "mutated"
    assert backend.get_all("policies")[0]["details"]
    assert backend.find("clients", client_id="C001")[0]["full_name"] == "Arman Tulegenov"
    assert backend.find("clients", client_id="missing") == []
    with pytest.raises(KeyError):
        knowledge.get("payments.missing")
    with pytest.raises(ValueError):
        backend.get_all("meta")


def test_missing_file_fails_clearly(tmp_path):
    with pytest.raises(DataLoadError, match="scenarios.json"):
        load_starter_kit(tmp_path)


@pytest.mark.parametrize("contents", ["{not json", '{"scenarios": []}', "NaN"])
def test_malformed_data_fails_clearly(tmp_path, contents):
    (tmp_path / "scenarios.json").write_text(contents, encoding="utf-8")
    with pytest.raises(DataLoadError, match="scenarios.json"):
        load_starter_kit(tmp_path)


@pytest.mark.parametrize(
    ("file_name", "mutation", "message"),
    [
        (
            "scenarios.json",
            lambda data: data["scenarios"].append(data["scenarios"][0]),
            "Duplicate scenario",
        ),
        (
            "scenarios.json",
            lambda data: data["scenarios"][0]["actions"].append("unknown_action"),
            "Unknown scenario action",
        ),
        (
            "scenarios.json",
            lambda data: data["scenarios"][0]["slots"]["required"].append("unknown_slot"),
            "Unknown scenario slot",
        ),
        (
            "scenarios.json",
            lambda data: data["scenarios"][0]["not_this_if"][0].update(use_instead="SC99"),
            "Unknown scenario",
        ),
        (
            "mock_backend.json",
            lambda data: data["policies"][0].update(client_id="C999"),
            "Unknown record client",
        ),
        (
            "dev_utterances.json",
            lambda data: data["utterances"][0]["expected"].append("SC99"),
            "Unknown expected scenario",
        ),
    ],
)
def test_duplicate_and_dangling_references_fail(tmp_path, file_name, mutation, message):
    shutil.copytree(STARTER_KIT, tmp_path, dirs_exist_ok=True)
    path = tmp_path / file_name
    data = json.loads(path.read_text(encoding="utf-8"))
    mutation(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DataLoadError, match=message):
        load_starter_kit(tmp_path)
