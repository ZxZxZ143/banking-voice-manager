"""Project only explicitly safe fields. Never serialize state, trace or a whole result."""

from datetime import UTC, datetime
from typing import get_args

from app.analytics.models import (
    ActionName,
    EndedPayload,
    FraudPayload,
    HandoffPayload,
    InsurancePayload,
    RiskPayload,
    SalesPayload,
    SelectedPayload,
    StartedPayload,
    TurnPayload,
    make_event,
)
from app.packs.contracts import GlobalConversationContext, ScenarioResult
from app.packs.fraud_security.models import FraudCaseResult
from app.packs.insurance_manager.pack import InsuranceResult
from app.packs.product_promoter.models import SalesLeadResult
from app.risk.models import RiskAssessment


def map_turn_events(
    context: GlobalConversationContext,
    assistant_id: str,
    result: ScenarioResult,
    risk: RiskAssessment | None,
    *,
    previous_assistant: str | None,
    assistant_initiated: bool,
    emit_result: bool = True,
    product_ids: frozenset[str] = frozenset(),
    scenario_ids: frozenset[str] = frozenset(),
    created_at: datetime | None = None,
):
    events = []
    common = dict(
        created_at=created_at or datetime.now(UTC),
        session_id=context.session_id,
        turn_number=context.turn_number,
        channel=context.channel,
        assistant_id=assistant_id,
        conversation_status=context.conversation_status,
    )

    def add(payload, **metadata):
        events.append(
            make_event(
                **common, sequence=len(events), event_type=payload.kind, payload=payload, **metadata
            )
        )

    if context.turn_number == 1:
        add(StartedPayload(assistant_initiated=assistant_initiated))
    if previous_assistant != assistant_id:
        add(SelectedPayload(previous_assistant_id=previous_assistant))
    add(TurnPayload(assistant_initiated=assistant_initiated))
    if emit_result:
        if isinstance(result, InsuranceResult):
            add(
                InsurancePayload(
                    completed=result.completed,
                    handoff=result.handoff,
                    actions=sorted(set(result.actions) & set(get_args(ActionName))),
                ),
                scenario_id=result.scenario_id if result.scenario_id in scenario_ids else None,
                result_status=result.status,
            )
        elif isinstance(result, SalesLeadResult):
            add(
                SalesPayload(
                    campaign={
                        "product_promoter": "deposit",
                        "card_promoter": "card",
                        "loan_promoter": "loan",
                    }[assistant_id],
                    product_category=result.product_category,
                    selected_product_id=(
                        result.selected_product_id
                        if result.selected_product_id in product_ids
                        else None
                    ),
                    presented_product_ids=sorted(set(result.presented_products) & product_ids),
                    outcome=result.outcome,
                    interest_level=result.interest_level,
                    next_action=result.next_action,
                    completed=result.completed,
                    handoff=result.handoff,
                ),
                result_status=result.status,
            )
        elif isinstance(result, FraudCaseResult):
            add(
                FraudPayload(
                    case_type=result.case_type,
                    case_status=result.case_status,
                    facts=result.facts,
                    recommended_action=(result.risk.recommended_action if result.risk else "none"),
                    guidance_shown=result.guidance_shown,
                    completed=result.completed,
                    handoff=result.handoff,
                ),
                result_status=result.status,
                risk_level=result.risk.level if result.risk else None,
                risk_signals=result.facts,
            )
    # Include attempted-but-unavailable Risk analyses; never imply successful assessment.
    if risk and (risk.risk_relevant or risk.analysis_status != "analyzed"):
        add(
            RiskPayload(
                analysis_status=risk.analysis_status,
                recommended_action=risk.recommended_action,
                guidance_shown=risk.guidance_shown,
            ),
            risk_level=risk.level,
            risk_signals=risk.signals,
        )
    if context.conversation_status == "handoff":
        add(HandoffPayload())
    elif context.conversation_status == "ended":
        add(EndedPayload())
    return events
