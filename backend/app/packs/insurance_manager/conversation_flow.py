"""Application-owned request completion and policy context, independent of wording."""

import re

from app.packs.insurance_manager.state import ConversationState

# Only catalog scenarios that establish a relationship by definition belong here.
# App/login help, complaints, callbacks and other contextual requests stay semantic.
NEW_SCENARIOS = {"SC01", "SC02", "SC03", "SC06", "SC07", "SC08", "SC09", "SC10"}
EXISTING_SCENARIOS = {
    "SC04",
    "SC05",
    "SC12",
    "SC13",
    "SC14",
    "SC15",
    "SC16",
    "SC17",
    "SC19",
    "SC20",
    "SC21",
    "SC22",
    "SC24",
    "SC25",
    "SC26",
    "SC27",
    "SC28",
    "SC30",
    "SC39",
}
INFORMATIONAL_SCENARIOS = {"SC18", "SC23", "SC31", "SC33", "SC38", "SC40"}
CONTEXT_SIGNALS = {"acknowledgement", "more_questions", "no_more_questions"}


def scenario_relationship(scenario):
    if scenario in NEW_SCENARIOS:
        return "new"
    if scenario in EXISTING_SCENARIOS:
        return "existing"
    if scenario in INFORMATIONAL_SCENARIOS:
        return "not_applicable"
    return "unknown"


def unfinished_request(state):
    meta = state.conversation
    return bool(
        state.active_scenario
        or state.scenario_stack
        or state.pending_scenarios
        or state.awaiting_confirmation
        or meta
        and (
            meta.expected_slot
            or meta.phase != "wrap_up"
            and (
                meta.policy_relationship in {"new", "existing"}
                or meta.expected_answer_type == "policy_relationship"
            )
        )
    )


def more_questions(language):
    return (
        "Остались ещё вопросы по страхованию?"
        if language == "ru"
        else "Сақтандыру бойынша тағы сұрақтарыңыз бар ма?"
    )


def enter_wrap_up(meta, language):
    meta.phase = "wrap_up"
    meta.expected_slot = None
    meta.expected_answer_type = "more_questions"
    meta.last_question = more_questions(language)
    meta.repair_attempts = 0
    meta.resume_after_risk = False


def remember_relationship(meta, relationship):
    if relationship == "unknown":
        return
    meta.policy_relationship = relationship
    meta.acknowledged_information = [
        item
        for item in meta.acknowledged_information
        if item not in {"existing_policy", "new_policy"}
    ]
    if relationship in {"new", "existing"}:
        meta.acknowledged_information.append(relationship + "_policy")


def update_relationship(previous, state, decision, policy):
    meta = state.conversation
    if meta is None:
        return
    old = previous.conversation
    if old and previous.active_scenario:
        meta.scenario_relationships[previous.active_scenario] = old.policy_relationship
    if old and old.phase == "wrap_up" and decision.conversation_signal not in CONTEXT_SIGNALS:
        # Starting a new request releases the completed request's conversational goal.
        meta.policy_relationship = "unknown"
        meta.acknowledged_information = []
        meta.phase = "discover"
        meta.last_question = None
        meta.expected_answer_type = None
    established = (
        scenario_relationship(state.active_scenario)
        if policy.outcome in {"accept", "continue"} and policy.scenario_ids[0] != "SYS_OUT_OF_SCOPE"
        else "unknown"
    )
    evidence = decision.policy_relationship
    if established in {"new", "existing"}:
        evidence = established
    elif evidence == "unknown":
        evidence = established
    # A slot-only answer cannot erase the relationship established for that task.
    if not (
        evidence == "not_applicable"
        and meta.policy_relationship in {"new", "existing"}
        and (decision.is_continuation or policy.scenario_ids == ["SYS_OUT_OF_SCOPE"])
    ):
        remember_relationship(meta, evidence)
    if meta.policy_relationship == "unknown":
        if "existing_policy" in meta.acknowledged_information:
            remember_relationship(meta, "existing")
        elif "new_policy" in meta.acknowledged_information:
            remember_relationship(meta, "new")
    if state.active_scenario:
        meta.scenario_relationships[state.active_scenario] = meta.policy_relationship


def relationship_choice_allowed(state, decision):
    meta = state.conversation
    return bool(
        meta
        and meta.phase != "wrap_up"
        and meta.policy_relationship == "unknown"
        and not meta.expected_slot
        and decision
        and decision.relationship_needed
        and decision.conversation_signal not in {"greeting", *CONTEXT_SIGNALS}
        and [item.scenario_id for item in decision.scenarios] == ["SYS_UNCLEAR"]
    )


def is_relationship_question(text):
    """Output guard/evaluation only; never classify customer requests using these words."""
    return bool(
        re.search(r"\bнов\w*|\bжаңа\b", text or "", re.I)
        and re.search(
            r"существующ|действующ|имеющ|уже\s+есть|у\s+вас\s+есть|қолданыс|бұрынғы"
            r"|бар\s+полис|(?:полис|сақтандыру)\w*\s+бар",
            text or "",
            re.I,
        )
    )


def discovery_question(state, decision=None):
    ru = state.response_language == "ru"
    meta = state.conversation or ConversationState()
    if relationship_choice_allowed(state, decision):
        return (
            "Вы хотите оформить новую страховку или разобраться с существующей?"
            if ru
            else "Жаңа сақтандыру рәсімдегіңіз келе ме, "
            "әлде қолданыстағы полис бойынша көмек керек пе?"
        )
    if meta.policy_relationship == "existing":
        return (
            "Что нужно уточнить или сделать по вашему полису?"
            if ru
            else "Полисіңіз бойынша нені нақтылау немесе жасау керек?"
        )
    if meta.policy_relationship == "new":
        return "Что вы хотите застраховать?" if ru else "Нені сақтандырғыңыз келеді?"
    return (
        "Расскажите, пожалуйста, с чем хотите разобраться?"
        if ru
        else "Қандай мәселе бойынша көмектесе аламын?"
    )
