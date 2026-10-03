"""Private/local browser synthesis. Public ingress must allow signed phone routes only."""

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import ValidationError

from app.speech.errors import SpeechConfigurationError, SpeechProviderError
from app.speech.tts.base import SpeechRequest

router = APIRouter()


@router.post("/api/speech/tts")
async def speech(request: Request):
    allowed = {
        request.app.state.settings.frontend_origin,
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    }
    if request.headers.get("origin") not in allowed:
        raise HTTPException(403, "speech_origin_denied")
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "speech_json_required")
    body = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 20_000:
                    raise HTTPException(413, "speech_request_too_large")
    except TimeoutError:
        raise HTTPException(408, "speech_request_timeout") from None
    try:
        payload = SpeechRequest.model_validate_json(bytes(body))
    except ValidationError:
        # Never echo submitted text through FastAPI validation errors.
        raise HTTPException(422, "invalid_speech_request") from None
    provider = request.app.state.tts_provider
    if provider is None:
        raise HTTPException(503, "backend_speech_unavailable")

    async def disconnected():
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                return

    synthesis = asyncio.create_task(provider.synthesize(payload.text, payload.language))
    disconnect = asyncio.create_task(disconnected())
    try:
        async with asyncio.timeout(35):
            done, _ = await asyncio.wait(
                {synthesis, disconnect}, return_when=asyncio.FIRST_COMPLETED
            )
            if disconnect in done:
                raise HTTPException(499, "speech_cancelled")
            result = synthesis.result()
        if result.content_type not in {"audio/mpeg", "audio/wav"} or len(result.audio) > 8_000_000:
            raise SpeechProviderError("Invalid synthesis response.")
        return Response(
            result.audio,
            media_type=result.content_type,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Speech-Provider": "openai",
                "X-Speech-Language": payload.language,
            },
        )
    except SpeechConfigurationError:
        raise HTTPException(503, "backend_speech_unavailable") from None
    except (SpeechProviderError, TimeoutError):
        raise HTTPException(502, "backend_speech_failed") from None
    finally:
        synthesis.cancel()
        disconnect.cancel()
        await asyncio.gather(synthesis, disconnect, return_exceptions=True)
