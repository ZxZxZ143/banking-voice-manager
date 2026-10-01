"""Conservative reply-language guard; performs no intent or product classification."""

import re


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
