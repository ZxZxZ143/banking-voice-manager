"""Short source-grounded policy facts; machine IDs/dates stay out of customer speech."""

from datetime import date

RU_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
KK_MONTHS = (
    "қаңтар",
    "ақпан",
    "наурыз",
    "сәуір",
    "мамыр",
    "маусым",
    "шілде",
    "тамыз",
    "қыркүйек",
    "қазан",
    "қараша",
    "желтоқсан",
)


def human_date(value: str, language: str) -> str:
    day = date.fromisoformat(value)
    if language == "ru":
        return f"{day.day} {RU_MONTHS[day.month - 1]} {day.year} года"
    return f"{day.year} жылғы {day.day} {KK_MONTHS[day.month - 1]}"


def policy_facts(record: dict, reference: str, language: str) -> tuple[str, dict[str, str]]:
    start, end, today = (
        date.fromisoformat(value) for value in (record["start_date"], record["end_date"], reference)
    )
    status = "future" if today < start else "expired" if today > end else "active"
    statuses = {
        "ru": {
            "active": "Сейчас ваш полис действует.",
            "expired": "Срок действия вашего полиса истёк.",
            "future": "Ваш полис ещё не начал действовать.",
        },
        "kk": {
            "active": "Қазір полисіңіз жарамды.",
            "expired": "Полисіңіздің мерзімі аяқталған.",
            "future": "Полисіңіз әлі күшіне енбеген.",
        },
    }
    begin, finish = (
        human_date(record["start_date"], language),
        human_date(record["end_date"], language),
    )
    end_verb = "закончился" if status == "expired" else "заканчивается"
    ending = (
        f"Срок действия вашего полиса {end_verb} {finish}."
        if language == "ru"
        else f"Полисіңіздің аяқталу күні — {finish}."
    )
    period = (
        f"Период страхования — с {begin} по {finish}."
        if language == "ru"
        else f"Сақтандыру мерзімі — {begin} бастап {finish} дейін."
    )
    return statuses[language][status], {"policy_end_date": ending, "policy_period": period}
