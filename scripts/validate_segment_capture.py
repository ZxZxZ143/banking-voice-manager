"""Loopback-only browser fixture with live RT/TTS and explicit ASR fault injection.

Only initial whole failures and specified bounded results are injected. Unmodified
segment/yes audio uses live providers. Never mount these routes in production.
"""

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
from app.speech.structured.recognition import BoundedTranscriber
from app.speech.tts.factory import build_tts_provider

OUTPUT = ROOT / "work/segment-capture"
AUDIO = {
    "whole": "Семь семь семь пять два три два восемь шесть два.",
    "first": "Восемь семь семь семь.",
    "middle": "Пять два три.",
    "last": "Два восемь шесть два.",
    "yes": "Да, верно.",
    "iin_first": "Один два три четыре пять шесть.",
    "iin_last": "Семь восемь девять ноль один два.",
}
settings = Settings(
    event_db_path=OUTPUT / "synthetic.db", twilio_enabled=False, vonage_enabled=False
)
app = create_app(settings)
active = {}
observations = []
original_relay = voice.relay


class FaultBounded(BoundedTranscriber):
    async def transcribe(self, pcm, context):
        if context.expected_kind == "none":
            # Clear RU/KK confirmations stay single-pass; ambiguous ones may recover.
            return await super().transcribe(pcm, context)
        case, sid = active["case"], active["sid"]
        capture = app.state.services.dialogs.get(sid).conversation.structured_capture
        initial = context.capture_part == "whole"
        first = context.capture_part == "first"
        attempts = capture.segment_attempts.get("first", 0) if capture else 0
        if initial or first and case == "single":
            observations.append({"provider": "bounded", "injected": "unavailable"})
            raise TimeoutError()
        if first and case in {"disagreement", "keyboard"} and (attempts == 0 or case == "keyboard"):
            observations.append({"provider": "bounded", "injected": "conflicting_segment"})
            return "8771"
        observations.append({"provider": "bounded", "injected": False})
        return await super().transcribe(pcm, context)


async def fault_relay(websocket, upstream, detector, **options):
    context = options["context"]
    iterator = upstream.__aiter__()

    class InitialFailure:
        async def send(self, raw):
            await upstream.send(raw)

        def __aiter__(self):
            return self

        async def __anext__(self):
            raw = await iterator.__anext__()
            event = json.loads(raw)
            if event.get("type", "").endswith("input_audio_transcription.completed"):
                if context.expected_kind != "none" and context.capture_part == "whole":
                    event["transcript"] = "неразборчиво"
                    observations.append({"provider": "realtime", "injected": "whole_failure"})
                else:
                    observations.append({"provider": "realtime", "injected": False})
            return json.dumps(event)

    await original_relay(websocket, InitialFailure(), detector, **options)


voice.BoundedTranscriber = FaultBounded
voice.relay = fault_relay


@app.post("/segment/seed/{case}/{session_id}")
def seed(case: str, session_id: UUID):
    if case not in {"single", "dual", "disagreement", "keyboard", "iin"}:
        raise HTTPException(404)
    sid = str(session_id)
    active.update(case=case, sid=sid)
    observations.clear()
    kind = "iin" if case == "iin" else "phone"
    app.state.services.dialogs.save(
        DialogState(
            session_id=sid,
            active_scenario="SC25",
            response_language="ru",
            slots={"contact_field": "email"},
            conversation=ConversationState(
                expected_slot=kind, phase="collect", policy_relationship="existing"
            ),
        )
    )
    return {
        "response_text": "Назовите ИИН, пожалуйста."
        if kind == "iin"
        else "Назовите телефон, пожалуйста."
    }


@app.get("/segment/audio/{name}")
def audio(name: str):
    if name not in AUDIO or not (OUTPUT / f"{name}.mp3").exists():
        raise HTTPException(404)
    return FileResponse(OUTPUT / f"{name}.mp3", media_type="audio/mpeg")


@app.get("/segment/check/{session_id}")
def check(session_id: UUID):
    if str(session_id) != active.get("sid"):
        raise HTTPException(404)
    state = app.state.services.dialogs.get(str(session_id))
    capture = state.conversation.structured_capture
    expected = "123456789012" if active["case"] == "iin" else "+77775232862"
    provided = state.identification.provided_values.get(
        "iin" if active["case"] == "iin" else "phone", []
    )
    expected_parts = ["123456", "789012"] if active["case"] == "iin" else ["8777", "523", "2862"]
    return {
        "phase": capture.phase if capture else None,
        "draft_count": len(capture.parts) if capture else 0,
        "attempts": capture.segment_attempts if capture else {},
        "manual": bool(capture and capture.manual_requested),
        "segment_matches": bool(
            capture
            and capture.segment_candidate
            and len(capture.parts) < len(expected_parts)
            and capture.segment_candidate == expected_parts[len(capture.parts)]
        ),
        "accepted_expected": provided == [expected],
        "source_preserved": bool(
            capture
            and capture.candidate == ("123456789012" if active["case"] == "iin" else "87775232862")
        ),
        "lookups": len(state.client_lookup_attempts),
        "status": state.conversation_status,
        "observations": observations,
    }


async def generate():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    provider = build_tts_provider(settings)
    for name, text in AUDIO.items():
        path = OUTPUT / f"{name}.mp3"
        if not path.exists():
            result = await provider.synthesize(text, "ru")
            path.write_bytes(result.audio)
            print(name, "generated", flush=True)


if __name__ == "__main__":
    if "--generate" in sys.argv:
        asyncio.run(generate())
    else:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8015, access_log=False)
