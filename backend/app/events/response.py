from collections.abc import Iterator, Mapping
from typing import Any

from app.core.channels import Channel
from app.events.models import ConversationEvent
from app.events.normalize import agent_evidence


def response_events(
    session_id: str, channel: Channel, response: Mapping[str, Any]
) -> Iterator[ConversationEvent]:
    """Record supplied evidence, never infer policy acceptance or business actions."""
    evidence = agent_evidence(response)
    fields = {"session_id": session_id, "channel": channel, **evidence["fields"]}
    yield ConversationEvent(event_type="agent.response", text=response["response_text"], **fields)
    for scenario in evidence["scenarios"]:
        confidence = scenario.get("confidence") if isinstance(scenario, dict) else None
        yield ConversationEvent(
            event_type="scenario.selected", scenario=scenario, confidence=confidence, **fields
        )
    if evidence["clarification"] is not None:
        yield ConversationEvent(
            event_type="clarification.requested",
            clarification=evidence["clarification"],
            **fields,
        )
    if evidence["handoff"]:
        yield ConversationEvent(event_type="handoff.requested", handoff=True, **fields)
