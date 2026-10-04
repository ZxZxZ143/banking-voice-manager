"""LOCAL ONLY synthetic seeds/audio for the actual Conversation Demo browser gate.

Uses the real MessageService, live Router/Composer/Risk, live STT and Cedar TTS.
Never mount these fixture routes in the production app. No customer audio/data.
"""

# ruff: noqa: E402
import asyncio
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.core.config import Settings
from app.main import create_app
from app.packs.insurance_manager.state import ConversationState, DialogState
from app.speech.structured.capture import StructuredCapture, capture_question
from app.speech.tts.factory import build_tts_provider

OUTPUT = ROOT / "work/voice-latency"
CASES = {
    "short_reply": (None, None, "Хорошо."),
    "yes": ("vehicle_plate", "945ABC02", "Да."),
    "digit_correction": ("phone", "+77775232862", "Последняя цифра три."),
    "letter_correction": ("vehicle_plate", "945ABC02", "Нет, вместо эй — би."),
    "phone": ("phone", None, "Восемь семь семь семь пять два три два восемь шесть два."),
    "iin": ("iin", None, "Ноль ноль ноль один ноль один три ноль ноль ноль ноль ноль."),
    "region": ("region", None, "Ноль два."),
    "insurance": (None, None, "Где находится ваш офис в Алматы?"),
    "risk": (None, None, "Мне звонят из банка и просят назвать код из СМС."),
    "no_more": (None, None, "Нет, больше вопросов нет, спасибо."),
}
settings = Settings(
    frontend_origin="http://127.0.0.1:5174",  # Baseline; production allowlist also has 5173.
    event_db_path=OUTPUT / "synthetic.db",
    twilio_enabled=False,
    vonage_enabled=False,
    enable_dev_stand=False,
)
app = create_app(settings)
sessions = {}


@app.post("/validation/seed/{case}/{session_id}")
def seed(case: str, session_id: UUID):
    if case not in CASES:
        raise HTTPException(404)
    slot, candidate, _ = CASES[case]
    sid = str(session_id)
    scenario = "SC01" if slot in {"vehicle_plate", "region"} else "SC25" if slot else None
    capture = (
        StructuredCapture(slot, slot, scenario, "confirmation", candidate=candidate)
        if candidate
        else None
    )
    question = (
        capture_question(capture, "ru")
        if capture
        else ("Назовите номер, пожалуйста." if slot else "Чем я могу помочь?")
    )
    state = DialogState(
        session_id=sid,
        active_scenario=scenario,
        response_language="ru",
        slots={"vehicle_type": "car"} if scenario == "SC01" else {},
        conversation=ConversationState(
            expected_slot=slot,
            phase="collect" if slot else "wrap_up",
            policy_relationship="existing" if slot else "not_applicable",
            structured_capture=capture,
            last_question=question,
            last_assistant_act="verify_identifier"
            if capture
            else "ask_slot"
            if slot
            else "resolved",
        ),
    )
    app.state.services.dialogs.save(state)
    sessions[sid] = case
    return {"response_text": question}


@app.get("/validation/audio/{case}")
def audio(case: str):
    if case not in CASES or not (OUTPUT / f"{case}.mp3").exists():
        raise HTTPException(404)
    return FileResponse(OUTPUT / f"{case}.mp3", media_type="audio/mpeg")


@app.get("/validation/check/{session_id}")
def check(session_id: UUID):
    sid = str(session_id)
    if sid not in sessions:
        raise HTTPException(404)
    state = app.state.services.dialogs.get(sid)
    capture = state.conversation.structured_capture
    expected = {
        "digit_correction": "+77775232863",
        "letter_correction": "945BBC02",
        "phone": "+77775232862",
        "iin": "000101300000",
    }.get(sessions[sid])
    return {
        "pending_matches": bool(capture and capture.candidate == expected),
        "pending": capture is not None,
        "phase": state.conversation.phase,
        "lookups": len(state.client_lookup_attempts),
        "provided": bool(state.identification.provided_values),
        "status": state.conversation_status,
        "region_matches": state.slots.get("region") == "almaty",
    }


async def generate():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    provider = build_tts_provider(settings)
    for case, (_, _, words) in CASES.items():
        path = OUTPUT / f"{case}.mp3"
        if path.exists():
            continue
        try:
            result = await provider.synthesize(words, "ru")
            path.write_bytes(result.audio)
            print(case, "generated", flush=True)
        except Exception as error:
            print(case, type(error).__name__, flush=True)


if __name__ == "__main__":
    if "--generate" in sys.argv:
        asyncio.run(generate())
    else:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8013, access_log=False)
