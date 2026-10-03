"""Conservative reply-language guard; performs no intent or product classification."""

import re
from typing import Literal

ResponseLanguage = Literal["ru", "kk"]

# Only complete language-control clauses, never a business-intent classifier.
_REQUEST_PREFIX = r"(?:(?:ответь(?:те)?|говори(?:те)?|отвечай(?:те)?|давайте|можно|пожалуйста)\s+)*"
_REQUESTS = {
    "ru": re.compile(
        _REQUEST_PREFIX + r"(?:на\s+русском(?:\s+языке)?|по[-\s]русски)(?:\s+пожалуйста)?"
    ),
    "kk": re.compile(
        _REQUEST_PREFIX + r"(?:на\s+казахском(?:\s+языке)?|по[-\s]казахски)(?:\s+пожалуйста)?"
        r"|қазақша(?:\s+(?:жауап\s+бер(?:іңіз|ші)?|сөйлейік|сөйлеңіз|айтыңыз))?"
        r"|қазақ\s+тілінде(?:\s+жауап\s+беріңіз)?"
    ),
}


def language_request(text: str) -> tuple[ResponseLanguage | None, str]:
    """Extract explicit complete clauses; leave all remaining business text intact."""
    requested = None
    remaining = []
    for clause in re.split(r"(?<=[,;.!?])\s*", text):
        normalized = clause.casefold().strip(" \t\r\n,;.!?")
        match = next(
            (lang for lang, pattern in _REQUESTS.items() if pattern.fullmatch(normalized)), None
        )
        if match:
            requested = match
        elif normalized:
            remaining.append(clause)
    return requested, " ".join(remaining) if requested else text


def stable_response_language(
    text: str,
    current: ResponseLanguage,
    preferred: ResponseLanguage | None,
    *,
    initial_hint: ResponseLanguage | None = None,
) -> ResponseLanguage:
    """Bounded linguistic evidence; uncertain turns retain the established language.

    Model evidence is useful only before an application response establishes continuity.
    Explicit preferences are authoritative until another explicit control request.
    """
    if preferred:
        return preferred
    words = re.findall(r"[а-яёәғқңөұүһі]+", text.casefold())
    neutral = {
        "да",
        "нет",
        "иә",
        "жоқ",
        "на",
        "год",
        "года",
        "месяц",
        "месяцев",
        "тысяч",
        "тысячи",
        "миллион",
        "тенге",
        "теңге",
    }
    if words and len(words) <= 3 and all(word in neutral for word in words):
        return current
    ru_functions = {
        "я",
        "мне",
        "меня",
        "мой",
        "моя",
        "мои",
        "вы",
        "вас",
        "ваш",
        "это",
        "этот",
        "этому",
        "какие",
        "какой",
        "что",
        "чтобы",
        "как",
        "где",
        "когда",
        "для",
        "при",
        "без",
        "и",
        "или",
        "ли",
        "в",
        "на",
        "по",
        "не",
        "нужно",
        "можно",
        "хочу",
    }
    kk_functions = {
        "мен",
        "маған",
        "маган",
        "сен",
        "сіз",
        "сиз",
        "осы",
        "сол",
        "үшін",
        "ушин",
        "туралы",
        "керек",
        "бар",
        "ма",
        "ме",
        "ба",
        "бе",
        "па",
        "пе",
        "қандай",
        "кандай",
        "калай",
        "қалай",
        "және",
        "немесе",
        "әлде",
    }
    marked = re.compile(r"[әғқңөұүһі]")
    ru = sum(
        word in ru_functions
        or (
            len(word) >= 5
            and not marked.search(word)
            and bool(re.search(r"(?:ует|ются|ете|ешь|ый|ий|ая|ого|ому|ыми|ить|ать)$", word))
        )
        for word in words
    )
    kk = sum(
        word in kk_functions
        or bool(marked.search(word))
        or (
            len(word) >= 5 and bool(re.search(r"(?:мын|мін|мыз|міз|кым|ким|келеди|сыз|сіз)$", word))
        )
        for word in words
    )
    if ru >= 2 and ru > kk:
        return "ru"
    if kk >= 2 and kk > ru:
        return "kk"
    return initial_hint or current


def reply_language(text, detected_language, response_language):
    words = re.findall(r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]+", text)
    marked = sum(bool(re.search(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]", word)) for word in words)
    russian_markers = {
        "и",
        "в",
        "на",
        "по",
        "как",
        "где",
        "когда",
        "что",
        "или",
        "ли",
        "мой",
        "мне",
        "меня",
        "моего",
        "ваш",
        "хочу",
        "нужно",
        "можно",
        "ещё",
    }
    if (
        detected_language == "kk"
        and not marked
        and sum(word.casefold() in russian_markers for word in words) >= 2
    ):
        return "ru"
    if (
        detected_language == "ru"
        and marked
        and ((len(words) == 1) or (marked >= 2 and marked * 2 >= len(words)))
    ):
        return "kk"
    if detected_language in ("ru", "kk"):
        return detected_language
    return response_language
