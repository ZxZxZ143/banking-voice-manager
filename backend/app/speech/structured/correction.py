"""Local compositional RU/KK correction grammar; never an admission authority.

The parser receives only the reply and identifier kind. The application resolves the
edit against private state, checks uniqueness and validates the original schema.
Unknown/multiple edits fail closed; no model invents a replacement character.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app.speech.structured.normalization import (
    DIGITS,
    LETTERS,
    PATTERNS,
    REGIONS,
    VISUAL,
    normalize_spoken,
)


@dataclass(frozen=True)
class IdentifierCorrection:
    target: Literal["digit", "letter", "fragment", "whole"] = "fragment"
    old_fragment: str | None = field(default=None, repr=False)
    new_fragment: str | None = field(default=None, repr=False)
    position: int | None = None  # One-based in the named segment; -1 = last.
    segment: Literal["digits", "letters", "region"] | None = None


@dataclass(frozen=True)
class StructuredConfirmationResponse:
    kind: Literal["confirm", "reject", "correction", "unrelated"]
    correction: IdentifierCorrection | None = field(default=None, repr=False)


_ORDINALS = (
    (r"перв\w*|бірінші|алғашқы", 1),
    (r"втор\w*|екінші", 2),
    (r"трет\w*|үшінші", 3),
    (r"четверт\w*|төртінші", 4),
    (r"пят(?:ый|ая|ое|ую|ой|ого|ому|ом)|бесінші", 5),
    (r"шест(?:ой|ая|ое|ую|ого|ому|ом)|алтыншы", 6),
    (r"седьм\w*|жетінші", 7),
    (r"восьм\w*|сегізінші", 8),
    (r"девят(?:ый|ая|ое|ую|ой|ого|ому|ом)|тоғызыншы", 9),
    (r"десят(?:ый|ая|ое|ую|ой|ого|ому|ом)|оныншы", 10),
    (r"одиннадцат\w*|онбірінші", 11),
    (r"двенадцат\w*|онекінші", 12),
    (r"последн\w*|соңғы|ақырғы", -1),
)
_DIGIT_NOUNS = {
    "нул": "0",
    "единиц": "1",
    "двойк": "2",
    "тройк": "3",
    "четверк": "4",
    "пятерк": "5",
    "шестерк": "6",
    "семерк": "7",
    "восьмерк": "8",
    "девятк": "9",
}
_YES = {"да", "верно", "правильно", "подтверждаю", "иә", "дұрыс", "растаймын"}
_NO = {"нет", "неверно", "неправильно", "жоқ", "емес"}
_SOFT = {"все", "всё", "целиком", "полностью", "совершенно", "точно", "бәрі", "толық"}
_CUES = r"\b(вместо|замен\w*|исправ\w*|не|только|кроме|сказали|орнына|емес|тек|өзгерт\w*)\b"


def parse_confirmation(text: str, kind: str) -> StructuredConfirmationResponse:
    if len(text) > 500:
        return StructuredConfirmationResponse("unrelated")
    text = text.casefold().replace("ё", "е").strip()
    matches = list(re.finditer(r"[0-9]+|[^\W\d_]+", text))
    tokens = [m.group() for m in matches]
    # Whole replacements may have a rejection prefix. Normalize only within the
    # source schema, never reinterpret another identifier type as this one.
    replacement = re.sub(r"^(?:нет|неверно|жоқ)[\s,.:;-]*", "", text)
    full = normalize_spoken(replacement, kind)
    if full.accepted:
        return StructuredConfirmationResponse(
            "correction", IdentifierCorrection("whole", new_fragment=full.value)
        )
    position = None
    ordinal_indices = set()
    positions = []
    for index, token in enumerate(tokens):
        for pattern, value in _ORDINALS:
            if re.fullmatch(pattern, token):
                positions.append(value)
                ordinal_indices.add(index)
                break
    if len(positions) > 1:
        return StructuredConfirmationResponse("correction", IdentifierCorrection())
    if positions:
        position = positions[0]
    letter = bool(re.search(r"\b(?:букв\w*|әріп\w*)\b", text))
    digit = bool(re.search(r"\b(?:цифр\w*|сан\w*)\b", text))
    region = bool(re.search(r"\b(?:регион\w*|өңір\w*|аймақ\w*)\b", text))
    cue = bool(re.search(_CUES, text)) or position is not None
    if not cue:
        if set(tokens) - _SOFT <= _YES and set(tokens) & _YES:
            return StructuredConfirmationResponse("confirm")
        if set(tokens) <= _NO | {"дұрыс", "не", "верно"} and set(tokens) & (_NO | {"не"}):
            return StructuredConfirmationResponse("reject")
        return StructuredConfirmationResponse("unrelated")
    # Negative-only answers are rejection, never an edit or affirmative.
    if set(tokens) <= _NO | {"дұрыс", "не", "верно"}:
        return StructuredConfirmationResponse("reject")
    groups = []
    last_index = -2
    for index, token in enumerate(tokens):
        if index in ordinal_indices:
            continue
        value = str(DIGITS[token]) if token in DIGITS else None
        if value is None and token.isascii() and token.isdigit():
            value = token
        if value is None:
            value = next((v for stem, v in _DIGIT_NOUNS.items() if token.startswith(stem)), None)
        # 'а' is a conjunction after a negated fragment. Else it can explicitly
        # name the Cyrillic A. 'и' inside prose must never become an invented E.
        conjunction = token in {"а", "и"} and groups and not letter and len(tokens) > 2
        if value is None and not digit and not region and not conjunction:
            value = LETTERS.get(token)
            visual = token.upper().translate(VISUAL)
            if value is None and re.fullmatch(r"[A-Z]", visual):
                value = visual
            if token == "б":
                value = "B"
            if token == "д":
                value = "D"
        # Always treat standalone 'а' between two values as a grammar separator.
        if token == "а" and groups and index + 1 < len(tokens):
            value = None
        if value is not None:
            if (
                index == last_index + 1
                and text[matches[last_index].end() : matches[index].start()].isspace()
            ):
                groups[-1] += value
            else:
                groups.append(value)
            last_index = index
    target = "letter" if letter else "digit" if digit else "fragment"
    segment = "region" if region else "letters" if letter else "digits" if digit else None
    # Spoken replacement has no reliable punctuation in an ASR final. Two
    # explicitly supplied atoms after a replacement operator remain old/new.
    # This is grammar, independent of the candidate's contents or test phrases.
    if len(groups) == 1 and re.search(r"\b(?:вместо|замени\w*|орнына)\b", text):
        width = 2 if region else 1
        if len(groups[0]) == width * 2:
            groups = [groups[0][:width], groups[0][width:]]
    if len(groups) == 2:
        old, new = groups
    elif len(groups) == 1 and (position is not None or region):
        old, new = None, groups[0]
    else:
        old, new = None, None
    if new and target == "fragment" and not region:
        if new.isdigit() and (old is None or old.isdigit()):
            target, segment = "digit", "digits"
        elif new.isalpha() and (old is None or old.isalpha()):
            target, segment = "letter", "letters"
    return StructuredConfirmationResponse(
        "correction", IdentifierCorrection(target, old, new, position, segment)
    )


def apply_correction(candidate: str, kind: str, edit: IdentifierCorrection) -> str | None:
    """Return one minimal source-valid edit, or None; repeated fragments never guess."""
    new = edit.new_fragment
    if not new:
        return None
    if edit.target == "whole":
        updated = new
    else:
        if edit.segment == "region":
            if kind != "vehicle_plate":
                return None
            indices = list(range(len(candidate) - 2, len(candidate)))
        elif edit.segment == "letters" or edit.target == "letter":
            indices = [i for i, c in enumerate(candidate) if c.isalpha()]
        elif edit.segment == "digits" or edit.target == "digit":
            indices = [i for i, c in enumerate(candidate) if c.isdigit()]
        else:
            indices = list(range(len(candidate)))
        if edit.position is not None:
            index = len(indices) - 1 if edit.position == -1 else edit.position - 1
            if not 0 <= index < len(indices) or len(new) != 1:
                return None
            starts = [indices[index]]
            width = 1
        else:
            fragment = edit.old_fragment
            if fragment is None and edit.segment == "region":
                fragment = candidate[-2:]
            if not fragment or len(fragment) != len(new):
                return None
            width = len(fragment)
            starts = [
                i
                for i in indices
                if candidate[i : i + width] == fragment
                and all(j in indices for j in range(i, i + width))
            ]
        if len(starts) != 1:
            return None
        start = starts[0]
        if edit.old_fragment is not None and candidate[start : start + width] != edit.old_fragment:
            return None
        updated = candidate[:start] + new + candidate[start + width :]
    if not re.fullmatch(PATTERNS[kind], updated):
        return None
    if kind == "vehicle_plate" and updated[-2:] not in REGIONS:
        return None
    return updated if updated != candidate else None
