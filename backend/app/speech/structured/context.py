from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExpectedKind = Literal[
    "none", "phone", "iin", "policy_number", "claim_number", "vehicle_plate", "region_code"
]
SLOT_KINDS = {
    name: name for name in ("phone", "iin", "policy_number", "claim_number", "vehicle_plate")
}
SLOT_KINDS["region"] = "region_code"
SLOT_KINDS.update(drivers_iin="iin", new_driver_iin="iin", culprit_vehicle_plate="vehicle_plate")

_PROMPTS = {
    "none": "Customer speech in Russian and Kazakh, sometimes mixed.",
    "phone": (
        "Kazakhstan phone number, +7 or domestic 8 followed by ten digits. "
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


class TranscriptionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    language_hint: Literal["ru", "kk", "mixed"] | None = None
    expected_kind: ExpectedKind = "none"
    prompt: str = Field(default=_PROMPTS["none"], max_length=500)
    keywords: tuple[str, ...] = Field(default=(), max_length=10)
    accuracy_mode: Literal["medium", "high"] = "medium"
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
        prompt=_PROMPTS[kind],
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
                "prompt": part_instruction(capture.kind, part),
            }
        )
    if capture and capture.slot == slot and capture.phase == "confirmation":
        # Yes/no needs no identifier hints and no second paid transcription.
        return context_for_slot(None, language)
    return context
