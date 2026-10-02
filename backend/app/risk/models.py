from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from app.core.contracts import Contract, Language


class RiskSignal(StrEnum):
    BANK_IMPERSONATION = "bank_impersonation"
    OTP_REQUESTED = "otp_requested_by_third_party"
    OTP_DISCLOSED = "otp_disclosed"
    CREDENTIAL_DISCLOSED = "credential_disclosed"
    PIN_PASSWORD_REQUESTED = "pin_or_password_requested"
    CVV_REQUESTED = "cvv_requested"
    SUSPICIOUS_LINK = "suspicious_link"
    REMOTE_ACCESS_REQUESTED = "remote_access_requested"
    REMOTE_ACCESS_INSTALLED = "remote_access_installed"
    UNKNOWN_TRANSACTION = "unknown_transaction"
    ACCOUNT_TAKEOVER = "account_takeover_concern"
    CONTACT_CHANGE = "unauthorized_contact_change"
    TRANSFER_PRESSURE = "transfer_under_pressure"
    LOST_CARD = "lost_stolen_card"
    COERCED_TRANSFER_SENT = "coerced_transfer_sent"


RiskLevel = Literal["none", "low", "medium", "high", "critical"]
RiskAction = Literal[
    "none",
    "show_security_guidance",
    "security_review",
    "urgent_security_review",
    "operator_handoff",
]
SecurityIntent = Literal[
    "concern", "general_info", "unclear", "out_of_scope", "operator_request", "goodbye"
]
CaseType = Literal[
    "none",
    "social_engineering",
    "transaction",
    "phishing",
    "remote_access",
    "account_access",
    "lost_card",
    "credential_exposure",
]
SecurityQuestion = Literal[
    "exposure", "transaction_kind", "remote_installed", "link_exposure", "concern_details"
]
Guidance = Literal[
    "do_not_share_secrets",
    "end_suspicious_call",
    "avoid_link",
    "avoid_remote_access",
    "no_safe_account_transfer",
    "official_channels",
    "exposure_review",
    "transaction_review",
    "card_review",
    "account_review",
    "remote_review",
]


class RiskAssessment(Contract):
    """Advisory triage, never a probability, credit/trust score or fraud verdict."""

    analysis_status: Literal["analyzed", "unavailable", "invalid_output"] = "analyzed"
    risk_relevant: bool | None = False
    level: RiskLevel = "none"
    signals: list[RiskSignal] = Field(default_factory=list, max_length=15)
    recommended_action: RiskAction = "none"
    reason: str = Field(default="", max_length=500)
    guidance_shown: list[Guidance] = Field(default_factory=list, max_length=11)
    error: str | None = None


class RiskContext(Contract):
    """Only safe security observations; no identity, products or private pack state."""

    previous_signals: list[RiskSignal] = Field(default_factory=list, max_length=15)
    pending_question: SecurityQuestion | None = None
    response_language: Literal["ru", "kk"] = "ru"


class RiskInput(Contract):
    current_text: str = Field(max_length=10000)
    language: Language | None = None
    channel: Literal["text", "voice"] = "text"
    active_assistant: str = Field(max_length=64)
    context: RiskContext = Field(default_factory=RiskContext)


class SecurityDecision(Contract):
    """No free text, identifiers, secret values, tools or banking-operation authority."""

    intent: SecurityIntent
    language: Language
    response_language: Literal["ru", "kk"]
    risk_relevant: bool
    level: RiskLevel
    signals: list[RiskSignal] = Field(default_factory=list, max_length=15)
    recommended_action: RiskAction
    case_type: CaseType = "none"
    transaction_kind: Literal["transfer", "purchase"] | None = None
    answer: bool | None = None
    confidence: float = Field(default=1, ge=0, le=1)

    @model_validator(mode="after")
    def consistent_assessment(self):
        if not self.risk_relevant and (
            self.signals or self.level != "none" or self.recommended_action != "none"
        ):
            raise ValueError("Irrelevant security content cannot carry risk signals/actions")
        if self.risk_relevant and (not self.signals or self.level == "none"):
            raise ValueError("Relevant assessment needs an explainable signal and triage level")
        if len(set(self.signals)) != len(self.signals):
            raise ValueError("Duplicate risk signals")
        return self
