from app.conversation.terminal import terminal_reply
from app.packs.contracts import InteractionMode, PackTurn, ScenarioManifest
from app.packs.fraud_security.models import FraudCaseResult, FraudContext, FraudPublicState
from app.risk.agent import RISK_INSTRUCTIONS
from app.risk.language import security_language
from app.risk.models import RiskSignal as S
from app.risk.models import SecurityDecision
from app.risk.service import RiskRun
from app.tracing.models import TraceRecord

FRAUD_MANIFEST = ScenarioManifest(
    id="fraud_security",
    name="Fraud & Security",
    interaction_mode=InteractionMode.CONSULTATIVE,
    supported_languages=("ru", "kk", "mixed"),
    output_schema="FraudCaseResult",
    public_description="Synthetic security guidance and safe fact collection for human review. "
    "No confirmed-fraud verdicts or banking operations.",
)


class FraudSecurityPack:
    manifest = FRAUD_MANIFEST
    state_schema = FraudContext
    output_schema = FraudCaseResult
    prompt = RISK_INSTRUCTIONS
    tools = ()
    policies = ("never request authentication secrets", "advisory only", "manual selection")
    completion_rules = "Explicit operator/farewell or concern needing human review."

    def __init__(self, intelligence):
        self.intelligence = intelligence
        self.knowledge = intelligence.policy

    def new_context(self):
        return FraudContext()

    async def open_turn(self, global_context, context):
        reply = (
            "Здравствуйте! Я виртуальный помощник по безопасности Merei Demo Bank. "
            "Что случилось? Секретные коды и данные карты не называйте."
        )
        return self._turn(
            global_context, context, None, reply, "active", "open", None, "scenario.opening"
        )

    async def handle_turn(self, text, global_context, context):
        run = await self.intelligence.analyze(
            text,
            active_assistant=self.manifest.id,
            language=global_context.language,
            channel=global_context.channel,
            context=context.risk_context(),
            force=True,
        )
        return await self.handle_assessed_turn(text, global_context, context, run)

    async def handle_assessed_turn(self, text, global_context, context, run: RiskRun):
        decision, assessment = run.decision, run.assessment
        language = (
            decision.response_language
            if decision
            else security_language(text, global_context.language, context.response_language)
        )
        context.response_language = language
        ru = language == "ru"
        if decision and decision.risk_relevant and decision.confidence >= 0.6:
            context.facts = list(dict.fromkeys(context.facts + decision.signals))
            if decision.case_type != "none":
                context.case_type = decision.case_type
            context.transaction_kind = decision.transaction_kind or context.transaction_kind
        # Apply the existing fact-based review rule before a semantic farewell can close.
        review = False
        if decision and decision.confidence >= 0.6:
            signals = set(context.facts)
            review = bool(
                signals
                & {
                    S.OTP_DISCLOSED,
                    S.CREDENTIAL_DISCLOSED,
                    S.REMOTE_ACCESS_INSTALLED,
                    S.COERCED_TRANSFER_SENT,
                    S.LOST_CARD,
                    S.ACCOUNT_TAKEOVER,
                    S.CONTACT_CHANGE,
                }
            )
            review |= S.UNKNOWN_TRANSACTION in signals and context.transaction_kind is not None
            review |= decision.answer is True and context.pending_question == "link_exposure"
        if decision and decision.intent in ("operator_request", "goodbye"):
            keys = assessment.guidance_shown[:2] if review and decision.intent == "goodbye" else []
            assessment.guidance_shown = keys
            status = "handoff" if decision.intent == "operator_request" or review else "ended"
            context.pending_question = None
            reply = " ".join(self.knowledge.text(key, language) for key in keys)
            reply = (reply + " " + terminal_reply(status, language)).strip()
            return self._turn(
                global_context,
                context,
                run,
                reply,
                status,
                "needs_review" if status == "handoff" else "informed",
                decision,
            )
        if not decision:
            guidance = assessment.guidance_shown if assessment else []
            prefix = (
                "Сейчас не удалось оценить ситуацию. "
                if ru
                else "Қазір жағдайды бағалау мүмкін болмады. "
            )
            reply = prefix + " ".join(self.knowledge.text(k, language) for k in guidance[:2])
            reply += " " + self.knowledge.text("official_channels", language)
            if assessment:
                assessment.guidance_shown = list(
                    dict.fromkeys(guidance[:2] + ["official_channels"])
                )
            return self._turn(global_context, context, run, reply.strip(), "active", "open", None)
        if decision.intent == "out_of_scope":
            reply = (
                "Я помогаю с безопасностью: подозрительные звонки, ссылки и операции. "
                "Что случилось?"
                if ru
                else "Мен күмәнді қоңыраулар, сілтемелер мен операциялардың қауіпсіздігі "
                "бойынша көмектесемін. Не болды?"
            )
            return self._turn(global_context, context, run, reply, "active", "open", decision)
        if (
            decision.intent == "general_info"
            or not decision.risk_relevant
            and decision.intent != "unclear"
        ):
            context.pending_question = None
            reply = self.knowledge.education.ru if ru else self.knowledge.education.kk
            return self._turn(global_context, context, run, reply, "active", "informed", decision)
        if decision.intent == "unclear" or decision.confidence < 0.6:
            context.unclear_count = min(3, context.unclear_count + 1)
            status = "handoff" if context.unclear_count == 3 else "active"
            keys = assessment.guidance_shown[:1] if assessment and status == "active" else []
            reply = (
                terminal_reply(status, language)
                if status == "handoff"
                else self.knowledge.text("concern_details", language, question=True)
            )
            if keys:
                reply = " ".join(self.knowledge.text(k, language) for k in keys) + " " + reply
            if assessment:
                assessment.guidance_shown = keys
            return self._turn(
                global_context,
                context,
                run,
                reply,
                status,
                "needs_review" if status == "handoff" else "open",
                decision,
            )
        context.unclear_count = 0
        context.facts = list(dict.fromkeys(context.facts + decision.signals))
        context.transaction_kind = decision.transaction_kind or context.transaction_kind
        previous_question = context.pending_question
        context.pending_question = None
        signals = set(context.facts)
        guidance = assessment.guidance_shown if assessment else []
        question = None
        if not review:
            if S.UNKNOWN_TRANSACTION in signals:
                question = "transaction_kind"
            elif signals & {S.OTP_REQUESTED, S.PIN_PASSWORD_REQUESTED, S.CVV_REQUESTED}:
                question = "exposure"
            elif S.REMOTE_ACCESS_REQUESTED in signals:
                question = "remote_installed"
            elif S.SUSPICIOUS_LINK in signals:
                question = "link_exposure"
        # An explicit safe negative ends collection for this question; never repeat it.
        if decision.answer is False and previous_question:
            question = None
        if question in context.asked_questions:
            question = None
        keys = guidance[:2] or ["official_channels"]
        reply = " ".join(self.knowledge.text(k, language) for k in keys)
        status, case_status = "active", "informed"
        if review:
            status, case_status = "handoff", "needs_review"
            reply += " " + terminal_reply("handoff", language)
        elif question:
            context.pending_question = question
            context.asked_questions.append(question)
            reply += " " + self.knowledge.text(question, language, question=True)
            case_status = "open"
        elif "official_channels" not in keys:
            reply += " " + self.knowledge.text("official_channels", language)
            keys = keys + ["official_channels"]
        if assessment:
            assessment.guidance_shown = keys
        return self._turn(global_context, context, run, reply, status, case_status, decision)

    def _turn(
        self, global_context, context, run, reply, status, case_status, decision, event="user.turn"
    ):
        assessment = run.assessment if run else None
        if assessment and assessment.guidance_shown:
            context.guidance_shown = list(
                dict.fromkeys(context.guidance_shown + assessment.guidance_shown)
            )
        result = FraudCaseResult(
            status=status,
            completed=status != "active" or case_status == "informed",
            handoff=status == "handoff",
            case_type=context.case_type,
            case_status=case_status,
            facts=context.facts.copy(),
            transaction_kind=context.transaction_kind,
            risk=assessment,
            guidance_shown=context.guidance_shown.copy(),
        )
        routing = decision or SecurityDecision(
            intent="unclear",
            language=context.response_language,
            response_language=context.response_language,
            risk_relevant=False,
            level="none",
            signals=[],
            recommended_action="none",
            confidence=0,
        )
        trace = TraceRecord(
            event_type=event,
            turn=global_context.turn_number + 1,
            transcript="",
            language=routing.language,
            reason=assessment.reason if assessment else "Manually selected security assistant",
            conversation_act=routing.intent,
            clarification=bool(context.pending_question),
            source_keys=[
                "security.policy." + k for k in (assessment.guidance_shown if assessment else [])
            ],
            manager_summary=result.model_dump(mode="json"),
        )
        return PackTurn(
            context=context,
            language=routing.language,
            response_text=reply,
            routing=routing,
            public_state=FraudPublicState(
                **context.model_dump(),
                session_id=global_context.session_id,
                turn_number=global_context.turn_number + 1,
                fraud_case=result,
            ),
            trace=trace,
            result=result,
            complete_pack=status != "active",
        )
