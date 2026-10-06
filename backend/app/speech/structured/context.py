from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExpectedKind = Literal[
    "none", "phone", "iin", "policy_number", "claim_number", "vehicle_plate", "region_code"
]
PhoneInputStyle = Literal["domestic_8", "international_7", "national_10"]
SLOT_KINDS = {
    name: name for name in ("phone", "iin", "policy_number", "claim_number", "vehicle_plate")
}
SLOT_KINDS["region"] = "region_code"
SLOT_KINDS.update(drivers_iin="iin", new_driver_iin="iin", culprit_vehicle_plate="vehicle_plate")

_LANGUAGE_PROMPT = (
    "Customer speech is primarily Russian and Kazakh, sometimes mixed. "
    "Preserve the original language and script. Do not translate speech into English. "
    "English may occur when genuinely spoken, including product names or Latin identifiers."
)
CONFIRMATION_KEYWORDS = (
    "да",
    "нет",
    "верно",
    "неверно",
    "правильно",
    "неправильно",
    "иә",
    "жоқ",
    "дұрыс",
    "дұрыс емес",
)
_CONFIRMATION_PROMPT = (
    "Transcribe this short confirmation exactly in Russian or Kazakh, sometimes mixed. "
    "Preserve the spoken language and script; do not translate into English. "
    "Preserve да, нет, иә, жоқ exactly when spoken. If uncertain, do not substitute English "
    "Yes or No. Preserve short corrections: digits, Latin letters and positions. "
    "Do not invent omitted characters."
)
_PROMPTS = {
    "none": _LANGUAGE_PROMPT,
    "phone": (
        "Kazakhstan phone: +7 or domestic 8 followed by ten digits, "
        "or a national ten-digit number beginning with 7. "
        "Preserve every spoken digit, individually or in Russian/Kazakh groups. "
        "Do not guess missing digits."
    ),
    "iin": (
        "Kazakhstan IIN: twelve digits. Preserve the exact spoken sequence, "
        "individually or in Russian/Kazakh groups, including zeros. "
        "Do not guess missing digits."
    ),
    "policy_number": (
        "Insurance policy: SQ, OGPO/CASCO/TRVL/PROP/NS/DMS, six digits. "
        "Preserve spoken Latin letters, hyphens and all digits exactly. Russian/Kazakh speech."
    ),
    "claim_number": (
        "Insurance claim: CL followed by six digits. "
        "Preserve spoken Latin letters and every digit exactly. Russian/Kazakh speech."
    ),
    "vehicle_plate": (
        "Kazakhstan plate: three digits, two or three Latin letters, two region digits. "
        "Preserve letters and digits exactly, including zeros. Russian/Kazakh speech."
    ),
    "region_code": (
        "Vehicle registration region: city/region name or Kazakhstan code 01 to 20. "
        "Preserve spoken digits, including zeros. Russian/Kazakh speech."
    ),
}


def language_prompt(prompt: str, language: str | None) -> str:
    if language in {"ru", "kk"}:
        preferred = "Russian" if language == "ru" else "Kazakh"
        prompt += f" Prefer {preferred} for ambiguous sounds only; preserve clearly spoken RU/KK."
    return prompt


class TranscriptionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    language_hint: Literal["ru", "kk", "mixed"] | None = None
    expected_kind: ExpectedKind = "none"
    prompt: str = Field(default=_PROMPTS["none"], max_length=500)
    keywords: tuple[str, ...] = Field(default=(), max_length=10)
    accuracy_mode: Literal["medium", "high"] = "medium"
    confirmation_kind: ExpectedKind = "none"
    phone_input_style: PhoneInputStyle | None = None
    capture_part: Literal[
        "whole", "first", "middle", "last", "prefix", "digits", "letters", "region"
    ] = "whole"


def context_for_slot(slot: str | None, language: str | None = None) -> TranscriptionContext:
    kind = SLOT_KINDS.get(slot, "none")
    keywords = (
        ("SQ", "OGPO", "CASCO", "TRVL", "PROP", "NS", "DMS")
        if kind == "policy_number"
        else ("CL",)
        if kind == "claim_number"
        else ()
    )
    return TranscriptionContext(
        language_hint=language if language in {"ru", "kk", "mixed"} else None,
        expected_kind=kind,
        prompt=language_prompt(_PROMPTS[kind], language),
        keywords=keywords,
        accuracy_mode="medium" if kind == "none" else "high",
    )


def kind_for_slot(slot, contact_field=None):
    return (
        "phone"
        if slot == "new_value" and contact_field == "phone"
        else SLOT_KINDS.get(slot, "none")
    )


def context_for_capture(slot, language, capture=None, contact_field=None):
    context = context_for_slot(kind_for_slot(slot, contact_field), language)
    if slot == "region":
        context = context_for_slot(slot, language)
    if capture and capture.slot == slot and capture.phase == "segments":
        from app.speech.structured.capture import PARTS, part_instruction

        context = context_for_slot(capture.kind, language)
        part = PARTS[capture.kind][len(capture.parts)]
        return context.model_copy(
            update={
                "capture_part": part,
                "prompt": part_instruction(capture.kind, part, capture.phone_input_style),
                "phone_input_style": capture.phone_input_style,
            }
        )
    if (
        capture
        and capture.slot == slot
        and capture.phase in {"confirmation", "segment_confirmation"}
    ):
        # Only public vocabulary, never the pending identifier or read-back.
        return context_for_slot(None, language).model_copy(
            update={
                "confirmation_kind": capture.kind,
                "accuracy_mode": "high",
                "prompt": language_prompt(_CONFIRMATION_PROMPT, language),
                "keywords": CONFIRMATION_KEYWORDS,
            }
        )
    return context
