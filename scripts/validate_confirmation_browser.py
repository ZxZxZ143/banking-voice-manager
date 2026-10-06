"""Loopback-only synthetic Conversation Demo gate. Never mounted in production."""

# ruff: noqa: E402
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.api.websocket import voice
from app.core.config import Settings
from app.main import create_app
from app.packs.insurance_manager.state import ConversationState, DialogState
from app.speech.structured.capture import StructuredCapture, capture_question
from app.speech.structured.correction import parse_confirmation
from app.speech.structured.recognition import BoundedTranscriber
from app.speech.tts.factory import build_tts_provider

OUTPUT = ROOT / "work/confirmation-stt"
AUDIO = {
    "ru_yes": ("Да.", "ru"),
    "ru_no": ("Нет.", "ru"),
    "kk_yes": ("Иә.", "kk"),
    "kk_no": ("Жоқ.", "kk"),
}
CASES = {
    "live_ru_yes",
    "live_ru_no",
    "live_kk_yes",
    "live_kk_no",
    "recover_ru_yes",
    "fixture_ru_yes",
    "fixture_unresolved",
    "fixture_kk_yes",
    "fixture_kk_no",
}
PHONE = "+77775232862"  # Existing synthetic demo fixture, never a production identifier.
settings = Settings(
    event_db_path=OUTPUT / "browser-synthetic.db", twilio_enabled=False, vonage_enabled=False
)
app = create_app(settings)
active, observations = {}, []
original_relay = voice.relay


class ConfirmationBounded(BoundedTranscriber):
    async def transcribe(self, pcm, context):
        assert context.confirmation_kind == "phone"
        assert PHONE not in context.model_dump_json()
        case = active["case"]
        fixture = {
            "fixture_ru_yes": "Да.",
            "fixture_unresolved": "No.",
            "fixture_kk_yes": "Иә.",
            "fixture_kk_no": "Жоқ.",
        }.get(case)
        result = fixture if fixture else await super().transcribe(pcm, context)
        observations.append(
            {
                "provider": "bounded",
                "fixture": bool(fixture),
                "status": parse_confirmation(result, "phone").kind,
            }
        )
        return result


async def confirmation_relay(websocket, upstream, detector, **options):
    iterator = upstream.__aiter__()

    class Observed:
        async def send(self, raw):
            await upstream.send(raw)

        def __aiter__(self):
            return self

        async def __anext__(self):
            raw = await iterator.__anext__()
            event = json.loads(raw)
            if event.get("type", "").endswith("input_audio_transcription.completed"):
                injected = not active["case"].startswith("live_")
                if injected:
                    event["transcript"] = "No."
                observations.append(
                    {
                        "provider": "realtime",
                        "fixture": injected,
                        "status": parse_confirmation(event["transcript"], "phone").kind,
                    }
                )
            return json.dumps(event)

    await original_relay(websocket, Observed(), detector, **options)


voice.BoundedTranscriber = ConfirmationBounded
voice.relay = confirmation_relay


@app.post("/confirmation/seed/{case}/{session_id}")
def seed(case: str, session_id: UUID):
    if case not in CASES:
        raise HTTPException(404)
    language = "kk" if "kk" in case else "ru"
    sid = str(session_id)
    active.update(case=case, sid=sid)
    observations.clear()
    capture = StructuredCapture("phone", "phone", "SC25", "confirmation", candidate=PHONE)
    question = capture_question(capture, language)
    capture.prompt = question
    app.state.services.dialogs.save(
        DialogState(
            session_id=sid,
            active_scenario="SC25",
            response_language=language,
            slots={"contact_field": "email"},
            conversation=ConversationState(
                expected_slot="phone",
                phase="collect",
                last_question=question,
                structured_capture=capture,
                policy_relationship="existing",
            ),
        )
    )
    return {"response_text": question, "language": language}


@app.get("/confirmation/audio/{name}")
def audio(name: str):
    path = OUTPUT / f"browser-{name}.mp3"
    if name not in AUDIO or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/confirmation/check/{session_id}")
def check(session_id: UUID):
    if str(session_id) != active.get("sid"):
        raise HTTPException(404)
    state = app.state.services.dialogs.get(str(session_id))
    capture = state.conversation.structured_capture
    return {
        "phase": capture.phase if capture else None,
        "candidate_retained": bool(capture and capture.candidate == PHONE),
        "attempts": capture.confirmation_attempts if capture else None,
        "accepted_expected": state.identification.provided_values.get("phone") == [PHONE],
        "iin_fallback": bool(
            state.identification.provided_values.get("iin")
            or "phone" in state.identification.unavailable_fields
        ),
        "lookups": len(state.client_lookup_attempts),
        "status": state.conversation_status,
        "observations": observations,
    }


async def generate():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    provider = build_tts_provider(settings)
    for name, (text, language) in AUDIO.items():
        path = OUTPUT / f"browser-{name}.mp3"
        if not path.exists():
            result = await provider.synthesize(text, language)
            path.write_bytes(result.audio)
            print(name, "generated", flush=True)


if __name__ == "__main__":
    if "--generate" in sys.argv:
        asyncio.run(generate())
    else:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8016, access_log=False)
