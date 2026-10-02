"""Bounded lookup across at most two identifier types; unknown is not invalid formatting."""

from app.packs.insurance_manager.tools.read_only import find_client


def lookup_client(state, backend, supplied=()):
    ru = state.response_language == "ru"
    if state.client_id:
        return state.client_id, None
    attempted = state.client_lookup_attempts
    if state.slots.get("phone") and state.slots.get("iin") and not attempted:
        result = find_client(backend, phone=state.slots["phone"], iin=state.slots["iin"])
        if result.success:
            state.client_id = result.data["client_id"]
            return state.client_id, None
        # Contradictory supplied identifiers never establish ownership. Ask for one correction.
        attempted.append("iin")
        return None, dict(
            text="По этим данным запись не нашлась. Уточните телефон, пожалуйста."
            if ru
            else "Бұл деректермен жазба табылмады. Телефонды нақтылаңызшы.",
            actions=["find_client"],
            source_keys=[],
            completed=False,
            handoff=False,
            expected_slot="phone",
        )
    available = [
        k for k in ("phone", "iin") if state.slots.get(k) and (k not in attempted or k in supplied)
    ]
    for name in available[: max(0, 2 - len(attempted))]:
        attempted.append(name)
        result = find_client(backend, **{name: state.slots[name]})
        if result.success:
            state.client_id = result.data["client_id"]
            return state.client_id, None
    if len(attempted) < 2:
        name = "iin" if "phone" in attempted else "phone"
        message = (
            (
                "По этому номеру запись не нашлась. Если удобно, назовите ИИН — "
                "попробую проверить по нему."
            )
            if ru and name == "iin"
            else (
                "По этому ИИН запись не нашлась. Можно проверить по номеру "
                "телефона — назовите его, пожалуйста."
            )
            if ru
            else "Жазба табылмады. ЖСН-ді айтыңызшы, сол арқылы тексеріп көрейін."
            if name == "iin"
            else "Жазба табылмады. Телефон нөмірін айтып бере аласыз ба?"
        )
        return None, dict(
            text=message,
            fact_text=(
                "По этим данным запись в доступной базе не нашлась."
                if ru
                else "Қолжетімді қорда бұл деректермен жазба табылмады."
            ),
            actions=["find_client"],
            source_keys=[],
            completed=False,
            handoff=False,
            expected_slot=name,
        )
    return None, None
