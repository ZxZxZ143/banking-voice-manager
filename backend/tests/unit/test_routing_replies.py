import pytest

from app.core.config import Settings
from app.data.loaders import load_starter_kit
from app.dialog.models import DialogState
from app.response.routing import RoutingReplyGenerator
from app.scenarios.catalog import ScenarioCatalog
from app.scenarios.decision_policy import PolicyResult


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_local_replies_never_leak_unfilled_source_templates(language):
    kit = load_starter_kit(Settings(_env_file=None).starter_kit_path)
    catalog = ScenarioCatalog(kit.scenarios)
    replies = RoutingReplyGenerator(catalog, kit.slots)
    ids = [s.scenario_id for s in kit.scenarios.scenarios] + [
        s.id for s in kit.scenarios.system_intents
    ]
    for scenario_id in ids:
        state = DialogState(
            session_id="reply-test",
            active_scenario=scenario_id if not scenario_id.startswith("SYS_") else None,
            response_language=language,
            conversation_status="handoff" if scenario_id == "SC37" else "awaiting_user",
        )
        policy = PolicyResult(
            outcome="clarify" if scenario_id == "SYS_UNCLEAR" else "accept",
            scenario_ids=[scenario_id],
            consecutive_low_confidence=0,
            reason="Offline response contract check",
        )
        response = replies.generate(state, policy)
        assert response.strip()
        assert "{" not in response and "}" not in response, (scenario_id, response)
        if scenario_id == "SYS_UNCLEAR":
            assert "?" in response or language == "kk"
