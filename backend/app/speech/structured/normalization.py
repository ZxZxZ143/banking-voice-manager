"""Bounded candidate parsing: exact schemas choose candidates, never missing digits."""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.speech.structured.context import ExpectedKind

PATTERNS = {
    "phone": r"\+7\d{10}",
    "iin": r"\d{12}",
    "policy_number": r"SQ-(OGPO|CASCO|TRVL|PROP|NS|DMS)-\d{6}",
    "claim_number": r"CL-\d{6}",
    "vehicle_plate": r"\d{3}[A-Z]{2,3}\d{2}",
    "region_code": r"0[1-9]|1\d|20|almaty|astana|other",
}
# Official vehicle-registration codes, https://www.gov.kz/article/22592 (2026-10-03).
REGIONS = {
    "01": "Астана",
    "02": "Алматы",
    "03": "Акмолинская область",
    "04": "Актюбинская область",
    "05": "Алматинская область",
    "06": "Атырауская область",
    "07": "Западно-Казахстанская область",
    "08": "Жамбылская область",
    "09": "Карагандинская область",
    "10": "Костанайская область",
    "11": "Кызылординская область",
    "12": "Мангистауская область",
    "13": "Туркестанская область",
    "14": "Павлодарская область",
    "15": "Северо-Казахстанская область",
    "16": "Восточно-Казахстанская область",
    "17": "Шымкент",
    "18": "Абай",
    "19": "Жетісу",
    "20": "Ұлытау",
}
REGION_NAMES = {
    **{name.casefold(): code for code, name in REGIONS.items()},
    "алматы облысы": "05",
    "алматинская область": "05",
    "almaty": "02",
    "astana": "01",
    "ақмола": "03",
    "ақтөбе": "04",
    "атырау": "06",
    "батыс қазақстан": "07",
    "жамбыл": "08",
    "қарағанды": "09",
    "караганда": "09",
    "қостанай": "10",
    "қызылорда": "11",
    "маңғыстау": "12",
    "түркістан": "13",
    "павлодар": "14",
    "солтүстік қазақстан": "15",
    "шығыс қазақстан": "16",
    "другой регион": "other",
    "басқа өңір": "other",
    "other": "other",
}
_RU = "ноль один два три четыре пять шесть семь восемь девять".split()
_KK = "нөл бір екі үш төрт бес алты жеті сегіз тоғыз".split()
DIGITS = {word: n for words in (_RU, _KK) for n, word in enumerate(words)}
DIGITS.update({"нуль": 0, "одна": 1, "две": 2})
_SMALL = (
    "десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать "
    "шестнадцать семнадцать восемнадцать девятнадцать"
).split()
NUMBERS = {**DIGITS, **{word: n for n, word in enumerate(_SMALL, 10)}}
TENS = dict(
    zip(
        "двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто".split(),
        range(20, 100, 10),
        strict=True,
    )
)
TENS.update(
    dict(
        zip(
            "он жиырма отыз қырық елу алпыс жетпіс сексен тоқсан".split(),
            range(10, 100, 10),
            strict=True,
        )
    )
)
HUNDREDS = dict(
    zip(
        "сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот".split(),
        range(100, 1000, 100),
        strict=True,
    )
)
FILLERS = set(
    (
        "это мой моя номер номера телефон телефона иин жсн полис полиса заявление заявления "
        "машина автомобиля госномер нөмір нөмірі нөмірім менің міне осы код плюс plus тіркеу "
        "аймақ аймағы өңір өңірі регион региона буквы әріп әріптер затем потом и және пожалуйста "
        "болады город города қаласы облысы область тіркелген регистрация регистрации дефис сызықша"
    ).split()
)
ORDINALS = {
    "первый": 1,
    "первом": 1,
    "второй": 2,
    "втором": 2,
    "третий": 3,
    "бірінші": 1,
    "екінші": 2,
    "үшінші": 3,
}
# Only active letter-bearing contexts use this lexicon. Unknown words fail closed.
LETTER_NAMES = {
    "A": "эй а",
    "B": "би бэ",
    "C": "си сэ це",
    "D": "ди дэ",
    "E": "и е",
    "F": "эф",
    "G": "джи гэ",
    "H": "эйч аш",
    "I": "ай і",
    "J": "джей",
    "K": "кей ка",
    "L": "эл эль",
    "M": "эм",
    "N": "эн",
    "O": "оу о",
    "P": "пи пэ",
    "Q": "кью ку қью",
    "R": "ар эр",
    "S": "эс ес",
    "T": "ти тэ",
    "U": "ю у",
    "V": "ви вэ",
    "W": "даблъю дубльве",
    "X": "экс икс",
    "Y": "уай игрек",
    "Z": "зед зэт зет",
}
LETTERS = {word: letter for letter, words in LETTER_NAMES.items() for word in words.split()}
VISUAL = str.maketrans("АВСЕНКМОРТХУ", "ABCEHKMOPTXY")
PREFIX_ALIASES = {
    "sq": "SQ",
    "скью": "SQ",
    "эскью": "SQ",
    "ску": "SQ",
    "ogpo": "OGPO",
    "огпо": "OGPO",
    "оғпо": "OGPO",
    "casco": "CASCO",
    "каско": "CASCO",
    "каскo": "CASCO",
    "trvl": "TRVL",
    "трвл": "TRVL",
    "prop": "PROP",
    "проп": "PROP",
    "ns": "NS",
    "нс": "NS",
    "dms": "DMS",
    "дмс": "DMS",
    "cl": "CL",
    "сиэл": "CL",
    "сиэль": "CL",
    "сl": "CL",
}
MAX_CANDIDATES = 64


