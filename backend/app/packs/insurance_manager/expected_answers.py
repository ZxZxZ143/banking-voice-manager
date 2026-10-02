"""Literal identifier normalization for the field already requested, never intent routing."""

import re

_DIGITS = {
    "ноль": "0",
    "нуль": "0",
    "один": "1",
    "одна": "1",
    "два": "2",
    "две": "2",
    "три": "3",
    "четыре": "4",
    "пять": "5",
    "шесть": "6",
    "семь": "7",
    "восемь": "8",
    "девять": "9",
    "нөл": "0",
    "бір": "1",
    "екі": "2",
    "үш": "3",
    "төрт": "4",
    "бес": "5",
    "алты": "6",
    "жеті": "7",
    "сегіз": "8",
    "тоғыз": "9",
}


def expected_trip_duration(text: str, state) -> int | None:
    """Remember a literal duration while collecting dates for an authorized travel flow."""
    if (
        state.active_scenario != "SC06"
        or not state.conversation
        or state.conversation.expected_slot not in {"trip_start", "trip_end"}
    ):
        return None
    match = re.fullmatch(
        r"(?:на\s+)?(\d{1,3}|\w+)\s+"
        r"(день|дня|дней|неделя|недели|недель|неделю|күн|күнге|апта|аптаға)[.!]?",
        text.strip().casefold(),
    )
    if not match:
        return None
    count, unit = match.groups()
    count = int(count) if count.isdigit() else int(_DIGITS.get(count, "0"))
    days = count * (7 if unit.startswith(("недел", "апта")) else 1)
    return days if 1 <= days <= 365 else None


def expected_identifier(text: str, state, definitions) -> tuple[str, str] | None:
    name = state.conversation.expected_slot if state.conversation else None
    if name not in {"phone", "iin", "policy_number", "claim_number"}:
        return None
    definition = definitions[name]
    candidates = []
    if name in {"phone", "iin"}:
        candidates = [re.sub(r"[\s()+-]", "", item) for item in re.findall(r"\+?\d[\d ()-]*", text)]
        words = re.findall(r"\w+", text.casefold())
        if words and all(word in _DIGITS for word in words):
            candidates.append("".join(_DIGITS[word] for word in words))
    else:
        candidates = re.findall(r"\b(?:SQ-[A-Z]+|CL)-\d+\b", text.upper())
    valid = set()
    for value in candidates:
        if name == "phone" and len(value) == 11 and value[0] in {"7", "8"}:
            value = "+7" + value[1:]
        if re.fullmatch(definition.pattern, value):
            valid.add(value)
    return (name, valid.pop()) if len(valid) == 1 else None
