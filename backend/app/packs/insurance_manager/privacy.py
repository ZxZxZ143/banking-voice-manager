"""Insurance presentation redaction; original identifiers stay in local business state."""

import re

SENSITIVE_SLOTS = {
    "phone",
    "iin",
    "drivers_iin",
    "new_driver_iin",
    "policy_number",
    "claim_number",
    "new_value",
}


def redact_text(text: str, slots: dict | None = None) -> str:
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
    return re.sub(r"\b[A-Z]{2,}(?:-[A-Z]+)*-\d{3,}\b", "[номер скрыт]", text, flags=re.I)


def safe_slots(slots: dict) -> dict:
    return {key: "[получено]" if key in SENSITIVE_SLOTS else value for key, value in slots.items()}
