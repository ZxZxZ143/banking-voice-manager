"""Local test bench: browser PCM24 -> OpenAI, automatic commit via Silero."""

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect

from app.speech.audio import PCM_CHANNELS, PCM_SAMPLE_RATE
from app.speech.structured.recognition import BoundedTranscriber
from app.speech.stt.adaptive_endpoint import AdaptiveEndpoint
from app.speech.stt.endpointing import SpeechEndDetector
from app.speech.stt.streaming import StreamInput, relay_stream
from app.speech.stt.streaming_provider import configure_transcription

router = APIRouter()


async def relay(websocket: WebSocket, upstream, detector: SpeechEndDetector, **options):
    async def receive():
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return StreamInput("cancel")
        if message.get("bytes") is not None:
            return StreamInput("audio", message["bytes"])
        raw = message.get("text", "")
        if len(raw) > 256:
            raise ValueError("Control message too large")
        kind = json.loads(raw).get("type")
        if kind not in ("finish", "cancel"):
            raise ValueError("Unknown control message")
        return StreamInput(kind)

    await relay_stream(receive, websocket.send_json, upstream, detector, **options)


@router.websocket("/api/v1/voice")
async def voice(websocket: WebSocket) -> None:
    settings = websocket.app.state.settings
    allowed = {settings.frontend_origin, "http://127.0.0.1:5173", "http://localhost:5173"}
    if websocket.headers.get("origin") not in allowed:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    if not settings.openai_api_key:
        await websocket.send_json(
            {
                "type": "error",
                "code": "missing_api_key",
                "message": "Добавьте OPENAI_API_KEY в .env backend.",
            }
        )
        await websocket.close(code=1013)
        return
    if websocket.app.state.voice_connections >= 2:
        await websocket.send_json(
            {"type": "error", "code": "busy", "message": "Стенд занят. Закройте другую запись."}
        )
        await websocket.close(code=1013)
        return
    websocket.app.state.voice_connections += 1
    try:
        async with asyncio.timeout(150):
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            if len(raw) > 1024:
                raise ValueError("Start message too large")
            config = json.loads(raw)
            UUID(config["session_id"])
            pause = config.get("pause_ms")
            if (
                config.get("type") != "start"
                or config.get("sample_rate") != PCM_SAMPLE_RATE
                or config.get("channels") != PCM_CHANNELS
                or (pause is not None and (type(pause) is not int or not 500 <= pause <= 5000))
            ):
                raise ValueError("Invalid stream configuration")
            messages = websocket.app.state.services.messages
            context, turn, slot = messages.transcription_snapshot(config["session_id"])
            adaptive = AdaptiveEndpoint(context) if pause is None else None
            pause = adaptive.base_ms if adaptive else pause
            detector = await asyncio.to_thread(SpeechEndDetector, pause)

            def record(text, outcome):
                return messages.record_recognition(config["session_id"], turn, slot, text, outcome)

            async with connect(
                "wss://api.openai.com/v1/realtime?intent=transcription",
                additional_headers={
                    "Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"
                },
                open_timeout=20,
                close_timeout=3,
                max_size=2_000_000,
            ) as upstream:
                await configure_transcription(upstream, context, settings.streaming_stt_model)
                await websocket.send_json(
                    {
                        "type": "ready",
                        "pause_ms": pause,
                        **({"endpoint_profile": adaptive.profile} if adaptive else {}),
                    }
                )
                await relay(
                    websocket,
                    upstream,
                    detector,
                    context=context,
                    second_pass=BoundedTranscriber(
                        settings.openai_api_key.get_secret_value(), settings.structured_stt_model
                    ),
                    record_recognition=record,
                    adaptive_endpoint=adaptive,
                )
    except WebSocketDisconnect:
        pass
    except ImportError:
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "voice_unavailable",
                    "message": (
                        "Не установлены зависимости голосового модуля. "
                        "Установите backend[voice] в окружении backend."
                    ),
                }
            )
        except Exception:
            pass
    except Exception as error:
        logging.getLogger(__name__).warning("voice_failed exception_type=%s", type(error).__name__)
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "voice_failed",
                    "message": (
                        "Ошибка голосового потока. "
                        "Проверьте соединение, формат аудио и доступ к модели."
                    ),
                }
            )
        except Exception:
            pass
    finally:
        websocket.app.state.voice_connections -= 1
        try:
            await websocket.close()
        except Exception:
            pass
