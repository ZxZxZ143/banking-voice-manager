"""Signed Twilio admission and per-socket protocol lifecycle."""

import asyncio
import base64
import logging
from time import monotonic
from urllib.parse import urlsplit

from fastapi import WebSocket, WebSocketDisconnect
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse

from app.core.config import Settings
from app.speech.errors import SpeechConfigurationError
from app.speech.stt.streaming_provider import OpenAIStreamingSTT
from app.speech.tts.factory import build_tts_provider
from app.telephony.base import CallStarted, ProviderAudio, ProviderError
from app.telephony.providers.twilio import TwilioTelephonyProvider
from app.telephony.providers.twilio_audio import MulawInput
from app.telephony.providers.twilio_messages import (
    Connected,
    Dtmf,
    Mark,
    Media,
    Start,
    Stop,
    message_adapter,
)
from app.telephony.runtime import PhoneRuntime

logger = logging.getLogger(__name__)
VOICE_PATH = "/api/v1/telephony/twilio/voice"
MEDIA_PATH = "/api/v1/telephony/twilio/media"


class TwilioGateway:
    def __init__(
        self, settings: Settings, runtime: PhoneRuntime, provider: TwilioTelephonyProvider
    ):
        parsed = urlsplit(settings.public_base_url or "")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin")
        if (
            not settings.twilio_auth_token
            or not settings.twilio_auth_token.get_secret_value().strip()
            or not settings.twilio_account_sid
        ):
            raise ValueError("Twilio credentials are required")
        self.base_url = (settings.public_base_url or "").rstrip("/")
        self.account_sid = settings.twilio_account_sid
        self.validator = RequestValidator(settings.twilio_auth_token.get_secret_value())
        self.runtime = runtime
        self.provider = provider
        self.pending: dict[str, float] = {}

    def valid_signature(
        self, path: str, signature: str, params, *, websocket: bool = False
    ) -> bool:
        url = self.base_url + path
        # Twilio's WS signing can use the HTTPS upgrade URL or WSS stream URL.
        # All candidates are pinned to this configured origin/path; no forwarded headers.
        urls = [url]
        if websocket:
            urls.extend(
                [
                    url + "/",
                    "wss://" + url.removeprefix("https://"),
                    "wss://" + url.removeprefix("https://") + "/",
                ]
            )
        return bool(signature) and any(self.validator.validate(u, params, signature) for u in urls)

    def admit(self, call_id: str) -> str:
        now = monotonic()
        self.pending = {sid: deadline for sid, deadline in self.pending.items() if deadline > now}
        if self.runtime.registry.get(call_id) is not None:
            raise ValueError("Call already active")
        if len(self.pending) >= 100 and call_id not in self.pending:
            raise ValueError("Twilio admission capacity exceeded")
        self.pending[call_id] = now + 120
        response = VoiceResponse()
        response.connect().stream(
            url="wss://" + self.base_url.removeprefix("https://") + MEDIA_PATH
        )
        response.hangup()
        return str(response)

    async def serve(self, socket: WebSocket) -> None:
        stream = None
        normal_stop = False
        failed = False
        connected = False
        sequence = 0
        media_chunk = 0
        media_timestamp = -1
        try:
            while True:
                async with asyncio.timeout(300 if stream else 10):
                    raw = await socket.receive_text()
                if len(raw.encode("utf-8")) > 8192:
                    raise ValueError("Oversized Twilio message")
                message = message_adapter.validate_json(raw)
                if isinstance(message, Connected):
                    if connected or stream:
                        raise ValueError("Duplicate connected")
                    connected = True
                    continue
                if not connected or int(message.sequenceNumber) != sequence + 1:
                    raise ValueError("Invalid event order")
                sequence = int(message.sequenceNumber)
                if isinstance(message, Start):
                    start = message.start
                    if stream or message.streamSid != start.streamSid:
                        raise ValueError("Duplicate or mismatched start")
                    if start.accountSid != self.account_sid:
                        raise ValueError("Account mismatch")
                    deadline = self.pending.pop(start.callSid, 0)
                    if deadline <= monotonic():
                        raise ValueError("Call was not admitted")
                    stream = self.provider.bind(start.callSid, start.streamSid, socket)
                    session = self.runtime.start_call(
                        CallStarted(
                            start.callSid,
                            {
                                "provider": "twilio",
                                "call_sid": start.callSid,
                                "stream_sid": start.streamSid,
                            },
                        )
                    )
                    logger.info(
                        "twilio started call_sid=%s stream_sid=%s session_id=%s",
                        stream.call_id,
                        stream.stream_id,
                        session.session_id,
                    )
                    continue
                if stream is None or message.streamSid != stream.stream_id:
                    raise ValueError("Stream mismatch")
                if isinstance(message, Media):
                    chunk, timestamp = int(message.media.chunk), int(message.media.timestamp)
                    if chunk <= media_chunk or timestamp < media_timestamp:
                        raise ValueError("Invalid media order")
                    media_chunk, media_timestamp = chunk, timestamp
                    payload = base64.b64decode(message.media.payload, validate=True)
                    if not 0 < len(payload) <= 800:
                        raise ValueError("Invalid audio size")
                    session = self.runtime.registry.get(stream.call_id)
                    if session is None:
                        break
                    if session.status not in ("active", "transcribing"):
                        stream.decoder = None
                        continue
                    if stream.decoder is None:
                        stream.decoder = MulawInput()
                    for pcm in stream.decoder.decode(payload):
                        await self.runtime.feed_audio(stream.call_id, ProviderAudio(pcm))
                elif isinstance(message, Mark):
                    self.provider.acknowledge(stream, message.mark.name)
                elif isinstance(message, Stop):
                    if (
                        message.stop.callSid != stream.call_id
                        or message.stop.accountSid != self.account_sid
                    ):
                        raise ValueError("Stop identity mismatch")
                    normal_stop = True
                    break
                elif isinstance(message, Dtmf):
                    # Accepted protocol event; keypad-driven scenarios are deliberately deferred.
                    logger.info("twilio dtmf_ignored call_sid=%s", stream.call_id)
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            failed = True
            logger.warning(
                "twilio protocol_or_transport_error call_sid=%s stream_sid=%s",
                stream.call_id if stream else None,
                stream.stream_id if stream else None,
            )
            try:
                await socket.close(code=1008)
            except Exception:
                pass
        finally:
            if stream:
                if failed:
                    await self.runtime.handle_event(
                        ProviderError(stream.call_id, "twilio_protocol_error")
                    )
                else:
                    await self.runtime.end_call(
                        stream.call_id, cancel=not normal_stop, hangup=False
                    )
                logger.info(
                    "twilio closed call_sid=%s stream_sid=%s", stream.call_id, stream.stream_id
                )
                await self.provider.close(stream.call_id)
            elif not failed:
                try:
                    await socket.close(code=1000)
                except Exception:
                    pass

    async def shutdown(self):
        self.pending.clear()
        await self.runtime.shutdown()


