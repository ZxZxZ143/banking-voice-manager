"""Twilio transport only. PhoneRuntime owns STT, Agent, TTS, and turn state."""

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4

from fastapi import WebSocket

from app.speech.tts.base import SpeechResult
from app.telephony.providers.twilio_audio import MulawInput, speech_to_mulaw

logger = logging.getLogger(__name__)


class PlaybackCancelled(RuntimeError):
    pass


@dataclass
class TwilioStream:
    call_id: str
    stream_id: str
    socket: WebSocket
    decoder: MulawInput | None = field(default_factory=MulawInput)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    marks: dict[str, asyncio.Future] = field(default_factory=dict)
    closed: bool = False


class TwilioTelephonyProvider:
    def __init__(self, *, playback_timeout_seconds: float = 120):
        if not 0 < playback_timeout_seconds <= 120:
            raise ValueError("Invalid playback timeout")
        self.playback_timeout_seconds = playback_timeout_seconds
        self.streams: dict[str, TwilioStream] = {}

    def bind(self, call_id: str, stream_id: str, socket: WebSocket) -> TwilioStream:
        if call_id in self.streams or any(s.stream_id == stream_id for s in self.streams.values()):
            raise ValueError("Duplicate Twilio stream")
        stream = TwilioStream(call_id, stream_id, socket)
        self.streams[call_id] = stream
        return stream

    def acknowledge(self, stream: TwilioStream, name: str) -> None:
        if self.streams.get(stream.call_id) is not stream or stream.closed:
            return
        future = stream.marks.pop(name, None)
        if future is not None and not future.done():
            future.set_result(None)
            logger.info(
                "twilio playback_complete call_sid=%s stream_sid=%s mark=%s monotonic_ms=%.3f",
                stream.call_id,
                stream.stream_id,
                name,
                perf_counter() * 1000,
            )

    async def send_audio(self, call_id: str, speech: SpeechResult) -> None:
        stream = self.streams[call_id]
        started = perf_counter()
        try:
            audio = await asyncio.to_thread(speech_to_mulaw, speech)
        except Exception:
            logger.warning(
                "twilio output_conversion_failed call_sid=%s stream_sid=%s",
                call_id,
                stream.stream_id,
            )
            raise
        name = "reply-" + uuid4().hex
        future = asyncio.get_running_loop().create_future()
        try:
            async with stream.lock:
                if stream.closed or self.streams.get(call_id) is not stream:
                    raise PlaybackCancelled("Stream closed during conversion")
                stream.marks[name] = future
                playback_at = perf_counter()
                logger.info(
                    "twilio playback_start call_sid=%s stream_sid=%s mark=%s "
                    "monotonic_ms=%.3f conversion_lock_ms=%.3f",
                    call_id,
                    stream.stream_id,
                    name,
                    playback_at * 1000,
                    (playback_at - started) * 1000,
                )
                for offset in range(0, len(audio), 800):
                    await stream.socket.send_json(
                        {
                            "event": "media",
                            "streamSid": stream.stream_id,
                            "media": {
                                "payload": base64.b64encode(audio[offset : offset + 800]).decode()
                            },
                        }
                    )
                await stream.socket.send_json(
                    {
                        "event": "mark",
                        "streamSid": stream.stream_id,
                        "mark": {"name": name},
                    }
                )
            logger.info(
                "twilio audio_sent call_sid=%s stream_sid=%s mark=%s conversion_send_ms=%.1f",
                call_id,
                stream.stream_id,
                name,
                (perf_counter() - started) * 1000,
            )
            async with asyncio.timeout(self.playback_timeout_seconds):
                await future
        except TimeoutError:
            logger.warning(
                "twilio playback_timeout call_sid=%s stream_sid=%s mark=%s",
                call_id,
                stream.stream_id,
                name,
            )
            raise
        finally:
            stream.marks.pop(name, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # consume a concurrent clear exception even on task cancellation

    async def clear(self, stream: TwilioStream) -> None:
        # Twilio also acknowledges cleared marks; remove them BEFORE sending clear.
        for future in stream.marks.values():
            if not future.done():
                future.set_exception(PlaybackCancelled("Playback cleared"))
        stream.marks.clear()
        await stream.socket.send_json({"event": "clear", "streamSid": stream.stream_id})
        logger.info(
            "twilio playback_cleared call_sid=%s stream_sid=%s", stream.call_id, stream.stream_id
        )

    async def hangup(self, call_id: str) -> None:
        # Closing Connect/Stream resumes the webhook's final Hangup TwiML.
        await self.close(call_id)

    async def close(self, call_id: str) -> None:
        stream = self.streams.pop(call_id, None)
        if stream is None:
            return
        stream.closed = True
        # Always settle pending futures, even if a network send is blocked.
        for future in stream.marks.values():
            if not future.done():
                future.set_exception(PlaybackCancelled("Stream closed"))
        stream.marks.clear()
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
