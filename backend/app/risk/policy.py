import json
from pathlib import Path
from typing import Literal

from app.core.contracts import Contract
from app.risk.models import Guidance, RiskAssessment, RiskSignal, SecurityQuestion


class LocalizedText(Contract):
    ru: str
    kk: str


class SecurityPolicy(Contract):
    brand: Literal["Merei Demo Bank"]
    synthetic: Literal[True]
    reference_date: str
    description: str
    guidance: dict[Guidance, LocalizedText]
    questions: dict[SecurityQuestion, LocalizedText]
    education: LocalizedText

    def text(self, key, language, *, question=False):
        item = (self.questions if question else self.guidance)[key]
        return item.ru if language == "ru" else item.kk


def load_policy(path: Path) -> SecurityPolicy:
    return SecurityPolicy.model_validate(json.loads(path.read_text(encoding="utf-8")))


def guidance_for(signals: list[RiskSignal]) -> list[Guidance]:
    result = []
    for signal in signals:
        if signal in {
            RiskSignal.OTP_REQUESTED,
            RiskSignal.PIN_PASSWORD_REQUESTED,
            RiskSignal.CVV_REQUESTED,
            RiskSignal.BANK_IMPERSONATION,
        }:
            result.extend(["do_not_share_secrets", "end_suspicious_call"])
        elif signal in {RiskSignal.OTP_DISCLOSED, RiskSignal.CREDENTIAL_DISCLOSED}:
            result.extend(["exposure_review", "end_suspicious_call"])
        elif signal == RiskSignal.SUSPICIOUS_LINK:
            result.append("avoid_link")
        elif signal == RiskSignal.REMOTE_ACCESS_REQUESTED:
            result.append("avoid_remote_access")
        elif signal == RiskSignal.REMOTE_ACCESS_INSTALLED:
            result.append("remote_review")
        elif signal in {RiskSignal.TRANSFER_PRESSURE, RiskSignal.COERCED_TRANSFER_SENT}:
            result.append("no_safe_account_transfer")
        elif signal == RiskSignal.UNKNOWN_TRANSACTION:
            result.append("transaction_review")
        elif signal == RiskSignal.LOST_CARD:
            result.append("card_review")
        else:
            result.append("account_review")
    keys = list(dict.fromkeys(result))
    if "exposure_review" in keys or "remote_review" in keys:
        # A disclosed secret or installed remote access needs urgent advice before
        # the earlier, less urgent request facts retained in the case context.
        priority = {"exposure_review": 0, "remote_review": 0, "end_suspicious_call": 1}
        keys.sort(key=lambda key: priority.get(key, 2))
    return keys


def assessment_reason(assessment: RiskAssessment) -> str:
    # Application-level explanation from stable facts, no model prose or user secrets.
    return "Reported security indicators: " + ", ".join(s.value for s in assessment.signals)
