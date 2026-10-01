import json
from pathlib import Path

from app.packs.product_promoter.models import Preferences, Product, ProductCatalog


def load_catalog(path: Path) -> ProductCatalog:
    return ProductCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))


def matching_products(catalog: ProductCatalog, category: str, prefs: Preferences) -> list[Product]:
    """Explicit restrictions filter candidates; soft preferences rank them deterministically."""
    products = [p for p in catalog.products if p.category == category]
    products = [
        p
        for p in products
        if (
            (prefs.currency is None or prefs.currency in p.currencies)
            and (
                category != "deposit"
                or (
                    (
                        prefs.amount is None
                        or prefs.currency is None
                        or prefs.amount >= p.minimum_amount
                    )
                    and (prefs.term_months is None or prefs.term_months in p.term_months)
                    and (prefs.liquidity is not True or p.partial_withdrawal)
                    and (prefs.replenishment is not True or p.replenishment)
                )
            )
            and (prefs.digital_only is not True or p.digital)
            and (prefs.fee_sensitive is not True or p.monthly_fee_kzt == 0)
        )
    ]

    def score(p):
        if category == "deposit":
            return p.effective_rate_percent
        if prefs.cash_withdrawal or prefs.goal == "withdrawals":
            return p.atm_free_limit_kzt
        if prefs.cashback or prefs.goal == "cashback":
            return p.cashback_percent
        return -p.monthly_fee_kzt

    return sorted(products, key=lambda p: (-score(p), p.id))


def conditions(p: Product, language: str) -> str:
    """Every numeric value is formatted directly from a validated product record."""
    ru = language == "ru"
    name = p.name_ru if ru else p.name_kk
    currencies = "/".join(p.currencies)
    channel = (
        {"demo_app": "демо-приложение", "demo_branch": "демо-отделение"}
        if ru
        else {"demo_app": "демо-қолданба", "demo_branch": "демо-бөлімше"}
    )[p.opening_channel]
    yes, no = ("да", "нет") if ru else ("иә", "жоқ")
    if p.category == "deposit":
        terms = "/".join(str(v) for v in p.term_months)
        capitalization = (
            ("ежемесячная" if ru else "ай сайын") if p.capitalization == "monthly" else no
        )
        if ru:
            body = (
                f"{name} ({p.id}): {currencies}; "
                f"номинальная ставка {p.nominal_rate_percent:g}% годовых, "
                f"ГЭСВ {p.effective_rate_percent:g}%; минимум {p.minimum_amount:g} {currencies}; "
                f"срок {terms} мес.; пополнение — {yes if p.replenishment else no}; "
                f"частичное снятие — {yes if p.partial_withdrawal else no}; "
                f"капитализация — {capitalization}. "
                f"Досрочное закрытие: {p.early_termination_ru} "
            )
        else:
            body = (
                f"{name} ({p.id}): {currencies}; "
                f"номиналды мөлшерлеме жылына {p.nominal_rate_percent:g}%, "
                f"ЖТСМ {p.effective_rate_percent:g}%; "
                f"ең аз сома {p.minimum_amount:g} {currencies}; "
                f"мерзімі {terms} ай; толықтыру — {yes if p.replenishment else no}; "
                f"ішінара алу — {yes if p.partial_withdrawal else no}; "
                f"капиталдандыру — {capitalization}. "
                f"Мерзімінен бұрын жабу: {p.early_termination_kk} "
            )
    elif ru:
        body = (
            f"{name} ({p.id}): {currencies}; обслуживание {p.monthly_fee_kzt} KZT/мес.; "
            f"cashback {p.cashback_percent:g}%, максимум {p.cashback_limit_kzt} KZT/мес.; "
            f"снятие в демо-банкоматах без комиссии до {p.atm_free_limit_kzt} KZT/мес., "
            f"сверх лимита {p.atm_above_limit_percent:g}%. "
            f"Цифровая карта — {yes if p.digital else no}. "
        )
    else:
        body = (
            f"{name} ({p.id}): {currencies}; қызмет ақысы {p.monthly_fee_kzt} KZT/ай; "
            f"cashback {p.cashback_percent:g}%, ең көбі {p.cashback_limit_kzt} KZT/ай; "
            f"демо-банкоматта айына {p.atm_free_limit_kzt} KZT дейін комиссиясыз алу, "
            f"лимиттен асқанда {p.atm_above_limit_percent:g}%. "
            f"Цифрлық карта — {yes if p.digital else no}. "
        )
    restriction = p.restrictions_ru if ru else p.restrictions_kk
    return body + (
        f"Открытие: {channel}. {restriction} Дата условий: {p.reference_date}."
        if ru
        else f"Ашу: {channel}. {restriction} Шарттар күні: {p.reference_date}."
    )
