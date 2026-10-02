"""Signed Vonage callbacks and WebSocket lifecycle over the existing runtime."""

import asyncio
import hashlib
import hmac
import logging
from time import monotonic, time

import jwt
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.speech.stt.streaming_provider import OpenAIStreamingSTT
from app.speech.tts.openai_provider import OpenAITTSProvider
from app.telephony.base import CallStarted, ProviderAudio, ProviderError
from app.telephony.providers.vonage import VonageTelephonyProvider
from app.telephony.providers.vonage_audio import CONTENT_TYPE, L16Input
from app.telephony.providers.vonage_messages import (
    Answer,
    CallEvent,
    Cleared,
    Connected,
    Dtmf,
    Notify,
    control_adapter,
)
from app.telephony.runtime import PhoneRuntime
from app.telephony.vonage_calls import MEDIA_PATH, application_id, public_origin, trial_numbers

logger = logging.getLogger(__name__)
TERMINAL = {
    "completed",
    "busy",
    "cancelled",
    "unanswered",
    "rejected",
    "failed",
    "timeout",
    "disconnected",
}


class VonageGateway:
    def __init__(
        self, settings: Settings, runtime: PhoneRuntime, provider: VonageTelephonyProvider
    ):
        self.origin = public_origin(settings.public_base_url)
        self.application_id = application_id(settings)
        self.from_number, self.to_number = trial_numbers(settings)
        if not settings.vonage_api_key or not settings.vonage_signature_secret:
            raise ValueError(
                "Vonage API key and signature secret are required for signed callbacks"
            )
        self.api_key = settings.vonage_api_key
        self._signature_secret = settings.vonage_signature_secret.get_secret_value()
        if not self._signature_secret.strip():
            raise ValueError("Empty signature secret")
        self.runtime, self.provider = runtime, provider
        self.pending: dict[str, float] = {}
        self.known: set[str] = set()
        self.closed: set[str] = set()

    def authenticate(self, authorization: str, body: bytes | None = None) -> bool:
        """Official signed-webhook JWT shape; TLS remains required for every endpoint."""
        if not authorization.startswith("Bearer ") or len(authorization) > 8192:
            return False
        try:
            claims = jwt.decode(
                authorization[7:],
                self._signature_secret,
                algorithms=["HS256"],
                issuer="Vonage",
                leeway=30,
                options={"require": ["iat", "jti", "iss", "api_key"]},
            )
            issued = claims["iat"]
            if (
                not isinstance(issued, int)
                or not 0 <= time() - issued + 30 <= 330
                or not isinstance(claims["jti"], str)
                or not 0 < len(claims["jti"]) <= 128
                or claims["api_key"] != self.api_key
                or claims.get("application_id", self.application_id) != self.application_id
            ):
                return False
            # Vonage documents payload checking as optional under TLS. Verify when supplied.
            if body is not None and "payload_hash" in claims:
                digest = claims["payload_hash"]
                if not isinstance(digest, str) or not hmac.compare_digest(
                    digest, hashlib.sha256(body).hexdigest()
                ):
                    return False
            return True
        except (jwt.PyJWTError, ValueError, TypeError):
            return False

    def answer(self, answer: Answer) -> list[dict]:
        if answer.to != self.to_number or answer.from_number != self.from_number:
            raise ValueError("Call is outside configured trial destination/caller")
        now = monotonic()
        self.pending = {uuid: deadline for uuid, deadline in self.pending.items() if deadline > now}
        if answer.uuid in self.closed or self.runtime.registry.get(answer.uuid):
            raise ValueError("Closed or already active call")
        if (
            len(self.pending) >= 100
            and answer.uuid not in self.pending
            or len(self.known) >= 1000
            and answer.uuid not in self.known
        ):
            raise ValueError("Call capacity exceeded")
        self.known.add(answer.uuid)
        self.pending[answer.uuid] = now + 120
        return [
            {
                "action": "connect",
                "endpoint": [
                    {
                        "type": "websocket",
                        "uri": "wss://" + self.origin.removeprefix("https://") + MEDIA_PATH,
                        "content-type": CONTENT_TYPE,
                        "headers": {"call_uuid": answer.uuid},
                        "authorization": {"type": "vonage"},
                    }
                ],
            }
        ]

    async def event(self, event: CallEvent):
        # Never persist arbitrary callback data or phone numbers. Connected-leg UUIDs may differ.
        logger.info("vonage event call_uuid=%s status=%s", event.uuid, event.status)
        if event.uuid not in self.known:
            return
        if event.status in TERMINAL or event.type == "error":
            self.pending.pop(event.uuid, None)
            self.closed.add(event.uuid)
            if event.status in {"failed", "rejected", "timeout"} or event.type == "error":
                await self.runtime.handle_event(ProviderError(event.uuid, "vonage_call_failed"))
            else:
                await self.runtime.end_call(event.uuid, hangup=False)

    async def serve(self, socket: WebSocket):
        stream = None
        session = None
        failed = False
        audio_frames = 0
        close_code = None
        close_reason = "receive_loop_ended"
        phase = "receive"
        try:
            while True:
                if stream and stream.closed:
                    close_reason = "provider_closed"
                    break
                phase = "receive"
                async with asyncio.timeout(300 if stream else 10):
                    packet = await socket.receive()
                if packet["type"] == "websocket.disconnect":
                    close_code = packet.get("code", 1005)
                    # Peer reason is untrusted and may contain credentials/transcripts.
                    close_reason = "peer_disconnect"
                    break
                if packet["type"] != "websocket.receive":
                    raise ValueError("Unexpected WebSocket packet type")
                audio = packet.get("bytes")
                if audio is not None:
                    phase = "audio_validation"
                    if stream is None or not audio or len(audio) % 2 or len(audio) > 3200:
                        raise ValueError("Invalid binary audio")
                    audio_frames += 1
                    if audio_frames == 1:
                        logger.info(
                            "vonage first_binary_audio call_uuid=%s frame_bytes=%s audio_frames=1",
                            stream.call_id,
                            len(audio),
                        )
                    if self.runtime.registry.get(stream.call_id) is None:
                        close_reason = "runtime_closed"
                        break
                    if session.status not in ("active", "transcribing"):
                        stream.decoder = None
                        continue
                    if stream.decoder is None:
                        stream.decoder = L16Input()
                    phase = "audio_decode"
                    for pcm in stream.decoder.decode(audio):
                        phase = "audio_feed"
                        await self.runtime.feed_audio(
                            stream.call_id, ProviderAudio(pcm), wait_for_capacity=True
                        )
                        if self.runtime.registry.get(stream.call_id) is None:
                            close_reason = "runtime_closed"
                            return
                    continue
                phase = "control_validation"
                raw = packet.get("text")
                if not isinstance(raw, str) or len(raw.encode()) > 8192:
                    raise ValueError("Invalid control message")
                control = control_adapter.validate_json(raw)
                logger.info(
                    "vonage control event=%s call_uuid=%s",
                    control.event,
                    control.call_uuid
                    if isinstance(control, Connected)
                    else (stream.call_id if stream else None),
                )
                phase = "control_dispatch"
                if isinstance(control, Connected):
                    if stream is not None or self.pending.pop(control.call_uuid, 0) <= monotonic():
                        raise ValueError("Unadmitted or duplicate call connection")
                    if control.call_uuid in self.closed:
                        raise ValueError("Call already ended")
                    stream = self.provider.bind(control.call_uuid, socket)
                    session = self.runtime.start_call(
                        CallStarted(
                            control.call_uuid,
                            {
                                "provider": "vonage",
                                "call_uuid": control.call_uuid,
                            },
                        )
                    )
                    logger.info(
                        "vonage started call_uuid=%s session_id=%s content_type=%s",
                        stream.call_id,
                        session.session_id,
                        control.content_type,
                    )
                    continue  # Connected is initialization; keep receiving binary/control frames.
                elif stream is None:
                    raise ValueError("Connection must precede controls")
                elif isinstance(control, Notify):
                    self.provider.acknowledge(stream, control.payload.reply_id)
                elif isinstance(control, Cleared):
                    logger.info("vonage buffer_cleared call_uuid=%s", stream.call_id)
                elif isinstance(control, Dtmf):
                    logger.info("vonage dtmf_ignored call_uuid=%s", stream.call_id)
        except WebSocketDisconnect as error:
            close_code = error.code
            close_reason = "peer_disconnect"
        except asyncio.CancelledError:
            close_reason = "cancelled"
            raise
        except Exception as error:
            failed = True
            close_code = 1008
            close_reason = "protocol_or_transport_error"
            logger.warning(
                "vonage protocol_or_transport_error call_uuid=%s phase=%s exception_type=%s "
                "message=websocket_receive_processing_failed",
                stream.call_id if stream else None,
                phase,
                type(error).__name__,
            )
            try:
                await socket.close(code=1008)
            except Exception:
                pass
        finally:
            if stream:
                self.closed.add(stream.call_id)
                if session and session.error_code:
                    close_reason = session.error_code
                try:
                    if failed:
                        await self.runtime.handle_event(
                            ProviderError(stream.call_id, "vonage_protocol_error")
                        )
                    else:
                        await self.runtime.end_call(stream.call_id, cancel=True, hangup=False)
                except Exception as error:
                    logger.warning(
                        "vonage cleanup_error call_uuid=%s exception_type=%s "
                        "message=runtime_cleanup_failed",
                        stream.call_id,
                        type(error).__name__,
                    )
                await self.provider.close(stream.call_id)
            elif not failed:
                close_code = close_code or 1000
                try:
                    await socket.close(code=1000)
                except Exception:
                    pass
            logger.info(
                "vonage closed call_uuid=%s audio_frames=%s close_code=%s close_reason=%s",
                stream.call_id if stream else None,
                audio_frames,
                close_code if close_code is not None else 1000,
                close_reason,
            )

    async def shutdown(self):
        self.pending.clear()
        await self.runtime.shutdown()


def build_vonage_gateway(settings: Settings, messages) -> VonageGateway | None:
    if not settings.vonage_enabled:
        return None
    values = (settings.openai_router_model, settings.backend_tts_model, settings.backend_tts_voice)
    if (
        not settings.openai_api_key
        or not settings.openai_api_key.get_secret_value().strip()
        or not all(isinstance(value, str) and value.strip() for value in values)
    ):
        logger.warning("vonage unavailable: configure existing OpenAI routing and phone TTS")
        return None
    try:
        provider = VonageTelephonyProvider()
        key = settings.openai_api_key.get_secret_value()
        runtime = PhoneRuntime(
            messages,
            OpenAIStreamingSTT(api_key=key),
            OpenAITTSProvider(
                api_key=key, model=settings.backend_tts_model, voice=settings.backend_tts_voice
            ),
            provider,
        )
        return VonageGateway(settings, runtime, provider)
    except ValueError:
        logger.warning(
            "vonage unavailable: configure application, signed callbacks, destination and HTTPS"
        )
        return None
