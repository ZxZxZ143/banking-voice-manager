"""One extraction boundary for optional Agent evidence; no business inference."""

import math
from datetime import datetime
from typing import Any

RISK_LEVELS = ("unknown", "low", "medium", "high", "critical")
METRICS = (
    "agent_ms",
    "tts_ms",
    "tts_first_audio_ms",
    "endpointing_ms",
    "stt_final_ms",
    "speech_end_to_playback_submit_ms",
    "speech_end_to_playback_complete_ms",
    "final_to_playback_complete_ms",
    "client_stt_final_ms",
)


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return parsed


def scenario_key(value: Any) -> str | None:
    key = value.get("scenario_id") if isinstance(value, dict) else value
    return key if isinstance(key, str) and 0 < len(key) <= 128 else None


def risk_details(value: Any) -> tuple[str, list[str]]:
    risk = value if isinstance(value, dict) else {}
    level = risk.get("level")
    level = level if level in RISK_LEVELS else "unknown"
    signals = []
    for item in risk.get("signals", []) if isinstance(risk.get("signals"), list) else []:
        key = (
            next((item[k] for k in ("code", "type", "id") if isinstance(item.get(k), str)), None)
            if isinstance(item, dict)
            else item
        )
        if isinstance(key, str) and 0 < len(key) <= 128:
            signals.append(key)
    return level, sorted(set(signals))


def scenario_keys(event) -> list[str]:
    if event.scenario is not None:
        key = scenario_key(event.scenario)
        return [key] if key else []
    values = selected_values(event.trace, event.routing)
    return list(dict.fromkeys(key for value in values if (key := scenario_key(value))))


def latency_values(value: Any) -> dict[str, float]:
    source = dict(value) if isinstance(value, dict) else {}
    # Legacy trace.total is Agent/backend processing, NEVER end-to-end phone latency.
    for old, new in [
        ("total", "agent_ms"),
        ("stt", "stt_final_ms"),
        ("tts_first_audio", "tts_first_audio_ms"),
    ]:
        if new not in source and old in source:
            source[new] = source[old]
    return {
        key: float(v)
        for key in METRICS
        if isinstance(v := source.get(key), (int, float))
        and not isinstance(v, bool)
        and math.isfinite(v)
        and v >= 0
    }


def turn_latencies(events) -> list[dict[str, float]]:
    turns: dict[int, dict[str, float]] = {}
    index = 0
    answered = False
    for event in events:
        if event.event_type not in ("transcript.final", "agent.response"):
            continue
        metadata = event.metadata or {}
        trace = event.trace if isinstance(event.trace, dict) else {}
        number = metadata.get("turn", trace.get("turn_number", trace.get("turn")))
        if isinstance(number, int) and not isinstance(number, bool) and number > 0:
            index = number
        elif event.event_type == "transcript.final" or answered or index == 0:
            index += 1
        answered = event.event_type == "agent.response"
        turns.setdefault(index, {}).update(latency_values(event.latency))
    return list(turns.values())


def selected_values(trace: Any, routing: Any) -> list:
    trace = trace if isinstance(trace, dict) else {}
    routing = routing if isinstance(routing, dict) else {}
    values = trace.get("scenarios")
    if not isinstance(values, list):
        values = routing.get("scenarios", routing.get("selections", []))
    return values if isinstance(values, list) else []


def agent_evidence(response) -> dict:
    """Centralize exact optional Agent field names, preserving opaque source payloads."""
    trace = response.get("trace")
    trace = trace if isinstance(trace, dict) else {}
    routing = response.get("routing")
    routing = routing if isinstance(routing, dict) else {}
    state = response.get("state")
    state = state if isinstance(state, dict) else {}
    question = routing.get("clarification_question")
    return {
        "fields": {
            "conversation_status": response.get("conversation_status"),
            **{key: response.get(key) for key in ("risk", "routing", "state", "trace")},
            "language": next(
                (
                    source["language"]
                    for source in (trace, routing, state)
                    if isinstance(source.get("language"), str)
                ),
                None,
            ),
            "action": trace.get("actions"),
            "latency": trace.get("latency_ms"),
        },
        "scenarios": selected_values(trace, routing),
        "clarification": question
        if isinstance(question, str) and question.strip()
        else True
        if trace.get("clarification") is True
        else None,
        "handoff": trace.get("handoff") is True or response.get("conversation_status") == "handoff",
    }
