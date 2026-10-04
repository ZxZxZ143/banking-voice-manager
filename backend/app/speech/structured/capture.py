"""Private, bounded read-back and segmented collection, never business-slot storage."""

import re
from dataclasses import dataclass, field
from time import monotonic
from typing import Literal

from app.speech.structured.context import PhoneInputStyle
from app.speech.structured.correction import IdentifierCorrection
from app.speech.structured.normalization import (
    FILLERS,
    PATTERNS,
    REGIONS,
    NormalizedValue,
    _letters,
    digit_candidates,
    normalize_spoken,
    recognize_expected,
)
from app.speech.structured.policy import AcceptedStructuredValue, RecognitionOutcome

PARTS = {
    "phone": ("first", "middle", "last"),
    "iin": ("first", "last"),
    "policy_number": ("prefix", "digits"),
    "claim_number": ("prefix", "digits"),
    "vehicle_plate": ("digits", "letters", "region"),
}
_LENGTHS = {
    ("phone", "first"): 4,
    ("phone", "middle"): 3,
    ("phone", "last"): 4,
    ("iin", "first"): 6,
    ("iin", "last"): 6,
    ("policy_number", "digits"): 6,
    ("claim_number", "digits"): 6,
    ("vehicle_plate", "digits"): 3,
    ("vehicle_plate", "region"): 2,
}


@dataclass
class StructuredCapture:
    slot: str
    kind: str
    scenario: str
    phase: Literal["confirmation", "segments", "segment_confirmation"]
    candidate: str | None = field(default=None, repr=False)
    prompt: str | None = field(default=None, repr=False)
    parts: list[str] = field(default_factory=list, repr=False)
    segment_candidate: str | None = field(default=None, repr=False)
    segment_attempts: dict[str, int] = field(default_factory=dict, repr=False)
    phone_input_style: PhoneInputStyle | None = None
    repair_used: bool = False
    confirmation_attempts: int = 0
    correction_cycles: int = 0
    clarification_used: bool = False
    pending_edit: IdentifierCorrection | None = field(default=None, repr=False)
    manual_requested: bool = False
    expires_at: float = field(default_factory=lambda: monotonic() + 180, repr=False)


def phone_style(value):
    digits = value.lstrip("+")
    if len(digits) == 10:
        return "national_10"
    if len(digits) == 11 and digits[0] in "78":
        return "domestic_8" if digits[0] == "8" else "international_7"
    return None


def part_length(kind, part, style=None):
    return 3 if (kind, part, style) == ("phone", "first", "national_10") else _LENGTHS[kind, part]


def part_instruction(kind, part, style=None):
    if part == "prefix":
        return (
            "Transcribe only the spoken policy prefix SQ plus product letters."
            if kind == "policy_number"
            else "Transcribe only the spoken claim prefix letters CL."
        )
    if part == "letters":
        return (
            "Transcribe exactly two or three Latin vehicle plate letters. "
            "Do not add or omit a letter."
        )
    length = part_length(kind, part, style)
    return (
        f"Transcribe only {length} digits spoken individually in Russian or Kazakh. "
        "Preserve zeros. Do not fill missing digits."
    )


def recognize_context(text, context):
    if context.capture_part == "whole":
        return recognize_expected(text, context.expected_kind)
    kind, part = context.expected_kind, context.capture_part
    if kind not in PARTS or part not in PARTS[kind] or len(text) > 300:
        return NormalizedValue(kind)
    words = re.findall(r"[0-9]+|[^\W\d_]+", text.casefold().replace("ё", "е"))
    words = [w for w in words if w not in (FILLERS - {"и"})]
    if part in {"letters", "prefix"}:
        value = _letters(words)
        pattern = (
            "[A-Z]{2,3}"
            if part == "letters"
            else "CL"
            if kind == "claim_number"
            else "SQ(?:OGPO|CASCO|TRVL|PROP|NS|DMS)"
        )
        return NormalizedValue(kind, (value,) if value and re.fullmatch(pattern, value) else ())
    length = part_length(kind, part, context.phone_input_style)
    values, overflow = digit_candidates(words, length)
    values = {v for v in values if len(v) == length}
    if part == "region":
        values &= set(REGIONS)
    if (kind, part) == ("phone", "first"):
        # Drafts/read-back preserve spoken 8. Canonical +7 is only for final admission.
        values = {
            v
            for v in values
            if v[0] in ("7" if context.phone_input_style == "national_10" else "78")
        }
    return NormalizedValue(kind, tuple(sorted(values)), overflow)


