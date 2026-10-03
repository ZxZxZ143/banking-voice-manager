"""Reproducible synthetic speech fixtures; no customer records or routing labels."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RU = "ноль один два три четыре пять шесть семь восемь девять".split()
KK = "нөл бір екі үш төрт бес алты жеті сегіз тоғыз".split()
RU_TENS = (
    "десять двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто".split()
)
KK_TENS = "он жиырма отыз қырық елу алпыс жетпіс сексен тоқсан".split()
RU_HUNDREDS = "сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот".split()
TEENS = (
    "десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать "
    "шестнадцать семнадцать восемнадцать девятнадцать"
).split()


def cardinal(value, language):
    n = int(value)
    digits = KK if language == "kk" else RU
    parts = []
    if n >= 100:
        parts.append((digits[n // 100] + " жүз") if language == "kk" else RU_HUNDREDS[n // 100 - 1])
        n %= 100
    if language == "ru" and 10 <= n < 20:
        parts.append(TEENS[n - 10])
    else:
        if n >= 10:
            parts.append((KK_TENS if language == "kk" else RU_TENS)[n // 10 - 1])
        if n % 10 or not parts:
            parts.append(digits[n % 10])
    return " ".join(parts)


def spoken(value, language, grouped=False):
    if grouped:
        # Explicit zero groups retain all zeros. Nonzero triples use cardinals.
        chunks = [value[i : i + 3] for i in range(0, len(value), 3)]
        return " ".join(
            cardinal(c, language) if len(c) == 3 and c[0] != "0" else spoken(c, language)
            for c in chunks
        )
    return " ".join(
        (KK if language == "kk" or (language == "mixed" and i % 2) else RU)[int(c)]
        for i, c in enumerate(value)
    )


def build():
    rows = []
    for kind, count in [
        ("phone", 20),
        ("iin", 20),
        ("vehicle_plate", 20),
        ("policy_number", 15),
        ("claim_number", 10),
        ("region_code", 15),
    ]:
        for i in range(count):
            language = ("ru", "kk", "mixed")[i % 3]
            grouped = i % 5 == 3
            style = (
                "grouped" if grouped else ("slow", "fast", "individual", "filler", "letters")[i % 5]
            )
            if kind == "phone":
                digits = "7000" + f"{1234000 + i:07}"
                value = "+" + digits
                utterance = spoken(("8" if i % 2 else "7") + digits[1:], language, grouped)
            elif kind == "iin":
                value = "000" + f"{123456700 + i:09}"
                utterance = spoken(value, language, grouped)
            elif kind == "vehicle_plate":
                first = f"{123 + i:03}"
                suffix = f"{i + 1:02}"
                letters = ("ABC", "DEM", "KZ", "BEH")[i % 4]
                names = {
                    "A": "эй",
                    "B": "би",
                    "C": "си",
                    "D": "ди",
                    "E": "е",
                    "M": "эм",
                    "K": "кей",
                    "Z": "зед",
                    "H": "эйч",
                }
                value = first + letters + suffix
                utterance = (
                    spoken(first, language, grouped)
                    + " "
                    + " ".join(names[letter] for letter in letters)
                    + " "
                    + spoken(suffix, language)
                )
                if i % 5 == 4:
                    utterance = (
                        first
                        + " "
                        + letters.translate(str.maketrans("ABCEHKM", "АВСЕНКМ"))
                        + " "
                        + suffix
                    )
                    style = "asr_artifact"
            elif kind == "policy_number":
                prefix = ("OGPO", "CASCO", "TRVL", "PROP", "NS", "DMS")[i % 6]
                names = {
                    "OGPO": "о гэ пэ о",
                    "CASCO": "каско",
                    "TRVL": "ти ар ви эл",
                    "PROP": "пи ар оу пи",
                    "NS": "эн эс",
                    "DMS": "ди эм эс",
                }
                digits = f"{123000 + i:06}"
                value = "SQ-" + prefix + "-" + digits
                utterance = "эс кью " + names[prefix] + " " + spoken(digits, language, grouped)
            elif kind == "claim_number":
                digits = f"{123000 + i:06}"
                value = "CL-" + digits
                utterance = "си эл " + spoken(digits, language, grouped)
            else:
                value = f"{i + 1:02}"
                utterance = ("өңір " if language == "kk" else "регион ") + spoken(value, language)
                if i == 1:
                    utterance = "регион ноль два"
                    language = "ru"
                if i == 5:
                    utterance = "это регион ноль шесть"
                    language = "ru"
                if i == 10:
                    utterance = "регион 11"
                    language = "ru"
            if style == "filler":
                utterance = ("менің нөмірім " if language == "kk" else "мой номер ") + utterance
            rows.append(
                dict(
                    id=f"{kind}-{i + 1:02}",
                    kind=kind,
                    language=language,
                    style=style,
                    text=utterance,
                    expected=value,
                    synthetic=True,
                    voice=("coral", "nova", "shimmer")[i % 3],
                )
            )
    negatives = [
        ("iin", "ноль ноль один", None),
        ("phone", "8777000123", None),
        ("vehicle_plate", "123 ABC 99", None),
        ("policy_number", "SQ BAD 123456", None),
        ("claim_number", "CL 12345", None),
        ("region_code", "регион 21", None),
        ("region_code", "не Алматы", None),
        ("region_code", "Алматы или Астана", None),
        ("region_code", "регион 02 или 01", None),
        ("phone", "87770001234 или 87770001235", None),
        ("iin", "000101300000 или 000101300001", None),
        ("vehicle_plate", "123 эй би си 02 или 124 эй би си 02", None),
    ]
    rows.extend(
        dict(
            id=f"negative-{i + 1:02}",
            kind=k,
            language="ru",
            style="invalid",
            text=t,
            expected=e,
            synthetic=True,
            voice="coral",
        )
        for i, (k, t, e) in enumerate(negatives)
    )
    return rows


if __name__ == "__main__":
    path = ROOT / "data/speech/structured_utterances.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(build())} synthetic fixtures")
