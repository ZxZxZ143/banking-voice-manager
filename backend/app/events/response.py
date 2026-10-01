from collections.abc import Iterator, Mapping
from typing import Any

from app.core.channels import Channel
from app.events.models import ConversationEvent


def response_events(
    session_id: str, channel: Channel, response: Mapping[str, Any]
) -> Iterator[ConversationEvent]:
    """Record supplied evidence, never infer policy acceptance or business actions."""
    trace = response.get("trace")
    trace = trace if isinstance(trace, dict) else {}
    routing = response.get("routing")
    routing = routing if isinstance(routing, dict) else {}
    fields = {
        "session_id": session_id,
        "channel": channel,
        "conversation_status": response["conversation_status"],
        **{key: response.get(key) for key in ("risk", "routing", "state", "trace")},
        "language": trace.get("language") if isinstance(trace.get("language"), str) else None,
        "action": trace.get("actions"),
        "latency": trace.get("latency_ms"),
    }
    yield ConversationEvent(event_type="agent.response", text=response["response_text"], **fields)
    scenarios = trace.get("scenarios")
    if not isinstance(scenarios, list):
        scenarios = routing.get("scenarios", routing.get("selections"))
    if isinstance(scenarios, list):
        for scenario in scenarios:
            confidence = scenario.get("confidence") if isinstance(scenario, dict) else None
            yield ConversationEvent(
                event_type="scenario.selected", scenario=scenario, confidence=confidence, **fields
            )
    question = routing.get("clarification_question")
    if trace.get("clarification") is True or (isinstance(question, str) and question.strip()):
        yield ConversationEvent(
            event_type="clarification.requested",
            clarification=question if isinstance(question, str) else True,
            **fields,
        )
    if trace.get("handoff") is True or response["conversation_status"] == "handoff":
        yield ConversationEvent(event_type="handoff.requested", handoff=True, **fields)
