"""Pack-local admission before any identifier reaches slots or lookup memory."""

from dataclasses import dataclass, replace
from time import monotonic

from app.speech.structured.capture import (
    PARTS,
    StructuredCapture,
    accepted_result,
    assembled,
    capture_question,
)
from app.speech.structured.context import kind_for_slot
from app.speech.structured.correction import apply_correction, parse_confirmation
from app.speech.structured.normalization import recognize_expected
from app.speech.structured.policy import RISKS, RecognitionOutcome
from app.speech.structured.recognition import RecognitionMetadata, RecognitionResult


@dataclass
class CaptureStep:
    state: object
    speech: RecognitionResult
    question: str | None = None
    exhausted: bool = False


def advance_capture(
    previous, text, speech, channel, *, allow_unrecognized=False, manual_input_available=False
):
    meta = previous.conversation
    if not meta or not previous.active_scenario:
        return None
    if meta.resume_after_risk and not (
        speech and (speech.candidate or speech.metadata.candidate_count)
    ):
        return None
    pending = meta.structured_capture
    slot = meta.expected_slot
    kind = kind_for_slot(slot, previous.slots.get("contact_field"))
    if kind not in PARTS:
        return None
    if pending and (pending.slot != slot or pending.scenario != previous.active_scenario):
        pending = None
    if pending:
        kind = pending.kind
    if not pending and (not speech or speech.accepted_value):
        return None
    candidate = speech.candidate if speech else None
    answer = parse_confirmation(text, kind) if pending and pending.phase == "confirmation" else None
    manual = recognize_expected(text, kind) if pending and channel == "text" else None
    if (
        not allow_unrecognized
        and (answer is None or answer.kind == "unrelated")
        and not candidate
        and not (speech and speech.metadata.candidate_count)
        and not (manual and manual.accepted)
    ):
        return None
    state = previous.model_copy(deep=True)
    meta = state.conversation
    meta.resume_after_risk = False
    pending = meta.structured_capture if pending else None
    if speech is None:
        speech = RecognitionResult(
            RecognitionMetadata(
                mode="structured",
                expected_kind=kind,
                first_pass_valid=False,
                second_pass_used=False,
                candidate_count=0,
                accepted=False,
                risk=RISKS[kind],
            ),
            kind=kind,
        )
    step = CaptureStep(state, speech)

    def fallback():
        meta.structured_capture = None
        step.exhausted = True
        step.speech = RecognitionResult(
            speech.metadata.model_copy(
                update={
                    "accepted": False,
                    "outcome": RecognitionOutcome.manual_fallback,
                }
            ),
            kind=speech.kind,
        )
        step.question = (
            "Не удалось надёжно подтвердить номер. Подготовлю обращение для специалиста."
            if state.response_language == "ru"
            else "Нөмірді сенімді растау мүмкін болмады. Маманға өтініш дайындаймын."
        )
        return step

    def correction_fallback():
        if not manual_input_available or pending.manual_requested:
            return fallback()
        pending.manual_requested = True
        pending.pending_edit = None
        step.speech = RecognitionResult(
            speech.metadata.model_copy(
                update={
                    "accepted": False,
                    "outcome": RecognitionOutcome.manual_fallback,
                }
            ),
            kind=speech.kind,
        )
        step.question = (
            "Введите полный номер с клавиатуры. Если это неудобно, напишите «оператор»."
            if state.response_language == "ru"
            else "Толық нөмірді пернетақтамен енгізіңізші. Қолайсыз болса, «оператор» деп жазыңыз."
        )
        pending.prompt = step.question
        return step

    if pending and monotonic() > pending.expires_at:
        step = fallback()
        step.speech = RecognitionResult(
            step.speech.metadata.model_copy(update={"outcome": RecognitionOutcome.exhausted}),
            kind=speech.kind,
        )
        return step
    if manual and manual.accepted:
        meta.structured_capture = None
        meta.last_question = "[проверка номера]"
        meta.recognition_attempts.pop(slot, None)
        step.speech = accepted_result(speech, manual.kind, manual.value, "manual_entry")
        return step
    if pending and pending.manual_requested:
        return fallback()
    if pending and pending.phase == "confirmation":
        pending.confirmation_attempts += 1
        if answer.kind == "confirm" and pending.pending_edit is None:
            meta.structured_capture = None
            meta.last_question = "[проверка номера]"
            meta.recognition_attempts.pop(slot, None)
            step.speech = accepted_result(
                speech, pending.kind, pending.candidate, "customer_confirmation"
            )
            return step
        if answer.kind == "correction":
            if pending.correction_cycles >= 2:
                return correction_fallback()
            edit = answer.correction
            if pending.pending_edit and edit.position is not None and not edit.new_fragment:
                edit = replace(
                    pending.pending_edit,
                    position=edit.position,
                    segment=edit.segment or pending.pending_edit.segment,
                )
            corrected = apply_correction(pending.candidate, pending.kind, edit)
            if corrected:
                pending.candidate = corrected
                pending.correction_cycles += 1
                pending.pending_edit = None
                pending.confirmation_attempts = 0
            else:
                if pending.clarification_used:
                    return correction_fallback()
                pending.clarification_used = True
                pending.pending_edit = edit
                step.question = (
                    "Уточните позицию заменяемой цифры или буквы и новое значение. "
                    "Можно ввести номер с клавиатуры."
                    if state.response_language == "ru"
                    else "Өзгеретін цифрдың не әріптің орнын және жаңа мәнін айтыңызшы. "
                    "Нөмірді пернетақтамен енгізуге болады."
                )
                pending.prompt = step.question
                return step
        elif answer.kind == "reject" or candidate:
            if pending.repair_used:
                return fallback()
            pending.phase = "segments"
            pending.candidate = None
            pending.repair_used = True
            pending.confirmation_attempts = 0
        elif pending.confirmation_attempts >= 2:
            return fallback()
    elif pending and pending.phase == "segments":
        # Parts are drafts only. Each must be independently corroborated before assembly.
        if not candidate or not speech.metadata.consensus or candidate.kind != pending.kind:
            return fallback()
        pending.parts.append(candidate.canonical_candidate)
        if len(pending.parts) == len(PARTS[pending.kind]):
            pending.candidate = assembled(pending)
            if not pending.candidate:
                return fallback()
            pending.phase = "confirmation"
    elif candidate:
        pending = StructuredCapture(
            slot,
            candidate.kind,
            previous.active_scenario,
            "confirmation",
            candidate=candidate.canonical_candidate,
        )
    else:
        pending = StructuredCapture(
            slot,
            kind,
            previous.active_scenario,
            "segments",
            repair_used=True,
        )
    meta.structured_capture = pending
    meta.recognition_attempts[slot] = min(2, meta.recognition_attempts.get(slot, 0) + 1)
    step.speech = RecognitionResult(
        speech.metadata.model_copy(
            update={
                "outcome": RecognitionOutcome.confirmation_required
                if pending.phase == "confirmation"
                else RecognitionOutcome.repair_required,
            }
        ),
        kind=speech.kind,
        candidate=speech.candidate,
    )
    step.question = capture_question(pending, state.response_language)
    pending.prompt = step.question
    return step