@dataclass(frozen=True)
class NormalizedValue:
    kind: str
    candidates: tuple[str, ...] = field(default=(), repr=False)
    overflow: bool = False

    @property
    def accepted(self) -> bool:
        return len(self.candidates) == 1 and not self.overflow

    @property
    def value(self) -> str | None:
        return self.candidates[0] if self.accepted else None


def _group(words: tuple[str, ...]) -> int | None:
    """One grammatical RU/KK cardinal group, without absorbing separate digits."""
    if not words:
        return None
    if len(words) == 1:
        return NUMBERS.get(
            words[0], TENS.get(words[0], HUNDREDS.get(words[0], 100 if words[0] == "жүз" else None))
        )
    for i, word in enumerate(words):
        if word in {"тысяча", "тысячи", "тысяч", "мың"}:
            left = _group(words[:i]) if i else 1
            right = _group(words[i + 1 :]) if i + 1 < len(words) else 0
            if left is not None and right is not None and 1 <= left <= 999 and 0 <= right <= 999:
                return left * 1000 + right
            return None
    if len(words) >= 2 and words[1] == "жүз" and words[0] in DIGITS and DIGITS[words[0]]:
        rest = _group(words[2:]) if len(words) > 2 else 0
        if rest is not None and 0 <= rest < 100:
            return DIGITS[words[0]] * 100 + rest
    if words[0] in HUNDREDS or words[0] == "жүз":
        rest = _group(words[1:])
        if rest is not None and 0 < rest < 100:
            return HUNDREDS.get(words[0], 100) + rest
    if words[0] in TENS and len(words) == 2 and words[1] in DIGITS and DIGITS[words[1]]:
        return TENS[words[0]] + DIGITS[words[1]]
    return None


def digit_candidates(words: list[str], max_length: int) -> tuple[set[str], bool]:
    """Enumerate group boundaries; overflow is ambiguity, never a chosen prefix."""
    overflow = False

    @lru_cache(maxsize=256)
    def parse(index):
        nonlocal overflow
        if index == len(words):
            return {""}
        result = set()
        for end in range(index + 1, min(len(words), index + 8) + 1):
            group = words[index:end]
            value = (
                group[0] if len(group) == 1 and group[0].isascii() and group[0].isdigit() else None
            )
            if value is None:
                number = _group(tuple(group))
                value = str(number) if number is not None else None
            if value is None:
                continue
            for tail in parse(end):
                if len(value + tail) <= max_length:
                    result.add(value + tail)
            if len(result) > MAX_CANDIDATES:
                overflow = True
                return set()
        return result

    return parse(0) if len(words) <= 60 else set(), overflow or len(words) > 60


def _letters(words):
    result = ""
    for word in words:
        if word in PREFIX_ALIASES:
            result += PREFIX_ALIASES[word]
        elif word in LETTERS:
            result += LETTERS[word]
        else:
            visual = word.upper().translate(VISUAL)
            if not re.fullmatch(r"[A-Z]{1,6}", visual):
                return None
            result += visual
    return result


