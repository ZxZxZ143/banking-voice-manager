"""App-owned capabilities of the grounded business layer, not catalog name guesses."""

from typing import Literal

from pydantic import Field

from app.core.contracts import Contract

# These are implemented by read_only.py / response.insurance / response.routing.
GROUNDED_EXECUTABLE = frozenset(
    {
        "find_client",
        "get_policies",
        "get_policy",
        "get_claim",
        "get_bm_class",
        "calc_ogpo_price",
        "calc_casco_price",
        "calc_travel_price",
        "calc_property_price",
        "calc_accident_price",
        "check_payment",
        "check_coverage",
        "list_clinics",
        "get_offices",
        "kb_lookup",
    }
)


class ManagerSummary(Contract):
    reason: Literal[
        "operation_requires_human",
        "client_not_found",
        "record_not_found",
        "specialist_required",
        "lookup_exhausted",
    ]
    scenario: str
    business_problem: Literal[
        "existing_policy_status",
        "policy_documents",
        "payment_without_issuance",
        "renewal",
        "claim_status",
        "claim_review",
        "policy_change",
        "claim_registration",
        "policy_cancellation",
        "medical_assistance",
        "insurance_service",
    ] = "insurance_service"
    collected_fields: list[str] = Field(default_factory=list)
    unavailable_fields: list[str] = Field(default_factory=list)
    failed_lookup_fields: list[str] = Field(default_factory=list)
    known_client: bool
    completed_read_only_checks: list[str] = Field(default_factory=list)
    next_required_action: str | None


class ActionCapabilities:
    def __init__(self, actions):
        self.definitions = {action.name: action for action in actions.actions}

    def capability(self, name: str) -> Literal["executable", "requires_human"]:
        if name not in self.definitions:
            raise ValueError("Action missing from authoritative catalog")
        return "executable" if name in GROUNDED_EXECUTABLE else "requires_human"

    def next_unavailable(self, scenario) -> str | None:
        return next((a for a in scenario.actions if self.capability(a) == "requires_human"), None)

    def summary(self, state, scenario, checks, reason="operation_requires_human"):
        return self.make_summary(
            state,
            scenario,
            checks,
            reason,
            "operator_review" if reason == "lookup_exhausted" else self.next_unavailable(scenario),
        )

    @staticmethod
    def make_summary(state, scenario, checks, reason, next_action):
        return ManagerSummary(
            reason=reason,
            scenario=scenario.scenario_id,
            business_problem={
                "SC25": "existing_policy_status",
                "SC26": "policy_documents",
                "SC39": "policy_documents",
                "SC30": "payment_without_issuance",
                "SC27": "renewal",
                "SC17": "claim_status",
                "SC19": "claim_review",
                "SC20": "claim_review",
                "SC04": "policy_change",
                "SC05": "policy_change",
                "SC28": "policy_cancellation",
                "SC13": "claim_registration",
                "SC14": "claim_registration",
                "SC16": "claim_registration",
                "SC15": "medical_assistance",
            }.get(scenario.scenario_id, "insurance_service"),
            collected_fields=sorted(
                {k for k, v in state.slots.items() if v not in (None, "", [])}
                | state.identification.provided_values.keys()
            ),
            unavailable_fields=list(state.identification.unavailable_fields),
            failed_lookup_fields=list(state.identification.failed_fields),
            known_client=state.client_id is not None,
            completed_read_only_checks=list(
                dict.fromkeys(a for a in checks if a in GROUNDED_EXECUTABLE)
            ),
            next_required_action=next_action,
        )
