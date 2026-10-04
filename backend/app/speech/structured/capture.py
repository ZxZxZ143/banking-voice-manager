"""Private, bounded read-back and segmented collection, never business-slot storage."""

import re
from dataclasses import dataclass, field
from time import monotonic
from typing import Literal

from app.speech.structured.correction import IdentifierCorrection
from app.speech.structured.normalization import (
    FILLERS,
    PATTERNS,
    REGIONS,
    NormalizedValue,
    _letters,
    digit_candidates,
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
    phase: Literal["confirmation", "segments"]
    candidate: str | None = field(default=None, repr=False)
    prompt: str | None = field(default=None, repr=False)
    parts: list[str] = field(default_factory=list, repr=False)
    repair_used: bool = False
    confirmation_attempts: int = 0
    correction_cycles: int = 0
    clarification_used: bool = False
    pending_edit: IdentifierCorrection | None = field(default=None, repr=False)
    manual_requested: bool = False
    expires_at: float = field(default_factory=lambda: monotonic() + 180, repr=False)


def part_instruction(kind, part):
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
    length = _LENGTHS[kind, part]
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
    values, overflow = digit_candidates(words, _LENGTHS[kind, part])
    values = {v for v in values if len(v) == _LENGTHS[kind, part]}
    if part == "region":
        values &= set(REGIONS)
    if (kind, part) == ("phone", "first"):
        values = {"7" + v[1:] for v in values if v[0] in "78"}
    return NormalizedValue(kind, tuple(sorted(values)), overflow)


def assembled(capture):
    value = "".join(capture.parts)
    if capture.kind == "phone":
        value = "+" + value
    elif capture.kind == "policy_number":
        value = "SQ-" + capture.parts[0][2:] + "-" + capture.parts[1]
    elif capture.kind == "claim_number":
        value = capture.parts[0] + "-" + capture.parts[1]
    return value if re.fullmatch(PATTERNS[capture.kind], value) else None


def capture_question(capture, language):
    kk = language == "kk"
    if capture.phase == "confirmation":
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
            for char in capture.candidate
        )
        return (
            f"Нөмірді тексеріңізші: {readback}. Толық дұрыс па? Иә немесе жоқ деп жауап беріңізші."
            if kk
            else f"Проверьте номер: {readback}. Всё верно целиком? Ответьте «да» или «нет»."
        )
    part = PARTS[capture.kind][len(capture.parts)]
    if part == "prefix":
        return (
            "Тек әріптік префиксті айтыңызшы."
            if kk
            else "Назовите только буквенный префикс номера."
        )
    if part == "letters":
        return (
            "Енді нөмірдің әріптерін жеке айтыңызшы."
            if kk
            else "Теперь назовите только буквы номера, по одной."
        )
    count = _LENGTHS[capture.kind, part]
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
