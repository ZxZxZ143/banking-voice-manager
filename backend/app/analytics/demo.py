"""Synthetic DEMO records only; never loaded unless explicitly requested."""

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from app.events.models import ConversationEvent


def demo_events(now: datetime | None = None) -> list[ConversationEvent]:
    now = now or datetime.now(UTC)
    events = []

    def emit(session, channel, minute, kind, **fields):
        events.append(
            ConversationEvent(
                id=str(uuid5(NAMESPACE_URL, f"DEMO:{session}:{len(events)}")),
                session_id="DEMO-" + session,
                channel=channel,
                timestamp=(now + timedelta(minutes=minute)).isoformat(),
                event_type=kind,
                metadata={
                    "demo": True,
                    "turn": fields.pop("turn", 1),
                    **(
                        {"provider": "demo", "call_id": "DEMO-" + session}
                        if channel == "phone"
                        else {}
                    ),
                },
                **fields,
            )
        )

    # Six comparable historical windows: four selected scenario events per hour.
    for hour in range(1, 7):
        for number in range(4):
            name = f"baseline-{hour}-{number}"
            emit(name, "phone", -60 * hour - 5, "session.started")
            emit(
                name,
                "phone",
                -60 * hour - 4,
                "agent.response",
                text="[DEMO] Synthetic reply",
                risk={"level": "low", "signals": []},
            )
            emit(name, "phone", -60 * hour - 4, "scenario.selected", scenario="FRAUD_CALL_REPORT")
            emit(name, "phone", -60 * hour - 3, "conversation.ended", conversation_status="ended")
    for number in range(12):
        name = f"spike-{number}"
        emit(name, "phone", -20 + number, "session.started")
        emit(
            name,
            "phone",
            -19 + number,
            "agent.response",
            text="[DEMO] Synthetic review",
            risk={"level": "high", "signals": [{"code": "DEMO_SUSPICIOUS_ACTIVITY"}]},
            latency={
                "agent_ms": 3000,
                "tts_ms": 2000,
                "speech_end_to_playback_submit_ms": 6400,
                "speech_end_to_playback_complete_ms": 7400,
            },
        )
        emit(name, "phone", -19 + number, "scenario.selected", scenario="FRAUD_CALL_REPORT")
        emit(name, "phone", -18 + number, "handoff.requested", handoff=True)
        emit(name, "phone", -18 + number, "conversation.ended", conversation_status="handoff")
    emit("journey", "web", -6, "session.started")
    for turn, scenario in enumerate(
        ["LOGIN_PROBLEM", "LOGIN_PROBLEM", "SUSPICIOUS_TRANSACTION", "CARD_BLOCK"], 1
    ):
        emit(
            "journey", "web", -6 + turn, "agent.response", text="[DEMO] Synthetic reply", turn=turn
        )
        emit("journey", "web", -6 + turn, "scenario.selected", scenario=scenario, turn=turn)
    emit("journey", "web", -1, "clarification.requested", clarification=True)
    emit("journey", "web", -1, "handoff.requested", handoff=True)
    emit("journey", "web", 0, "conversation.ended", conversation_status="handoff")
    emit("recent", "phone", -1, "session.started")
    emit(
        "recent",
        "phone",
        0,
        "agent.response",
        text="[DEMO] Active synthetic session",
        conversation_status="awaiting_user",
    )
    return events


def seed_demo(store, now: datetime | None = None) -> int:
    events = demo_events(now)
    for event in events:
        store.append(event)
    return len(events)
