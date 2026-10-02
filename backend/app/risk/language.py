"""Security reply presentation only, never an intent/risk classifier."""

import re

from app.conversation.language import reply_language


def security_language(text, detected, fallback):
    words = re.findall(r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]+", text)
    marked = sum(bool(re.search(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]", word)) for word in words)
    russian = sum(
        word.casefold() in {"и", "в", "на", "по", "как", "что", "ли", "мне", "мой", "но", "хочу"}
        for word in words
    )
    if marked >= 2 and russian <= 1 or marked >= 1 and russian == 0:
        return "kk"
    if russian >= 2 and marked == 0:
        return "ru"
    return reply_language(text, detected, fallback)