def pricing_region(value: str) -> str:
    if value in {"almaty", "astana", "other"}:
        return value
    if value not in REGIONS:
        raise ValueError("Invalid registration region")
    return {"01": "astana", "02": "almaty"}.get(value, "other")


def normalize_spoken(text: str, kind: ExpectedKind, pattern: str | None = None) -> NormalizedValue:
    if kind == "none" or len(text) > 1000:
        return NormalizedValue(kind)
    words = re.findall(r"[0-9]+|[^\W\d_]+", text.casefold().replace("ё", "е"))
    names = set()
    if kind == "region_code":
        if set(words) & {"не", "нет", "жоқ", "емес"}:
            return NormalizedValue(kind)
        # Longest complete place names first; preserve any conflicting spoken code.
        for name, code in sorted(REGION_NAMES.items(), key=lambda item: -len(item[0])):
            phrase = name.split()
            for i in range(len(words) - len(phrase) + 1):
                if words[i : i + len(phrase)] == phrase:
                    names.add(code)
                    words[i : i + len(phrase)] = [""] * len(phrase)
        words = [word for word in words if word]
        ordinal_context = bool(set(words) & {"регион", "региона", "өңір", "аймақ"})
        words = [
            str(ORDINALS[w]) if ordinal_context and w in ORDINALS else w
            for w in words
            if w not in FILLERS
        ]
    else:
        fillers = (
            FILLERS - {"и"}
            if kind in {"vehicle_plate", "policy_number", "claim_number"}
            else FILLERS
        )
        words = [w for w in words if w not in fillers]
    if not words:
        return NormalizedValue(kind, tuple(sorted(names)))
    overflow = False
    values = set(names)
    if kind in {"phone", "iin", "region_code"}:
        digits, overflow = digit_candidates(words, {"phone": 11, "iin": 12, "region_code": 2}[kind])
        if kind == "region_code" and names and not any(v.zfill(2) in REGIONS for v in digits):
            return NormalizedValue(kind)
        for value in digits:
            if kind == "phone" and len(value) == 11 and value[0] in "78":
                values.add("+7" + value[1:])
            elif kind == "iin":
                values.add(value)
            elif kind == "region_code" and value.zfill(2) in REGIONS:
                values.add(value.zfill(2))
    elif kind in {"policy_number", "claim_number"}:
        for split in range(1, len(words)):
            prefix = _letters(words[:split])
            if kind == "claim_number" and prefix == "CL":
                canonical_prefix = "CL-"
            elif kind == "policy_number" and prefix in {
                "SQ" + p for p in ("OGPO", "CASCO", "TRVL", "PROP", "NS", "DMS")
            }:
                canonical_prefix = "SQ-" + prefix[2:] + "-"
            else:
                continue
            digits, over = digit_candidates(words[split:], 6)
            overflow |= over
            values.update(canonical_prefix + value for value in digits)
    elif kind == "vehicle_plate":
        for left in range(1, len(words) - 1):
            first, over = digit_candidates(words[:left], 3)
            overflow |= over
            for right in range(left + 1, len(words)):
                letters = _letters(words[left:right])
                if not letters or not re.fullmatch("[A-Z]{2,3}", letters):
                    continue
                suffix_words = words[right:]
                if set(re.findall(r"\w+", text.casefold())) & {
                    "регион",
                    "региона",
                    "өңір",
                    "аймақ",
                }:
                    suffix_words = [
                        str(ORDINALS[w]).zfill(2) if w in ORDINALS else w for w in suffix_words
                    ]
                last, over = digit_candidates(suffix_words, 2)
                overflow |= over
                values.update(a + letters + b for a in first for b in last if b in REGIONS)
    valid = tuple(sorted(v for v in values if re.fullmatch(pattern or PATTERNS[kind], v)))
    return NormalizedValue(kind, valid, overflow)


def recognize_expected(text: str, kind: ExpectedKind) -> NormalizedValue:
    result = normalize_spoken(text, kind)
    if (
        result.accepted
        or result.overflow
        or len(result.candidates) > 1
        or kind not in {"phone", "iin", "policy_number", "claim_number", "vehicle_plate"}
    ):
        return result
    # A full alternative identifier has a distinct schema. Never relabel it as the requested one.
    alternatives = [
        normalize_spoken(text, other)
        for other in ("phone", "iin", "policy_number", "claim_number", "vehicle_plate")
        if other != kind
    ]
    valid = [item for item in alternatives if item.accepted]
    return valid[0] if len(valid) == 1 else result
