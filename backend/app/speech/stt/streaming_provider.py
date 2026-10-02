"""Reuse the current OpenAI streaming configuration and local endpointing for phone."""

import asyncio
import json

from websockets.asyncio.client import connect

from app.speech.audio import PCM_SAMPLE_RATE
from app.speech.stt.endpointing import SpeechEndDetector
from app.speech.stt.streaming import EmitEvent, ReceiveInput, relay_stream


async def configure_transcription(upstream):
    await upstream.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "type": "transcription",
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": PCM_SAMPLE_RATE},
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


class OpenAIStreamingSTT:
    def __init__(self, *, api_key: str, pause_ms: int = 2500):
        if not api_key.strip():
            raise ValueError("Streaming STT requires a server API key.")
        if type(pause_ms) is not int or not 500 <= pause_ms <= 5000:
            raise ValueError("pause_ms must be between 500 and 5000.")
        self._api_key = api_key
        self._pause_ms = pause_ms

    async def run(self, receive: ReceiveInput, emit: EmitEvent) -> None:
        async with asyncio.timeout(150):
            detector = await asyncio.to_thread(SpeechEndDetector, self._pause_ms)
            async with connect(
                "wss://api.openai.com/v1/realtime?intent=transcription",
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
                open_timeout=20,
                close_timeout=3,
                max_size=2_000_000,
            ) as upstream:
                await configure_transcription(upstream)
                await relay_stream(receive, emit, upstream, detector, phone_timing=True)