def assembled(capture):
    value = "".join(capture.parts)
    if capture.kind == "phone":
        return value if normalize_spoken(value, "phone").accepted else None
    elif capture.kind == "policy_number":
        value = "SQ-" + capture.parts[0][2:] + "-" + capture.parts[1]
    elif capture.kind == "claim_number":
        value = capture.parts[0] + "-" + capture.parts[1]
    return value if re.fullmatch(PATTERNS[capture.kind], value) else None


def capture_question(capture, language):
    kk = language == "kk"
    if capture.phase in {"confirmation", "segment_confirmation"}:
        # Full read-back is only in the caller response. Public projections redact it.
        digits = (
            "нөл бір екі үш төрт бес алты жеті сегіз тоғыз"
            if kk
            else "ноль один два три четыре пять шесть семь восемь девять"
        ).split()
        letters = dict(
            zip(
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                (
                    "эй",
                    "би",
                    "си",
                    "ди",
                    "и",
                    "эф",
                    "джи",
                    "эйч",
                    "ай",
                    "джей",
                    "кей",
                    "эл",
                    "эм",
                    "эн",
                    "оу",
                    "пи",
                    "кью",
                    "ар",
                    "эс",
                    "ти",
                    "ю",
                    "ви",
                    "дабл ю",
                    "экс",
                    "уай",
                    "зэд",
                ),
                strict=True,
            )
        )
        readback = ", ".join(
            digits[int(char)]
            if char.isdigit()
            else letters.get(char, "плюс" if char == "+" else "дефис")
            for char in (
                capture.segment_candidate
                if capture.phase == "segment_confirmation"
                else capture.candidate
            )
        )
        if capture.phase == "segment_confirmation":
            return (
                f"Мен естігенім: {readback}. Дұрыс па?" if kk else f"Я услышал: {readback}. Верно?"
            )
        return (
            f"Нөмірді тексеріңізші: {readback}. Толық дұрыс па? Иә немесе жоқ деп жауап беріңізші."
            if kk
            else f"Проверьте номер: {readback}. Всё верно целиком? Ответьте «да» или «нет»."
        )
    part = PARTS[capture.kind][len(capture.parts)]
    retry = bool(capture.segment_attempts.get(part))
    if part == "prefix":
        if kk:
            return (
                "Тек әріптік префиксті қайта айтыңызшы."
                if retry
                else "Тек әріптік префиксті айтыңызшы."
            )
        return (
            "Повторите только буквенный префикс номера."
            if retry
            else "Назовите только буквенный префикс номера."
        )
    if part == "letters":
        if kk:
            return (
                "Нөмірдің тек әріптерін қайта айтыңызшы."
                if retry
                else "Енді нөмірдің әріптерін жеке айтыңызшы."
            )
        return (
            "Повторите только буквы номера, по одной."
            if retry
            else "Теперь назовите только буквы номера, по одной."
        )
    count = part_length(capture.kind, part, capture.phone_input_style)
    label = (
        ("алғашқы" if part == "first" else "соңғы" if part in {"last", "region"} else "келесі")
        if kk
        else (
            "первые"
            if part == "first"
            else "последние"
            if part in {"last", "region"}
            else "следующие"
        )
    )
    if capture.segment_attempts.get(part):
        return (
            f"Тек {label} {count} цифрды қайтадан жеке айтыңызшы."
            if kk
            else f"Повторите, пожалуйста, только {label} {count} цифры, по одной."
        )
    return (
        f"Нөмірдің {label} {count} цифрын жеке айтыңызшы."
        if kk
        else f"Назовите {label} {count} цифры номера, по одной."
    )


def confirmation_answer(text):
    text = re.sub(r"[.!?,«»]", "", text.casefold()).replace("ё", "е").strip()
    if text in {
        "да",
        "да верно",
        "да все верно",
        "все верно",
        "верно",
        "подтверждаю",
        "иә",
        "иә дұрыс",
        "дұрыс",
        "растаймын",
    }:
        return True
    if text in {
        "нет",
        "неверно",
        "не верно",
        "нет неверно",
        "неправильно",
        "жоқ",
        "дұрыс емес",
        "жоқ дұрыс емес",
    }:
        return False
    return None


def accepted_result(speech, kind, value, method):
    from app.speech.structured.recognition import RecognitionResult

    if kind == "phone":
        normalized = normalize_spoken(value, "phone")
        if not normalized.accepted:
            raise ValueError("Cannot admit an incomplete phone")
        value = normalized.value
    return RecognitionResult(
        speech.metadata.model_copy(
            update={
                "accepted": True,
                "outcome": RecognitionOutcome.accepted,
                "verification_method": method,
            }
        ),
        kind=kind,
        accepted_value=AcceptedStructuredValue(kind, value, method),
    )
