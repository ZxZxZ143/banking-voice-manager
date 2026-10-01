"""Shared successful terminal replies for all packs."""


def terminal_reply(status: str, language: str) -> str:
    replies = {
        "handoff": {
            "ru": "Конечно, передаю диалог оператору.",
            "kk": "Әрине, диалогты операторға тапсырамын.",
        },
        "ended": {"ru": "До свидания!", "kk": "Сау болыңыз!"},
    }
    return replies[status][language]
