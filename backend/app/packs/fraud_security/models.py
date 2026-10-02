from typing import Literal

from pydantic import Field

from app.core.contracts import Contract
from app.packs.contracts import ScenarioResult
from app.risk.models import (
    CaseType,
    Guidance,
    RiskAssessment,
    RiskContext,
    RiskSignal,
    SecurityQuestion,
)


class FraudCaseResult(ScenarioResult):
    case_type: CaseType = "none"
    case_status: Literal["open", "informed", "needs_review"] = "open"
    facts: list[RiskSignal] = Field(default_factory=list, max_length=15)
    transaction_kind: Literal["transfer", "purchase"] | None = None
    risk: RiskAssessment | None = None
    guidance_shown: list[Guidance] = Field(default_factory=list, max_length=11)


class FraudContext(Contract):
    response_language: Literal["ru", "kk"] = "ru"
    facts: list[RiskSignal] = Field(default_factory=list, max_length=15)
    case_type: CaseType = "none"
    transaction_kind: Literal["transfer", "purchase"] | None = None
    pending_question: SecurityQuestion | None = None
    asked_questions: list[SecurityQuestion] = Field(default_factory=list, max_length=5)
    guidance_shown: list[Guidance] = Field(default_factory=list, max_length=11)
    unclear_count: int = Field(default=0, ge=0, le=3)

    def risk_context(self):
        return RiskContext(
            previous_signals=self.facts.copy(),
            pending_question=self.pending_question,
            response_language=self.response_language,
        )


class FraudPublicState(FraudContext):
    session_id: str
    scenario_mode: Literal["fraud_security"] = "fraud_security"
    turn_number: int
    fraud_case: FraudCaseResult
