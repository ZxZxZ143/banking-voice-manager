"""Render security advice while retaining the selected business pack and its state."""

from typing import Literal

from pydantic import Field, SerializeAsAny

from app.conversation.status import ConversationStatus
from app.conversation.terminal import terminal_reply
from app.core.contracts import Contract
from app.packs.contracts import PackTurn
from app.risk.language import security_language
from app.risk.models import RiskAssessment
from app.tracing.models import TraceRecord


class SecurityGuardDecision(Contract):
    kind: Literal["security_guidance"]
    response_language: Literal["ru", "kk"]


class RiskGuidanceMessageResponse(Contract):
    session_id: str
    response_text: str
    routing: SecurityGuardDecision
    state: SerializeAsAny[Contract]
    trace: TraceRecord
    conversation_status: ConversationStatus
    risk: RiskAssessment | None = Field(default=None, exclude_if=lambda v: v is None)


async def guidance_turn(pack, global_context, entry, run, text, policy):
    # Snapshot is a pack-produced, redacted public projection, never its private state.
    if entry.public_state is None or entry.result is None:
        opening = await pack.open_turn(
            global_context.model_copy(deep=True), entry.state.model_copy(deep=True)
        )
        public, result = opening.public_state, opening.result
        # No prior business state exists. Keep the pack's own zero-model initial projection.
        entry.state = opening.context.model_copy(deep=True)
    else:
        public, result = (
            entry.public_state.model_copy(deep=True),
            entry.result.model_copy(deep=True),
        )
    decision, assessment = run.decision, run.assessment
    language = (
        decision.response_language
        if decision
        else security_language(text, global_context.language, "ru")
    )
    status = result.status
    if decision and decision.intent in ("operator_request", "goodbye"):
        assessment.guidance_shown = []
        status = "handoff" if decision.intent == "operator_request" else "ended"
        reply = terminal_reply(status, language)
        result = result.model_copy(
            update={"status": status, "handoff": status == "handoff", "completed": True}
        )
    else:
        keys = (assessment.guidance_shown or ["official_channels"])[:2]
        reply = " ".join(policy.text(k, language) for k in keys)
        if assessment.analysis_status != "analyzed":
            reply = (
                "Оценка риска сейчас недоступна. "
                if language == "ru"
                else "Қазір тәуекелді бағалау қолжетімсіз. "
            ) + reply
        if "official_channels" not in keys:
            reply += " " + policy.text("official_channels", language)
        assessment.guidance_shown = list(dict.fromkeys(keys + ["official_channels"]))
    # Update only shared wire metadata. The selected pack's business state/result survive.
    metadata = {
        "turn_number": global_context.turn_number + 1,
        "session_id": global_context.session_id,
        "language": decision.language if decision else global_context.language,
        "conversation_status": status,
    }
    public = public.model_copy(
        update={k: v for k, v in metadata.items() if k in type(public).model_fields}
    )
    trace = TraceRecord(
        turn=global_context.turn_number + 1,
        transcript="",
        language=decision.language if decision else global_context.language,
        reason=assessment.reason,
        conversation_act="security_guidance",
        policy_outcome="security_advisory",
        source_keys=["security.policy." + k for k in assessment.guidance_shown],
    )
    return PackTurn(
        context=entry.state.model_copy(deep=True),
        language=decision.language if decision else global_context.language,
        response_text=reply,
        routing=SecurityGuardDecision(kind="security_guidance", response_language=language),
        public_state=public,
        trace=trace,
        result=result,
        complete_pack=status in ("handoff", "ended"),
    )
