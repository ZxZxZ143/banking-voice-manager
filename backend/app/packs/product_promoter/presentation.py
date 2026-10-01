"""Human speech from catalog values; ISO currencies stay in machine-readable state."""

import re

from app.packs.product_promoter.models import Product


def _russian_form(number: float, forms: tuple[str, str, str]) -> str:
    if number != int(number):
        return forms[1]
    integer = int(number)
    if 11 <= integer % 100 <= 14:
        return forms[2]
    last = integer % 10
    return forms[0] if last == 1 else forms[1] if last in (2, 3, 4) else forms[2]


def number_text(number: float) -> str:
    return f"{number:g}".replace(".", ",")


def money(number: float, currency: str, language: str, *, genitive: bool = False) -> str:
    ru = language == "ru"
    unit = (
        "тенге"
        if currency == "KZT"
        else (
            _russian_form(number, ("доллар США", "доллара США", "долларов США"))
            if ru
            else "АҚШ доллары"
        )
    )
    if number >= 1000 and number % 1000 == 0:
        divisor = 1_000_000 if number % 1_000_000 == 0 else 1000
        scaled = number / divisor
        scale = (
            (
                _russian_form(scaled, ("миллион", "миллиона", "миллионов"))
                if divisor == 1_000_000
                else _russian_form(scaled, ("тысяча", "тысячи", "тысяч"))
            )
            if ru
            else ("миллион" if divisor == 1_000_000 else "мың")
        )
        if ru and genitive:
            scale = (
                ("миллиона" if scaled == 1 else "миллионов")
                if divisor == 1_000_000
                else "тысячи"
                if scaled == 1
                else "тысяч"
            )
        unit = "тенге" if currency == "KZT" else "долларов США" if ru else "АҚШ доллары"
        return f"{number_text(scaled)} {scale} {unit}"
    return f"{number_text(number)} {unit}"


def percent(number: float, language: str) -> str:
    unit = (
        _russian_form(number, ("процент", "процента", "процентов")) if language == "ru" else "пайыз"
    )
    return f"{number_text(number)} {unit}"


def spoken_currency(text: str, language: str) -> str:
    text = re.sub(
        r"(\d+(?:[.,]\d+)?)%",
        lambda match: percent(float(match[1].replace(",", ".")), language),
        text,
    )
    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*(KZT|USD)\b",
        lambda match: money(float(match[1]), match[2], language),
        text,
    )
    return text.replace("KZT", "тенге").replace(
        "USD", "доллары США" if language == "ru" else "АҚШ доллары"
    )


def spoken_summary(product: Product, language: str) -> str:
    ru = language == "ru"
    name = product.name_ru if ru else product.name_kk
    if product.category == "deposit":
        currency = product.currencies[0]
        amount = money(product.minimum_amount, currency, language, genitive=True)
        rate = percent(product.effective_rate_percent, language)
        terms = (
            " или ".join(map(str, product.term_months))
            if ru
            else " немесе ".join(map(str, product.term_months))
        )
        if ru:
            liquidity = ("Можно пополнять" if product.replenishment else "Пополнения нет") + (
                " и снимать часть денег"
                if product.partial_withdrawal
                else "; частичного снятия нет"
            )
            text = (
                f"У депозита «{name}» эффективная годовая ставка — {rate}. "
                f"Начать можно с суммы от {amount} на {terms} месяцев. {liquidity}. "
                f"При досрочном закрытии: {product.early_termination_ru} "
                f"{product.restrictions_ru}"
            )
        else:
            liquidity = ("Толықтыруға болады" if product.replenishment else "Толықтыру жоқ") + (
                ", ақшаның бір бөлігін алуға болады"
                if product.partial_withdrawal
                else "; ішінара алу жоқ"
            )
            text = (
                f"«{name}» депозиті: жылдық тиімді мөлшерлеме — {rate}, "
                f"ең аз сома — {amount}, мерзімі — {terms} ай. {liquidity}. "
                f"Мерзімінен бұрын жабу: {product.early_termination_kk} "
                f"{product.restrictions_kk}"
            )
    else:
        fee = money(product.monthly_fee_kzt, "KZT", language)
        cashback = percent(product.cashback_percent, language)
        limit = money(product.cashback_limit_kzt, "KZT", language, genitive=True)
        atm = money(product.atm_free_limit_kzt, "KZT", language, genitive=True)
        above = percent(product.atm_above_limit_percent, language)
        if ru:
            text = (
                f"Карта «{name}» стоит {fee} в месяц. Кешбэк за покупки — {cashback}, "
                f"до {limit} в месяц. В демо-банкоматах можно снять до {atm} в месяц без комиссии, "
                f"сверх лимита — {above}. {product.restrictions_ru}"
            )
        else:
            text = (
                f"«{name}» картасы: қызмет ақысы — айына {fee}. Cashback — {cashback}, "
                f"айына ең көбі {limit}. "
                f"Демо-банкоматта айына {atm} дейін комиссиясыз алуға болады, "
                f"лимиттен асқанда — {above}. {product.restrictions_kk}"
            )
    return spoken_currency(text, language)
