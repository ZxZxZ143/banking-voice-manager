from typing import Literal

from pydantic import Field, model_validator

from app.core.contracts import Contract, Language
from app.packs.contracts import ScenarioResult

Category = Literal["deposit", "card"]
Intent = Literal[
    "general_discovery",
    "deposit_interest",
    "card_interest",
    "product_comparison",
    "conditions_question",
    "objection",
    "application_interest",
    "decline",
    "operator_request",
    "goodbye",
    "out_of_scope",
]
Interest = Literal["unknown", "low", "medium", "high", "declined"]
NextAction = Literal[
    "continue_consultation",
    "application_interest",
    "send_application_link",
    "callback_requested",
    "operator_handoff",
    "declined",
]
Objection = Literal["fees", "yield", "liquidity", "restrictions", "other"]
Question = Literal[
    "category", "currency", "liquidity", "card_priority", "amount", "term", "next_action"
]


class Preferences(Contract):
    goal: Literal["save", "daily_payments", "cashback", "withdrawals"] | None = None
    amount: float | None = Field(default=None, gt=0, le=1e12, allow_inf_nan=False)
    currency: Literal["KZT", "USD"] | None = None
    term_months: int | None = Field(default=None, ge=1, le=120)
    liquidity: bool | None = None
    replenishment: bool | None = None
    cashback: bool | None = None
    fee_sensitive: bool | None = None
    cash_withdrawal: bool | None = None
    digital_only: bool | None = None


class ProductDecision(Contract):
    intent: Intent
    language: Language
    response_language: Literal["ru", "kk"]
    category: Category | None = None
    preferences: Preferences = Field(default_factory=Preferences)
    product_ids: list[str] = Field(default_factory=list, max_length=3)
    objection: Objection | None = None
    next_action: NextAction = "continue_consultation"
    confidence: float = Field(default=1, ge=0, le=1)


class SalesLeadResult(ScenarioResult):
    outcome: Literal["consulting", "interested", "declined", "handoff", "ended"]
    product_category: Category | None = None
    selected_product_id: str | None = None
    customer_preferences: Preferences = Field(default_factory=Preferences)
    presented_products: list[str] = Field(default_factory=list)
    compared_products: list[str] = Field(default_factory=list)
    objections: list[Objection] = Field(default_factory=list)
    interest_level: Interest = "unknown"
    next_action: NextAction = "continue_consultation"


class ProductScenarioContext(Contract):
    product_category: Category | None = None
    preferences: Preferences = Field(default_factory=Preferences)
    presented_products: list[str] = Field(default_factory=list)
    compared_products: list[str] = Field(default_factory=list)
    selected_product_id: str | None = None
    objections: list[Objection] = Field(default_factory=list)
    interest_level: Interest = "unknown"
    next_action: NextAction = "continue_consultation"
    last_question: Question | None = None
    response_language: Literal["ru", "kk"] = "ru"
    last_intent: Intent | None = None
    completed: bool = False
    recommended_product_id: str | None = None
    unclear_turns: int = Field(default=0, ge=0)


class Product(Contract):
    id: str = Field(pattern=r"^(DEP|CARD)-[A-Z]+$")
    category: Category
    name_ru: str
    name_kk: str
    currencies: list[Literal["KZT", "USD"]]
    nominal_rate_percent: float | None = Field(default=None, ge=0, le=100)
    effective_rate_percent: float | None = Field(default=None, ge=0, le=100)
    minimum_amount: float | None = Field(default=None, ge=0)
    term_months: list[int] = Field(default_factory=list)
    replenishment: bool = False
    partial_withdrawal: bool = False
    capitalization: Literal["monthly", "none"] = "none"
    early_termination_ru: str = ""
    early_termination_kk: str = ""
    monthly_fee_kzt: int = Field(default=0, ge=0)
    cashback_percent: float = Field(default=0, ge=0, le=100)
    cashback_limit_kzt: int = Field(default=0, ge=0)
    atm_free_limit_kzt: int = Field(default=0, ge=0)
    atm_above_limit_percent: float = Field(default=0, ge=0, le=100)
    digital: bool = False
    opening_channel: Literal["demo_app", "demo_branch"]
    restrictions_ru: str
    restrictions_kk: str
    reference_date: Literal["2026-10-01"]

    @model_validator(mode="after")
    def category_conditions(self):
        if self.category == "deposit" and (
            self.nominal_rate_percent is None
            or self.effective_rate_percent is None
            or self.minimum_amount is None
            or not self.term_months
            or not self.early_termination_ru
            or not self.early_termination_kk
        ):
            raise ValueError("Deposit conditions must be complete")
        return self


class ProductCatalog(Contract):
    brand: Literal["Merei Demo Bank"]
    synthetic: Literal[True]
    products: list[Product] = Field(min_length=4, max_length=6)

    @model_validator(mode="after")
    def distinct_products(self):
        if len({p.id for p in self.products}) != len(self.products):
            raise ValueError("Duplicate product ID")
        if any(
            not 2 <= sum(p.category == c for p in self.products) <= 3 for c in ("deposit", "card")
        ):
            raise ValueError("Provide two or three products in each category")
        return self


class ProductPublicState(ProductScenarioContext):
    session_id: str
    scenario_mode: Literal["product_promoter"] = "product_promoter"
    turn_number: int
    sales_lead: SalesLeadResult
    products: list[Product] = Field(default_factory=list)
    product_conditions: list["ProductConditions"] = Field(default_factory=list)


class ProductConditions(Contract):
    product_id: str
    name: str
    text: str


ProductPublicState.model_rebuild()