def build_twilio_gateway(settings: Settings, messages, *, tts=None) -> TwilioGateway | None:
    if not settings.twilio_enabled:
        return None
    tts = tts or build_tts_provider(settings)
    required = (
        settings.openai_api_key,
        settings.openai_router_model,
        settings.backend_tts_model,
        settings.backend_tts_voice,
    )
    if (
        tts is None
        or not all(required)
        or any(isinstance(value, str) and not value.strip() for value in required)
        or (settings.openai_api_key and not settings.openai_api_key.get_secret_value().strip())
    ):
        logger.warning("twilio unavailable: configure OpenAI routing and backend TTS settings")
        return None
    try:
        provider = TwilioTelephonyProvider()
        key = settings.openai_api_key.get_secret_value()
        runtime = PhoneRuntime(
            messages,
            OpenAIStreamingSTT(
                api_key=key,
                pause_ms=settings.phone_endpoint_silence_ms,
                model=settings.streaming_stt_model,
                second_pass_model=settings.structured_stt_model,
            ),
            tts,
            provider,
        )
        return TwilioGateway(settings, runtime, provider)
    except (ValueError, SpeechConfigurationError):
        logger.warning("twilio unavailable: configure Twilio credentials and HTTPS PUBLIC_BASE_URL")
        return None
