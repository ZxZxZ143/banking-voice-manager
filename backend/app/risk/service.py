from dataclasses import dataclass
from time import perf_counter

from app.agent.errors import RouterError, RouterOutputError
from app.conversation.language import stable_response_language
from app.risk.language import security_language
from app.risk.models import RiskAssessment, RiskContext, RiskInput, SecurityDecision
from app.risk.models import RiskSignal as S
from app.risk.policy import SecurityPolicy, assessment_reason, guidance_for
from app.risk.precheck import precheck
from app.risk.privacy import redact_authentication, redact_risk_input


@dataclass
class RiskRun:
    assessment: RiskAssessment | None
    decision: SecurityDecision | None
    precheck_ms: float
    agent_ms: float | None = None


class RiskIntelligence:
    def __init__(self, agent, policy: SecurityPolicy):
        self.agent, self.policy = agent, policy

    async def analyze(
        self,
        text,
        *,
        active_assistant,
        language=None,
        channel="text",
        context: RiskContext | None = None,
        force=False,
    ) -> RiskRun:
        started = perf_counter()
        context = (context or RiskContext()).model_copy(deep=True)
        candidate = precheck(text, security_followup=bool(context.pending_question))
        precheck_ms = (perf_counter() - started) * 1000
        if not candidate.analyze and not force:
            return RiskRun(None, None, precheck_ms)
        payload = RiskInput(
            current_text=redact_risk_input(redact_authentication(text, context.pending_question))[
                :10000
            ],
            language=language,
            channel=channel,
            active_assistant=active_assistant,
            context=context,
        )
        call_started = perf_counter()
        try:
            decision = await self.agent.analyze(payload)
            if type(decision) is not SecurityDecision:
                raise RouterOutputError()
            # The model interprets the safe answer; the application applies its known
            # question contract. This uses no utterance regexes or evaluation labels.
            if context.pending_question and decision.intent not in (
                "operator_request",
                "goodbye",
                "out_of_scope",
            ):
                signals = list(context.previous_signals)
                exposure = None
                if decision.answer is True:
                    if context.pending_question == "exposure":
                        if S.OTP_REQUESTED in signals:
                            exposure = S.OTP_DISCLOSED
                        elif S.PIN_PASSWORD_REQUESTED in signals or S.CVV_REQUESTED in signals:
                            exposure = S.CREDENTIAL_DISCLOSED
                    elif context.pending_question == "remote_installed":
                        exposure = S.REMOTE_ACCESS_INSTALLED
                if exposure:
                    decision = decision.model_copy(
                        update={
                            "intent": "concern",
                            "risk_relevant": True,
                            "signals": list(dict.fromkeys(signals + decision.signals + [exposure])),
                            "level": "critical",
                            "recommended_action": "urgent_security_review",
                            "case_type": "remote_access"
                            if exposure == S.REMOTE_ACCESS_INSTALLED
                            else "credential_exposure",
                        }
                    )
                elif (
                    decision.answer is True
                    and context.pending_question == "link_exposure"
                    and signals
                ):
                    decision = decision.model_copy(
                        update={
                            "intent": "concern",
                            "risk_relevant": True,
                            "signals": list(dict.fromkeys(signals + decision.signals)),
                            "level": "high",
                            "recommended_action": "security_review",
                            "case_type": "phishing",
                        }
                    )
                elif (
                    decision.answer is False
                    or context.pending_question == "transaction_kind"
                    and decision.transaction_kind
                ) and signals:
                    decision = decision.model_copy(
                        update={
                            "intent": "concern",
                            "risk_relevant": True,
                            "signals": list(dict.fromkeys(signals + decision.signals)),
                            "level": "medium" if signals == [S.SUSPICIOUS_LINK] else "high",
                            "recommended_action": "show_security_guidance"
                            if signals == [S.SUSPICIOUS_LINK]
                            else "security_review",
                        }
                    )
                decision = SecurityDecision.model_validate(decision.model_dump())
            decision.response_language = security_language(
                text, decision.language, decision.response_language
            )
            if decision.intent in ("goodbye", "operator_request") and decision.language != "mixed":
                # Short terminal controls must not replace the established reply language
                # with a fresh model/default label. Keep mixed-language presentation unchanged.
                decision.response_language = stable_response_language(
                    text, context.response_language, None
                )
            assessment = RiskAssessment(
                risk_relevant=decision.risk_relevant,
                level=decision.level,
                signals=decision.signals,
                recommended_action=decision.recommended_action,
            )
            if assessment.risk_relevant:
                assessment.guidance_shown = guidance_for(assessment.signals)
            assessment.reason = (
                assessment_reason(assessment) if assessment.signals else "No reported incident"
            )
        except RouterError as exc:
            decision = None
            assessment = RiskAssessment(
                analysis_status="invalid_output"
                if isinstance(exc, RouterOutputError)
                else "unavailable",
                risk_relevant=None,
                error=exc.code,
                guidance_shown=list(candidate.immediate_guidance),
                reason="Security analysis unavailable; precautionary guidance only",
            )
        return RiskRun(assessment, decision, precheck_ms, (perf_counter() - call_started) * 1000)
