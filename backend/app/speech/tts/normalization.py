"""Deterministic RU/KK speech text; display text and business values stay unchanged.

No floats, rounding, rates/calculation, intent inference or SSML. Unrecognized numbers
stay literal. Grouped numbers, decimal precision and leading identifier zeros survive.
"""

import re
from datetime import date

_RU_ONES = "ноль один два три четыре пять шесть семь восемь девять".split()
_RU_TEENS = (
    "десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать "
    "шестнадцать семнадцать восемнадцать девятнадцать"
).split()
_RU_TENS = (
    "ноль десять двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто"
).split()
_RU_HUNDREDS = (
    "ноль сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот".split()
)
_KK_ONES = "нөл бір екі үш төрт бес алты жеті сегіз тоғыз".split()
_KK_TENS = "нөл он жиырма отыз қырық елу алпыс жетпіс сексен тоқсан".split()
_NUMBER = r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"


def _form(number, one, few, many):
    return (
        many
        if 11 <= number % 100 <= 14
        else one
        if number % 10 == 1
        else few
        if number % 10 in (2, 3, 4)
        else many
    )


def integer_words(number: int, language: str, *, feminine=False) -> str:
    if not 0 <= number < 10**15:
        return str(number)
    if number == 0:
        return "ноль" if language == "ru" else "нөл"
    parts = []
    for divisor, ru_names, kk_name in [
        (10**12, ("триллион", "триллиона", "триллионов"), "триллион"),
        (10**9, ("миллиард", "миллиарда", "миллиардов"), "миллиард"),
        (10**6, ("миллион", "миллиона", "миллионов"), "миллион"),
        (1000, ("тысяча", "тысячи", "тысяч"), "мың"),
    ]:
        quotient, number = divmod(number, divisor)
        if quotient:
            parts.extend(
                [
                    integer_words(quotient, language, feminine=divisor == 1000),
                    _form(quotient, *ru_names) if language == "ru" else kk_name,
                ]
            )
    if language == "ru":
        hundreds, number = divmod(number, 100)
        if hundreds:
            parts.append(_RU_HUNDREDS[hundreds])
        if 10 <= number < 20:
            parts.append(_RU_TEENS[number - 10])
        else:
            tens, units = divmod(number, 10)
            if tens:
                parts.append(_RU_TENS[tens])
            if units:
                parts.append(
                    "одна"
                    if feminine and units == 1
                    else "две"
                    if feminine and units == 2
                    else _RU_ONES[units]
                )
    else:
        hundreds, number = divmod(number, 100)
        if hundreds:
            parts.append(((_KK_ONES[hundreds] + " ") if hundreds > 1 else "") + "жүз")
        tens, units = divmod(number, 10)
        if tens:
            parts.append(_KK_TENS[tens])
        if units:
            parts.append(_KK_ONES[units])
    return " ".join(parts)


def number_words(value: str, language: str) -> str:
    value = re.sub(r"[ \u00a0\u202f]", "", value)
    pieces = re.split(r"[.,]", value)
    whole = pieces[0]
    if len(whole) > 15 or (len(pieces) == 2 and len(pieces[1]) > 6):
        return value
    if len(pieces) == 1:
        if len(whole) > 1 and whole.startswith("0"):
            words = _RU_ONES if language == "ru" else _KK_ONES
            return " ".join(words[int(digit)] for digit in whole)
        return integer_words(int(whole), language)
    fraction = pieces[1]
    if language == "ru":
        denominators = [
            "десятая",
            "сотая",
            "тысячная",
            "десятитысячная",
            "стотысячная",
            "миллионная",
        ]
        denominator = denominators[len(fraction) - 1]
        denominator = (
            denominator
            if int(fraction) % 10 == 1 and int(fraction) % 100 != 11
            else denominator[:-2] + "ых"
        )
        return (
            integer_words(int(whole), language, feminine=True)
            + " "
            + _form(int(whole), "целая", "целых", "целых")
            + " "
            + integer_words(int(fraction), language, feminine=True)
            + " "
            + denominator
        )
    denominator = ["оннан", "жүзден", "мыңнан", "он мыңнан", "жүз мыңнан", "миллионнан"][
        len(fraction) - 1
    ]
    return (
        f"{integer_words(int(whole), language)} бүтін {denominator} "
        f"{integer_words(int(fraction), language)}"
    )


