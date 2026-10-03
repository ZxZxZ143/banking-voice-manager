"""Finite, application-owned identification. Only corrected values reopen a failed path."""

from hashlib import sha256

from app.packs.insurance_manager.tools.capabilities import ActionCapabilities
from app.packs.insurance_manager.tools.read_only import find_client, get_claim, get_policy

IDENTIFIERS = {"phone", "iin", "policy_number", "claim_number", "vehicle_plate"}


def remember(items, item):
    if item not in items:
        items.append(item)


def fingerprint(action, values):
    return sha256(repr((action, sorted(values.items()))).encode()).hexdigest()


def can_ask(state, name):
    memory = state.identification
    return name not in {*memory.unavailable_fields, *memory.failed_fields}


def lookup_exhausted(state, scenario, capabilities, actions=()):
    memory = state.identification
    memory.exhausted = True
    # Retain the safe summary before the processor changes terminal status.
    summary = ActionCapabilities.make_summary(
        state, scenario, memory.completed_read_only_checks, "lookup_exhausted", "operator_review"
    )
    state.manager_summary = summary
    return dict(
        text=(
            "По доступным данным не удалось однозначно найти нужную запись. "
            "Ваш вопрос и собранные сведения сохранены для специалиста, чтобы не пришлось "
            "повторять их. Подготовлена передача на проверку оператору. "
            "В этой демонстрации подключение оператора не выполняется."
            if state.response_language == "ru"
            else "Қолда бар деректерден қажетті жазбаны бірмәнді таба алмадым. "
            "Қайта айтудың қажеті болмас үшін сұрағыңыз бен жиналған мәліметтер маманға "
            "сақталды. Оператордың тексеруіне беру дайындалды. "
            "Бұл демонстрацияда оператор қосылмайды."
        ),
        actions=list(actions),
        source_keys=[],
        completed=False,
        handoff=True,
        manager_summary=summary,
    )


def lookup_client(state, backend, supplied=()):
    if state.client_id and state.identification.successful_field:
        return state.client_id, None, []
    state.client_id = None
    memory = state.identification
    actions = []
    available = {
        name: state.slots[name]
        for name in ("phone", "iin")
        if state.slots.get(name) and name not in memory.unavailable_fields
    }
    # Simultaneous contradictory identifiers must not establish ownership.
    candidates = (
        [available] if len(available) == 2 else [{name: value} for name, value in available.items()]
    )
    for values in candidates:
        key = fingerprint("find_client", values)
        if key in memory.failed_attempts:
            continue
        for name in values:
            remember(memory.attempted_fields, name)
            remember(state.client_lookup_attempts, name)
        result = find_client(backend, **values)
        actions.append("find_client")
        remember(memory.completed_read_only_checks, "find_client")
        if result.success:
            state.client_id = result.data["client_id"]
            memory.successful_field = next(iter(values))
            return state.client_id, None, actions
        memory.failed_attempts.append(key)
        if len(values) == 2:
            # A conflicting pair failed, not either identifier on its own. One explicit
            # correction can remove the conflict; never silently retry either side.
            remember(memory.failed_fields, "iin")
            remember(memory.requested_fields, "phone")
            return (
                None,
                dict(
                    text="Данные не совпали. Уточните, какой телефон использовать?"
                    if state.response_language == "ru"
                    else "Деректер сәйкес келмеді. Қай телефонды қолдану керек?",
                    actions=actions,
                    source_keys=[],
                    completed=False,
                    handoff=False,
                    expected_slot="phone",
                ),
                actions,
            )
        for name in values:
            remember(memory.failed_fields, name)
    for name in ("phone", "iin"):
        if len(available) == 2:
            continue
        if can_ask(state, name):
            remember(memory.requested_fields, name)
            return (
                None,
                dict(
                    text=(
                        "Назовите, пожалуйста, номер телефона?"
                        if name == "phone"
                        else "Можно проверить по ИИН. Назовите его, пожалуйста?"
                    )
                    if state.response_language == "ru"
                    else (
                        "Телефон нөмірін айта аласыз ба?"
                        if name == "phone"
                        else "ЖСН арқылы тексеруге болады. ЖСН-ді айта аласыз ба?"
                    ),
                    actions=actions,
                    source_keys=[],
                    completed=False,
                    handoff=False,
                    expected_slot=name,
                ),
                actions,
            )
    return None, None, actions


def lookup_record(state, backend, identifier):
    """Owned records only; a plate or record number never establishes ownership."""
    action = "get_policy" if identifier == "policy_number" else "get_claim"
    values = {"client_id": state.client_id, identifier: state.slots.get(identifier)}
    memory = state.identification
    key = fingerprint(action, values)
    if key in memory.failed_attempts:
        return None, []
    remember(memory.attempted_fields, identifier)
    result = (get_policy if identifier == "policy_number" else get_claim)(backend, **values)
    remember(memory.completed_read_only_checks, action)
    if result.success:
        return result.data, [action]
    memory.failed_attempts.append(key)
    # An ambiguous automatic lookup is not a failed provided record number.
    if values[identifier]:
        remember(memory.failed_fields, identifier)
    return None, [action]
