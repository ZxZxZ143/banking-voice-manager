"""Vonage binary PCM transport and native playback notifications."""

import asyncio
import logging
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import WebSocket

from app.speech.tts.base import SpeechResult
from app.telephony.providers.vonage_audio import FRAME_BYTES, L16Input, speech_to_l16

logger = logging.getLogger(__name__)


class PlaybackCancelled(RuntimeError):
    pass


@dataclass
class VonageStream:
    call_id: str
    socket: WebSocket
    decoder: L16Input | None = field(default_factory=L16Input)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    notifications: dict[str, asyncio.Future] = field(default_factory=dict)
    closed: bool = False


class VonageTelephonyProvider:
    def __init__(self, *, playback_timeout_seconds: float = 90):
        if not 0 < playback_timeout_seconds <= 90:
            raise ValueError("Invalid playback timeout")
        self.playback_timeout_seconds = playback_timeout_seconds
        self.streams: dict[str, VonageStream] = {}

    def bind(self, call_id: str, socket: WebSocket) -> VonageStream:
        if call_id in self.streams:
            raise ValueError("Call already bound")
        stream = VonageStream(call_id, socket)
        self.streams[call_id] = stream
        return stream

    def acknowledge(self, stream: VonageStream, reply_id: str):
        if self.streams.get(stream.call_id) is not stream or stream.closed:
            return
        future = stream.notifications.pop(reply_id, None)
        if future is not None and not future.done():
            future.set_result(None)
            logger.info(
                "vonage playback_complete call_uuid=%s reply_id=%s", stream.call_id, reply_id
            )

    async def send_audio(self, call_id: str, speech: SpeechResult):
        stream = self.streams[call_id]
        try:
            audio = await asyncio.to_thread(speech_to_l16, speech)
        except Exception:
            logger.warning("vonage output_conversion_failed call_uuid=%s", call_id)
            raise
        reply_id = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        try:
            async with stream.lock:
                if stream.closed or self.streams.get(call_id) is not stream:
                    raise PlaybackCancelled("Stream closed during conversion")
                stream.notifications[reply_id] = future
                for offset in range(0, len(audio), FRAME_BYTES):
                    frame = audio[offset : offset + FRAME_BYTES]
                    await stream.socket.send_bytes(frame.ljust(FRAME_BYTES, b"\0"))
                await stream.socket.send_json(
                    {"action": "notify", "payload": {"reply_id": reply_id}}
                )
            logger.info("vonage audio_sent call_uuid=%s reply_id=%s", call_id, reply_id)
            async with asyncio.timeout(self.playback_timeout_seconds):
                await future
        except TimeoutError:
            logger.warning("vonage playback_timeout call_uuid=%s", call_id)
            raise
        finally:
            stream.notifications.pop(reply_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    def invalidate(self, stream: VonageStream):
        for future in stream.notifications.values():
            if not future.done():
                future.set_exception(PlaybackCancelled("Playback cleared or closed"))
        stream.notifications.clear()

    async def clear(self, stream: VonageStream):
        self.invalidate(stream)
        await stream.socket.send_json({"action": "clear"})

    async def hangup(self, call_id: str):
        # The only NCCO action is connect: ending that WebSocket finishes the NCCO/call.
        await self.close(call_id)

    async def close(self, call_id: str):
        stream = self.streams.pop(call_id, None)
        if stream is None:
            return
        stream.closed = True
        self.invalidate(stream)
        try:
            async with asyncio.timeout(0.5):
                async with stream.lock:
                    await self.clear(stream)
        except Exception:
            pass
        finally:
            try:
                await stream.socket.close(code=1000)
            except Exception:
                pass
