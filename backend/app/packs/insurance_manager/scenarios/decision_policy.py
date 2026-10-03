from typing import Literal

from pydantic import Field, model_validator

from app.core.contracts import Contract
from app.packs.insurance_manager.agent.schemas import RouterDecision
from app.packs.insurance_manager.response.lookup import IDENTIFIERS
from app.packs.insurance_manager.scenarios.catalog import ScenarioCatalog
from app.packs.insurance_manager.state import DialogState


class PolicySettings(Contract):
    accept_threshold: float = Field(default=0.75, ge=0, le=1)
    low_threshold: float = Field(default=0.45, ge=0, le=1)
    handoff_after: int = Field(default=2, ge=1)
    max_unclear_turns: int = Field(default=3, ge=1)

    @model_validator(mode="after")
    def check_threshold_order(self) -> "PolicySettings":
        if self.low_threshold >= self.accept_threshold:
            raise ValueError("low_threshold must be below accept_threshold")
        return self


class PolicyResult(Contract):
    outcome: Literal["accept", "clarify", "handoff", "continue"]
    scenario_ids: list[str]
    consecutive_low_confidence: int
    reason: str


class DecisionPolicy:
    """Pure provisional policy; caller owns state updates and actual operator transfer."""

    def __init__(self, catalog: ScenarioCatalog, settings: PolicySettings | None = None) -> None:
        self.catalog = catalog
        self.settings = settings or PolicySettings()

    def decide(self, decision: RouterDecision, state: DialogState) -> PolicyResult:
        compact = self.catalog.get_compact_router_catalog()
        priorities = {s["scenario_id"]: s["priority"] for s in compact["scenarios"]}
        known = set(priorities) | {s["id"] for s in compact["system_intents"]}
        ids = [item.scenario_id for item in decision.scenarios]
        if any(
            item.scenario_id not in known for item in [*decision.scenarios, *decision.alternatives]
        ):
            raise ValueError("Router returned an unknown scenario ID")
        confidence = min(item.confidence for item in decision.scenarios)
        low_count = (
            state.consecutive_low_confidence + 1 if confidence < self.settings.low_threshold else 0
        )
        explicit_handoff = any(
            item.scenario_id == "SC37" and item.confidence >= self.settings.accept_threshold
            for item in decision.scenarios
        )
        if explicit_handoff:
            return PolicyResult(
                outcome="handoff",
                scenario_ids=["SC37"],
                consecutive_low_confidence=low_count,
                reason="Operator assistance is required",
            )
        if ids == ["SYS_OUT_OF_SCOPE"]:
            return PolicyResult(
                outcome="accept",
                scenario_ids=ids,
                consecutive_low_confidence=0,
                reason="Insurance scope reply; preserve business context",
            )
        conversational = state.conversation
        progress = bool(
            (decision.slots and decision.is_continuation)
            or (
                conversational
                and conversational.expected_answer_type
                and decision.conversation_signal in {"answer", "partial_answer"}
            )
        )
        if decision.conversation_signal == "greeting" or progress:
            low_count = 0
        if (
            conversational
            and (
                conversational.expected_slot in decision.slots
                or (
                    conversational.expected_slot in IDENTIFIERS
                    and (
                        bool(IDENTIFIERS & decision.slots.keys())
                        or (
                            decision.identifier_answer is not None
                            and decision.identifier_answer.status == "unavailable"
                        )
                    )
                )
            )
            and state.active_scenario is not None
            and (ids == [state.active_scenario] or ids == ["SYS_UNCLEAR"])
        ):
            return PolicyResult(
                outcome="continue",
                scenario_ids=[state.active_scenario],
                consecutive_low_confidence=0,
                reason="Validated requested data continues the active scenario",
            )
        confident = [
            item.scenario_id
            for item in decision.scenarios
            if item.confidence >= self.settings.accept_threshold
        ]
        if confidence < self.settings.accept_threshold and any(
            priorities.get(scenario_id) == "urgent" for scenario_id in confident
        ):
            # A weak secondary request must not block a confident urgent request.
            # Accept only confident selections; the original decision and transcript
            # retain uncertain secondary evidence for a later clarification.
            return PolicyResult(
                outcome="accept",
                scenario_ids=sorted(
                    confident, key=lambda scenario_id: priorities.get(scenario_id) != "urgent"
                ),
                consecutive_low_confidence=0,
                reason="Prioritize confident urgent requests; uncertain secondary intents deferred",
            )
        repairs_exhausted = conversational is None or conversational.repair_attempts >= max(
            2, self.settings.max_unclear_turns - 1
        )
        if low_count >= self.settings.handoff_after and repairs_exhausted and not progress:
            return PolicyResult(
                outcome="handoff",
                scenario_ids=["SC37"],
                consecutive_low_confidence=low_count,
                reason="Operator assistance is required",
            )
        if confidence < self.settings.accept_threshold or "SYS_UNCLEAR" in ids:
            if (
                state.unclear_count + 1 >= self.settings.max_unclear_turns
                and repairs_exhausted
                and not progress
                and decision.conversation_signal != "greeting"
            ):
                return PolicyResult(
                    outcome="handoff",
                    scenario_ids=["SC37"],
                    consecutive_low_confidence=low_count,
                    reason="Clarification limit reached; operator assistance is required",
                )
            return PolicyResult(
                outcome="clarify",
                scenario_ids=["SYS_UNCLEAR"],
                consecutive_low_confidence=low_count,
                reason="Routing requires clarification",
            )
        if decision.is_continuation and state.active_scenario in ids and len(ids) == 1:
            return PolicyResult(
                outcome="continue",
                scenario_ids=ids,
                consecutive_low_confidence=0,
                reason="Continue the active scenario",
            )
        ordered = sorted(ids, key=lambda scenario_id: priorities.get(scenario_id) != "urgent")
        return PolicyResult(
            outcome="accept",
            scenario_ids=ordered,
            consecutive_low_confidence=0,
            reason="Urgent requests first, then spoken order",
        )