def prepare_speech(text: str, language: str) -> str:
    language = "kk" if language == "kk" else "ru"
    text = text.replace("\r\n", "\n")
    protected = []

    def protect(value):
        # Letter-only placeholders cannot be consumed by numeric substitutions.
        token = "\ue000" + chr(0xE100 + len(protected)) + "\ue001"
        protected.append((token, value))
        return token

    def speak_date(match):
        raw = match[0]
        values = re.split(r"[.-]", raw)
        year, month, day = map(int, values if len(values[0]) == 4 else reversed(values))
        try:
            date(year, month, day)
        except ValueError:
            return protect(raw)
        months = (
            "января февраля марта апреля мая июня июля августа сентября октября ноября декабря"
            if language == "ru"
            else (
                "қаңтар ақпан наурыз сәуір мамыр маусым шілде тамыз қыркүйек қазан қараша желтоқсан"
            )
        ).split()
        prefix = integer_words(day, language)
        return protect(
            f"{prefix} {months[month - 1]}, "
            + ("год " if language == "ru" else "жыл ")
            + integer_words(year, language)
        )

    text = re.sub(r"(?<!\w)(?:\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})(?!\w)", speak_date, text)
    text = re.sub(
        r"(?<!\w)\+\d[\d ()-]{8,20}\d(?!\w)",
        lambda m: protect(
            ("плюс " if language == "ru" else "плюс ")
            + " ".join(
                (_RU_ONES if language == "ru" else _KK_ONES)[int(d)] for d in m[0] if d.isdigit()
            )
        ),
        text,
    )

    def percentage(match):
        value = re.sub(r"\s", "", match[1])
        unit = (
            "пайыз"
            if language == "kk"
            else "процента"
            if re.search(r"[.,]", value)
            else _form(int(value), "процент", "процента", "процентов")
        )
        return protect(number_words(match[1], language) + " " + unit)

    text = re.sub(rf"(?<![\w.,])({_NUMBER})\s*(?:%|процент(?:а|ов)?\b|пайыз\b)", percentage, text)

    def currency(match):
        number, currency = match[1], match[2]
        value = re.sub(r"\s", "", number)
        unit = (
            ("тенге" if language == "ru" else "теңге")
            if currency in ("KZT", "₸", "тенге", "теңге")
            else (
                "АҚШ доллары"
                if language == "kk"
                else "доллара США"
                if re.search(r"[.,]", value)
                else _form(int(value), "доллар США", "доллара США", "долларов США")
            )
        )
        return protect(number_words(number, language) + " " + unit)

    text = re.sub(rf"(?<![\w.,])({_NUMBER})\s*(KZT\b|USD\b|₸|тенге\b|теңге\b)", currency, text)
    text = re.sub(
        rf"(?<![\w.,])({_NUMBER})(?![\w.,])", lambda m: number_words(m[0], language), text
    )
    text = re.sub(r"\bKZT\b", "тенге" if language == "ru" else "теңге", text)
    text = re.sub(r"\bUSD\b", "доллары США" if language == "ru" else "АҚШ доллары", text)
    for token, value in protected:
        text = text.replace(token, value)
    # Plain text only: do not hand SSML to engines that may read it literally.
    text = re.sub(r"</?[A-Za-z][^>]{0,200}>", "", text)
    text = re.sub(r"(?m)^\s*[-*#]+\s+", "", text)
    text = text.replace("**", "").replace("…", ".")
    text = re.sub(r"\.{3,}", ".", text)
    return re.sub(r"[ \t]+", " ", text).strip()
