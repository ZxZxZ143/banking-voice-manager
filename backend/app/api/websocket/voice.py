"""Local test bench: browser PCM24 -> OpenAI, automatic commit via Silero."""

import asyncio
import base64
import json
from time import perf_counter
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect

from app.speech.stt.endpointing import SpeechEndDetector

router = APIRouter()


async def relay(websocket: WebSocket, upstream, detector: SpeechEndDetector):
    committed_at = None
    ended = asyncio.Event()
    total_bytes = 0
    start = perf_counter()

    async def commit():
        nonlocal committed_at
        if committed_at is not None:
            return
        if not detector.tracker.has_speech:
            await websocket.send_json({"type": "empty", "message": "Речь не обнаружена."})
            ended.set()
            return
        committed_at = perf_counter()
        await websocket.send_json({"type": "committed"})
        await upstream.send(json.dumps({"type": "input_audio_buffer.commit"}))

    async def receive_audio():
        nonlocal total_bytes
        while not ended.is_set():
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                ended.set()
                return
            pcm = message.get("bytes")
            if pcm is not None:
                if committed_at is not None:
                    continue
                if not pcm or len(pcm) > 4800 or len(pcm) % 2:
                    raise ValueError("Invalid PCM frame")
                total_bytes += len(pcm)
                if total_bytes > 48000 * 120:
                    raise ValueError("Audio limit exceeded")
                await upstream.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(pcm).decode("ascii"),
                        }
                    )
                )
                finished, probability = await asyncio.to_thread(detector.feed, pcm)
                await websocket.send_json(
                    {
                        "type": "activity",
                        "speech": probability >= 0.5,
                        "has_speech": detector.tracker.has_speech,
                        "silence_ms": detector.tracker.silence_ms,
                        "audio_ms": round(total_bytes / 48),
                    }
                )
                if finished:
                    await commit()
                elif not detector.tracker.has_speech and total_bytes >= 48000 * 15:
                    await commit()
            elif message.get("text"):
                if len(message["text"]) > 256:
                    raise ValueError("Control message too large")
                control = json.loads(message["text"])
                if control.get("type") == "cancel":
                    ended.set()
                elif control.get("type") == "finish":
                    await commit()
                else:
                    raise ValueError("Unknown control message")

    async def receive_text():
        async for raw in upstream:
            event = json.loads(raw)
            kind = event.get("type", "")
            if kind == "error" or kind.endswith(".failed"):
                raise RuntimeError("Provider error")
            if kind.endswith("input_audio_transcription.delta"):
                await websocket.send_json(
                    {
                        "type": "transcript.partial",
                        "delta": event.get("delta", ""),
                        "item_id": event.get("item_id"),
                        "received_ms": round((perf_counter() - start) * 1000),
                    }
                )
            elif kind.endswith("input_audio_transcription.completed"):
                if committed_at is None:
                    raise RuntimeError("Unexpected completion")
                await websocket.send_json(
                    {
                        "type": "utterance.final",
                        "text": event["transcript"],
                        "item_id": event.get("item_id"),
                        "language": None,
                        "stt_after_commit_ms": round((perf_counter() - committed_at) * 1000),
                        "endpoint_silence_ms": detector.tracker.silence_ms,
                        "audio_ms": round(total_bytes / 48),
                    }
                )
                ended.set()
                return
        if not ended.is_set():
            raise RuntimeError("Provider disconnected")

    async def commit_deadline():
        while not ended.is_set():
            await asyncio.sleep(0.2)
            if committed_at is not None and perf_counter() - committed_at > 30:
                raise TimeoutError("Final transcript timeout")

    tasks = [
        asyncio.create_task(fn())
        for fn in (receive_audio, receive_text, commit_deadline, ended.wait)
    ]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


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
            pause = config.get("pause_ms", 2500)
            if (
                config.get("type") != "start"
                or config.get("sample_rate") != 24000
                or config.get("channels") != 1
                or type(pause) is not int
                or not 500 <= pause <= 5000
            ):
                raise ValueError("Invalid stream configuration")
            detector = await asyncio.to_thread(SpeechEndDetector, pause)
            async with connect(
                "wss://api.openai.com/v1/realtime?intent=transcription",
                additional_headers={
                    "Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"
                },
                open_timeout=20,
                close_timeout=3,
                max_size=2_000_000,
            ) as upstream:
                await upstream.send(
                    json.dumps(
                        {
                            "type": "session.update",
                            "session": {
                                "type": "transcription",
                                "audio": {
                                    "input": {
                                        "format": {"type": "audio/pcm", "rate": 24000},
                                        "transcription": {
                                            "model": "gpt-live-transcribe",
                                            "languages": ["kk", "ru"],
                                            "delay": "medium",
                                            "prompt": (
                                                "Insurance customer speech in Kazakh "
                                                "and Russian, sometimes mixed."
                                            ),
                                        },
                                        "turn_detection": None,
                                    }
                                },
                            },
                        }
                    )
                )
                async with asyncio.timeout(20):
                    while True:
                        event = json.loads(await upstream.recv())
                        if event.get("type") == "error":
                            raise RuntimeError("Provider configuration error")
                        if event.get("type") == "session.updated":
                            break
                await websocket.send_json({"type": "ready", "pause_ms": pause})
                await relay(websocket, upstream, detector)
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
    except Exception:
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
