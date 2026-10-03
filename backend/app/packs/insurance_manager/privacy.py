"""Insurance presentation redaction; original identifiers stay in local business state."""

import re

from app.speech.structured.normalization import HUNDREDS, LETTERS, NUMBERS, TENS

SENSITIVE_SLOTS = {
    "phone",
    "iin",
    "drivers_iin",
    "new_driver_iin",
    "policy_number",
    "claim_number",
    "new_value",
    "vehicle_plate",
    "culprit_vehicle_plate",
}


def redact_local_phone(value, phone):
    """Before provider transport: hide every literal phone, including unknown callers."""
    if isinstance(value, dict):
        return {key: redact_local_phone(item, phone) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_local_phone(item, phone) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"(?<!\d)(?:\+?[78](?:[\s()-]*\d){10}|\d(?:[\s()-]*\d){9})(?!\d)",
            "[локальный телефон получен]",
            value,
        )
    return value


def redact_text(text: str, slots: dict | None = None) -> str:
    tokens = re.findall(r"\w+", text.casefold())
    number_lexicon = {**NUMBERS, **TENS, **HUNDREDS, "жүз": 100}
    spoken_size = sum(len(str(number_lexicon[word])) for word in tokens if word in number_lexicon)
    literal_size = sum(len(word) for word in tokens if word.isascii() and word.isdigit())
    letter_count = sum(
        1 if word in LETTERS else len(word) if re.fullmatch(r"[a-zавсенкмортху]{1,3}", word) else 0
        for word in tokens
    )
    if spoken_size and spoken_size + literal_size >= 3 and letter_count >= 2:
        return "[произнесённый номер скрыт]"
    if spoken_size >= 6 or (spoken_size and spoken_size + literal_size >= 6):
        return "[произнесённый номер скрыт]"
    number_words = {
        "ноль",
        "нуль",
        "один",
        "одна",
        "два",
        "две",
        "три",
        "четыре",
        "пять",
        "шесть",
        "семь",
        "восемь",
        "девять",
        "нөл",
        "бір",
        "екі",
        "үш",
        "төрт",
        "бес",
        "алты",
        "жеті",
        "сегіз",
        "тоғыз",
    }
    if sum(word.casefold() in number_words for word in re.findall(r"\w+", text)) >= 6:
        return "[произнесённый номер скрыт]"
    for name, value in (slots or {}).items():
        if name in SENSITIVE_SLOTS:
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, str) and item:
                    text = re.sub(re.escape(item), "[номер скрыт]", text, flags=re.I)
    text = re.sub(r"(?<!\d)(?:\+?\d[\s()-]*){10,12}(?!\d)", "[номер скрыт]", text)
    text = re.sub(r"\b\d{3}(?:[\s-]*[A-ZА-Я]){2,3}[\s-]*\d{2}\b", "[номер скрыт]", text, flags=re.I)
    return re.sub(r"\b[A-Z]{2,}(?:[\s-]+[A-Z]+)*[\s-]+\d{3,}\b", "[номер скрыт]", text, flags=re.I)


def safe_slots(slots: dict) -> dict:
    return {key: "[получено]" if key in SENSITIVE_SLOTS else value for key, value in slots.items()}
