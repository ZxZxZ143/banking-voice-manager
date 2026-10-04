"""Application authority for structured speech, independent of ASR/schema success."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from app.speech.structured.context import ExpectedKind
from app.speech.structured.normalization import NormalizedValue


class RecognitionRisk(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class RecognitionOutcome(StrEnum):
    accepted = "accepted"
    confirmation_required = "confirmation_required"
    repair_required = "repair_required"
    manual_fallback = "manual_fallback"
    exhausted = "exhausted"


RISKS = {
    "region_code": RecognitionRisk.low,
    "vehicle_plate": RecognitionRisk.medium,
    "policy_number": RecognitionRisk.medium,
    "claim_number": RecognitionRisk.medium,
    "phone": RecognitionRisk.high,
    "iin": RecognitionRisk.high,
}


@dataclass(frozen=True)
class RecognitionHypothesis:
    source: Literal["realtime", "bounded"]
    kind: ExpectedKind
    canonical_candidate: str | None = field(repr=False)
    valid_schema: bool
    evidence: Literal["unique_schema", "ambiguous", "invalid", "unavailable"]

    @classmethod
    def from_normalized(cls, source, parsed: NormalizedValue):
        return cls(
            source,
            parsed.kind,
            parsed.value,
            parsed.accepted,
            "unique_schema" if parsed.accepted else "ambiguous" if parsed.candidates else "invalid",
        )


@dataclass(frozen=True)
class AcceptedStructuredValue:
    kind: ExpectedKind
    canonical_value: str = field(repr=False)
    verification_method: Literal["low_risk_schema", "customer_confirmation", "manual_entry"]


@dataclass(frozen=True)
class RecognitionDecision:
    outcome: RecognitionOutcome
    risk: RecognitionRisk
    accepted_value: AcceptedStructuredValue | None = field(default=None, repr=False)
    candidate: RecognitionHypothesis | None = field(default=None, repr=False)
    consensus: bool = False


class StructuredRecognitionPolicy:
    """Agreement is corroboration, not proof: sensitive values require read-back consent.

    These recognizers share a vendor and waveform; correlated omissions remain possible.
    Conflicting/ambiguous candidates never authorize picking either recognizer's guess.
    """

    @staticmethod
    def requires_consensus(kind):
        return kind in RISKS and RISKS[kind] != RecognitionRisk.low

    def decide(self, expected_kind, first, second=None):
        valid = [h for h in (first, second) if h is not None and h.valid_schema]
        risk = max(
            (RISKS.get(h.kind, RecognitionRisk.low) for h in valid),
            key=lambda r: list(RecognitionRisk).index(r),
            default=RISKS.get(expected_kind, RecognitionRisk.low),
        )
        if not valid:
            return RecognitionDecision(RecognitionOutcome.repair_required, risk)
        if any(h and h.evidence == "ambiguous" for h in (first, second)):
            return RecognitionDecision(RecognitionOutcome.repair_required, risk)
        if risk == RecognitionRisk.low:
            chosen = valid[0]
            if (
                second
                and second.valid_schema
                and second.canonical_candidate != chosen.canonical_candidate
            ):
                return RecognitionDecision(RecognitionOutcome.repair_required, risk)
            return RecognitionDecision(
                RecognitionOutcome.accepted,
                risk,
                AcceptedStructuredValue(chosen.kind, chosen.canonical_candidate, "low_risk_schema"),
            )
        if len(valid) == 2 and (
            valid[0].kind != valid[1].kind
            or valid[0].canonical_candidate != valid[1].canonical_candidate
        ):
            return RecognitionDecision(RecognitionOutcome.repair_required, risk)
        return RecognitionDecision(
            RecognitionOutcome.confirmation_required,
            risk,
            candidate=valid[0],
            consensus=len(valid) == 2 and first.source != second.source,
        )
