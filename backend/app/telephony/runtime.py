"""Half-duplex phone orchestration over the existing Agent and speech boundaries."""

import asyncio
import logging
import math
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from app.events.models import ConversationEvent, EventType
from app.events.response import response_events
from app.events.store import EventStore, InMemoryEventStore
from app.speech.stt.streaming import StreamingSTT, StreamInput
from app.speech.tts.base import SpeechLanguage, TTSProvider
from app.telephony.agent_bridge import AgentBridge, AgentProcessor, AgentResponse
from app.telephony.audio import AudioNormalizer, PcmPassThroughNormalizer
from app.telephony.base import (
    CallEnded,
    CallStarted,
    IncomingAudio,
    ProviderAudio,
    ProviderError,
    TelephonyEvent,
    TelephonyProvider,
)
from app.telephony.sessions import ActiveCallRegistry, PhoneSession, PhoneStatus

logger = logging.getLogger(__name__)
AUDIO_QUEUE_WAIT_SECONDS = 45  # Bounded VAD + upstream connect/configuration startup allowance.


@dataclass
class _Capture:
    queue: asyncio.Queue[StreamInput] = field(default_factory=lambda: asyncio.Queue(maxsize=16))
    accepting: bool = True
    backpressure_logged: bool = False
    speech_end_at: float | None = None
    endpoint_at: float | None = None


@dataclass(frozen=True)
class _TurnTiming:
    turn: int
    final_at: float
    speech_end_at: float | None
    endpoint_at: float | None


@dataclass
class _Call:
    session: PhoneSession
    capture: _Capture | None = None
    turn_task: asyncio.Task | None = None
    capture_tasks: set[asyncio.Task] = field(default_factory=set)
    final_ids: set[str] = field(default_factory=set)
    turn_number: int = 0


class PhoneRuntime:
    def __init__(
        self,
        messages: AgentProcessor,
        stt: StreamingSTT,
        tts: TTSProvider,
        provider: TelephonyProvider,
        *,
        normalizer: AudioNormalizer | None = None,
        event_store: EventStore | None = None,
        registry: ActiveCallRegistry | None = None,
        turn_timeout_seconds: float = 180,
        cleanup_timeout_seconds: float = 1,
    ):
        for value in (turn_timeout_seconds, cleanup_timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Phone timeouts must be finite and positive")
        self.agent = AgentBridge(messages)
        self.stt = stt
        self.tts = tts
        self.provider = provider
        self.normalizer = normalizer if normalizer is not None else PcmPassThroughNormalizer()
        self.event_store = event_store if event_store is not None else InMemoryEventStore()
        self.registry = registry if registry is not None else ActiveCallRegistry()
        self.turn_timeout_seconds = turn_timeout_seconds
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self._calls: dict[str, _Call] = {}

    def _current(self, call: _Call) -> bool:
        return self._calls.get(call.session.call_id) is call

    @staticmethod
    def _latency(
        call: _Call,
        stage: str,
        turn: int,
        at: float,
        duration_ms: float = 0,
        basis: str = "stage",
    ) -> None:
        # Fixed stage names/IDs and monotonic durations only; no content or credentials.
        logger.info(
            "phone latency stage=%s call_id=%s session_id=%s turn=%s "
            "monotonic_ms=%.3f duration_ms=%.3f basis=%s",
            stage,
            call.session.call_id,
            call.session.session_id,
            turn,
            at * 1000,
            duration_ms,
            basis,
        )

    def _record(self, call: _Call, event_type: EventType, **fields: Any) -> None:
        try:
            fields["metadata"] = {
                **call.session.provider_metadata,
                **(fields.get("metadata") or {}),
                "call_id": call.session.call_id,
            }
            self.event_store.append(
                ConversationEvent(
                    session_id=call.session.session_id,
                    channel="phone",
                    event_type=event_type,
                    **fields,
                )
            )
        except Exception:
            logger.warning("Phone event recording failed")

    def start_call(self, event: CallStarted) -> PhoneSession:
        session = self.registry.start(event.call_id, event.metadata)
        if event.call_id not in self._calls:
            call = _Call(session)
            self._calls[event.call_id] = call
            self._record(
                call, "session.started", metadata={"channel_metadata": session.provider_metadata}
            )
        return session

    async def handle_event(self, event: TelephonyEvent) -> None:
        if isinstance(event, CallStarted):
            self.start_call(event)
        elif isinstance(event, IncomingAudio):
            await self.feed_audio(event.call_id, event.audio)
        elif isinstance(event, CallEnded):
            await self.end_call(event.call_id, hangup=False)
        elif isinstance(event, ProviderError):
            await self._fail_call(event.call_id, "provider_error")
        else:
            raise ValueError("Unknown telephony event")

    async def feed_audio(
        self, call_id: str, audio: ProviderAudio, *, wait_for_capacity: bool = False
    ) -> bool:
        call = self._calls.get(call_id)
        if call is None or call.session.status not in ("active", "transcribing"):
            # Half duplex: discard caller/echo frames while Agent, TTS or playback is busy.
            return False
        try:
            pcm = self.normalizer.normalize(audio)
            if call.capture is None or not call.capture.accepting:
                call.capture = _Capture()
                call.session.status = "transcribing"
                task = asyncio.create_task(self._capture(call, call.capture))
                call.capture_tasks.add(task)
                task.add_done_callback(call.capture_tasks.discard)
            capture = call.capture
            if wait_for_capacity:
                # Vonage opts in: its 20ms packets arrive during VAD/upstream startup.
                # Keep the existing bounded queue and let the socket apply backpressure.
                if capture.queue.full() and not capture.backpressure_logged:
                    capture.backpressure_logged = True
                    logger.info(
                        "phone audio_backpressure call_id=%s queued_frames=%s "
                        "message=waiting_for_stt_capacity",
                        call_id,
                        capture.queue.qsize(),
                    )
                async with asyncio.timeout(AUDIO_QUEUE_WAIT_SECONDS):
                    while capture.queue.full():
                        if not self._current(call) or not capture.accepting:
                            return False
                        await asyncio.sleep(0.01)
                if (
                    not self._current(call)
                    or call.capture is not capture
                    or not capture.accepting
                    or call.session.status not in ("active", "transcribing")
                ):
                    return False
            capture.queue.put_nowait(StreamInput("audio", pcm))
            return True
        except Exception as error:
            if call.session.provider_metadata.get("provider") == "vonage":
                logger.warning(
                    "phone audio_input_failed call_id=%s exception_type=%s "
                    "message=audio_admission_failed",
                    call_id,
                    type(error).__name__,
                )
            await self._fail_call(call_id, "audio_input_failed")
            return False

    async def finish_utterance(self, call_id: str) -> None:
        """Optional manual endpoint for a provider/bench; Silero normally commits audio."""
        call = self._calls.get(call_id)
        if call is None or call.capture is None or not call.capture.accepting:
            return
        try:
            call.capture.queue.put_nowait(StreamInput("finish"))
        except asyncio.QueueFull:
            await self._fail_call(call_id, "audio_input_failed")

    async def _capture(self, call: _Call, capture: _Capture) -> None:
        vonage = call.session.provider_metadata.get("provider") == "vonage"
        activity_logged = False

        async def emit(event: dict[str, Any]) -> None:
            nonlocal activity_logged
            if not self._current(call) or call.capture is not capture or not capture.accepting:
                return
            if event.get("type") == "activity" and event.get("silence_ms") == 0:
                capture.speech_end_at = None  # Speech resumed after a short, non-final pause.
            if event.get("type") in ("speech.end", "endpoint.decided"):
                at = event.get("at")
                if isinstance(at, (int, float)) and math.isfinite(at):
                    if event["type"] == "speech.end":
                        capture.speech_end_at = at
                        self._latency(
                            call, "speech_end", call.turn_number + 1, at, basis="last_vad_positive"
                        )
                    else:
                        capture.endpoint_at = at
                        silence_ms = event.get("silence_ms")
                        if isinstance(silence_ms, int) and 0 <= silence_ms <= 150000:
                            logger.info(
                                "phone endpointing_decision call_id=%s turn=%s silence_ms=%s",
                                call.session.call_id,
                                call.turn_number + 1,
                                silence_ms,
                            )
                        elapsed = (
                            (at - capture.speech_end_at) * 1000
                            if (capture.speech_end_at is not None)
                            else 0
                        )
                        self._latency(
                            call,
                            "endpointing_decision",
                            call.turn_number + 1,
                            at,
                            elapsed,
                            "speech_end" if elapsed else "unavailable",
                        )
                return
            if vonage and event.get("type") == "activity" and not activity_logged:
                activity_logged = True
                logger.info("phone stt_activity call_id=%s", call.session.call_id)
            if event.get("type") in ("utterance.final", "empty"):
                capture.accepting = False
            if event.get("type") == "utterance.final":
                if isinstance(event.get("text"), str) and len(event["text"].strip()) > 10000:
                    raise ValueError("STT final exceeds Agent input limit")
                # Release the STT relay after final admission; Agent/TTS are a separate task.
                await self.handle_transcript(call.session.call_id, event, wait_for_completion=False)
            elif event.get("type") == "error":
                raise RuntimeError("Streaming STT failed")

        try:
            if vonage:
                logger.info("phone stt_stream_started call_id=%s", call.session.call_id)
            async with asyncio.timeout(150):
                await self.stt.run(capture.queue.get, emit)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self._current(call) and call.capture is capture:
                if vonage:
                    logger.warning(
                        "phone stt_failed call_id=%s exception_type=%s "
                        "message=streaming_stt_failed",
                        call.session.call_id,
                        type(error).__name__,
                    )
                await self._fail_call(call.session.call_id, "stt_failed")
        finally:
            capture.accepting = False
            if self._current(call) and call.capture is capture:
                call.capture = None
                if call.session.status == "transcribing":
                    call.session.status = "active"

    async def handle_transcript(
        self, call_id: str, event: dict[str, Any], *, wait_for_completion: bool = True
    ) -> bool:
        """Normalized STT boundary, also used by the offline final-transcript bench."""
        call = self._calls.get(call_id)
        if (
            call is None
            or call.session.status not in ("active", "transcribing")
            or event.get("type") != "utterance.final"
        ):
            return False
        text = event.get("text")
        if not isinstance(text, str) or not text.strip():
            return False
        text = text.strip()
        if len(text) > 10000:
            await self._fail_call(call_id, "transcript_invalid")
            return False
        item_id = event.get("item_id")
        if isinstance(item_id, str):
            if item_id in call.final_ids:
                return False
            if len(call.final_ids) >= 1000 or len(item_id) > 128:
                await self._fail_call(call_id, "transcript_invalid")
                return False
            call.final_ids.add(item_id)
        # Admission is synchronous before any await; competing finals are rejected, not queued.
        call.session.status = "processing"
        final_at = perf_counter()
        call.turn_number += 1
        timing = _TurnTiming(
            call.turn_number,
            final_at,
            call.capture.speech_end_at if call.capture else None,
            call.capture.endpoint_at if call.capture else None,
        )
        logger.info("phone stt_final call_id=%s session_id=%s", call_id, call.session.session_id)
        self._latency(
            call,
            "stt_final",
            timing.turn,
            final_at,
            (final_at - timing.endpoint_at) * 1000 if timing.endpoint_at is not None else 0,
            "endpointing_decision" if timing.endpoint_at is not None else "unavailable",
        )
        if call.capture is not None:
            call.capture.accepting = False
        language = event.get("language")
        if language in ("ru", "kk", "mixed"):
            call.session.language = language
        latency = event.get("stt_after_commit_ms")
        self._record(
            call,
            "transcript.final",
            text=text,
            language=language if language in ("ru", "kk", "mixed") else None,
            latency={"stt": latency} if isinstance(latency, (int, float)) else None,
            metadata={"turn": timing.turn},
        )
        task = asyncio.create_task(self._turn(call, text, timing))
        call.turn_task = task

        def clear_turn(done: asyncio.Task) -> None:
            if call.turn_task is done:
                call.turn_task = None

        task.add_done_callback(clear_turn)
        if not wait_for_completion:
            return True
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if self._current(call):
                raise
        return True

    @staticmethod
    def _reply_language(response: AgentResponse, session: PhoneSession) -> SpeechLanguage:
        for context in (response.state, response.routing):
            if isinstance(context, dict) and context.get("response_language") in ("ru", "kk"):
                return context["response_language"]
        # Adapter fallback only; no language classification or business routing.
        return session.language if session.language in ("ru", "kk", "mixed") else "ru"

    async def _turn(self, call: _Call, text: str, timing: _TurnTiming) -> None:
        started = timing.final_at
        try:
            async with asyncio.timeout(self.turn_timeout_seconds):
                agent_started = perf_counter()
                self._latency(
                    call,
                    "agent_start",
                    timing.turn,
                    agent_started,
                    (agent_started - started) * 1000,
                    "stt_final",
                )
                response = await self.agent.respond(call.session.session_id, text)
                agent_done = perf_counter()
                if not self._current(call):
                    return
                self._latency(
                    call,
                    "agent_done",
                    timing.turn,
                    agent_done,
                    (agent_done - agent_started) * 1000,
                    "agent_start",
                )
                logger.info(
                    "phone agent_response call_id=%s session_id=%s status=%s agent_ms=%.1f",
                    call.session.call_id,
                    call.session.session_id,
                    response.conversation_status,
                    (agent_done - agent_started) * 1000,
                )
                call.session.conversation_status = response.conversation_status
                response_event_id = None
                try:
                    for event in response_events(
                        call.session.session_id, "phone", response.model_dump(mode="json")
                    ):
                        self.event_store.append(
                            event.model_copy(
                                update={
                                    "metadata": {
                                        **call.session.provider_metadata,
                                        "call_id": call.session.call_id,
                                        "turn": timing.turn,
                                    }
                                }
                            )
                        )
                        if event.event_type == "agent.response":
                            response_event_id = event.id
                            self.event_store.update_latency(
                                event.id, {"agent_ms": (agent_done - agent_started) * 1000}
                            )
                except Exception:
                    logger.warning("Phone response event recording failed")
                call.session.status = "speaking"
                tts_started = perf_counter()
                self._latency(
                    call,
                    "tts_start",
                    timing.turn,
                    tts_started,
                    (tts_started - agent_done) * 1000,
                    "agent_done",
                )
                speech = await self.tts.synthesize(
                    response.response_text, self._reply_language(response, call.session)
                )
                if not self._current(call):
                    return
                tts_ready = perf_counter()
                if response_event_id:
                    try:
                        self.event_store.update_latency(
                            response_event_id, {"tts_ms": (tts_ready - tts_started) * 1000}
                        )
                    except Exception:
                        logger.warning("Phone latency event recording failed")
                self._latency(
                    call,
                    "tts_ready",
                    timing.turn,
                    tts_ready,
                    (tts_ready - tts_started) * 1000,
                    "tts_start",
                )
                logger.info(
                    "phone tts_ready call_id=%s session_id=%s tts_ms=%.1f",
                    call.session.call_id,
                    call.session.session_id,
                    (tts_ready - tts_started) * 1000,
                )
                playback_started = perf_counter()
                self._latency(
                    call,
                    "playback_start",
                    timing.turn,
                    playback_started,
                    (playback_started - tts_ready) * 1000,
                    "tts_ready",
                )
                await self.provider.send_audio(call.session.call_id, speech)
                playback_complete = perf_counter()
                # Expose already-measured timing values; no new waits or phone behavior.
                if response_event_id:
                    timings = {
                        "agent_ms": (agent_done - agent_started) * 1000,
                        "tts_ms": (tts_ready - tts_started) * 1000,
                        "final_to_playback_complete_ms": (playback_complete - started) * 1000,
                    }
                    if timing.endpoint_at is not None:
                        timings["stt_final_ms"] = (started - timing.endpoint_at) * 1000
                    if timing.speech_end_at is not None:
                        timings["speech_end_to_playback_submit_ms"] = (
                            playback_started - timing.speech_end_at
                        ) * 1000
                        timings["speech_end_to_playback_complete_ms"] = (
                            playback_complete - timing.speech_end_at
                        ) * 1000
                        if timing.endpoint_at is not None:
                            timings["endpointing_ms"] = (
                                timing.endpoint_at - timing.speech_end_at
                            ) * 1000
                    try:
                        self.event_store.update_latency(response_event_id, timings)
                    except Exception:
                        logger.warning("Phone latency event recording failed")
                self._latency(
                    call,
                    "playback_complete",
                    timing.turn,
                    playback_complete,
                    (playback_complete - playback_started) * 1000,
                    "playback_start",
                )
                origin = timing.speech_end_at if timing.speech_end_at is not None else started
                self._latency(
                    call,
                    "total_turn",
                    timing.turn,
                    playback_complete,
                    (playback_complete - origin) * 1000,
                    "speech_end" if timing.speech_end_at is not None else "stt_final",
                )
                logger.info(
                    "phone turn_complete call_id=%s session_id=%s total_ms=%.1f",
                    call.session.call_id,
                    call.session.session_id,
                    (playback_complete - started) * 1000,
                )
                if not self._current(call):
                    return
                if response.conversation_status in ("handoff", "ended"):
                    await self._terminate(call, response.conversation_status, "agent_status", True)
                else:
                    call.session.status = "active"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self._current(call):
                if call.session.provider_metadata.get("provider") == "vonage":
                    logger.warning(
                        "phone turn_failed call_id=%s exception_type=%s message=phone_turn_failed",
                        call.session.call_id,
                        type(error).__name__,
                    )
                await self._fail_call(call.session.call_id, "phone_turn_failed")

    async def _fail_call(self, call_id: str, code: str) -> None:
        if call := self._calls.get(call_id):
            call.session.error_code = code
            await self._terminate(call, "error", code, True)

    async def end_call(self, call_id: str, *, cancel: bool = False, hangup: bool = True) -> None:
        if call := self._calls.get(call_id):
            await self._terminate(
                call, "cancelled" if cancel else "ended", "cancel" if cancel else "call_end", hangup
            )

    async def _terminate(self, call: _Call, status: PhoneStatus, reason: str, hangup: bool) -> None:
        if not self._current(call):
            return
        # Invalidate BEFORE cancelling tasks or awaiting provider cleanup.
        del self._calls[call.session.call_id]
        self.registry.remove(call.session.call_id)
        call.session.status = status
        self._record(
            call,
            "conversation.ended",
            conversation_status=call.session.conversation_status,
            metadata={"reason": reason, "phone_status": status},
        )
        tasks = set(call.capture_tasks)
        if call.turn_task is not None:
            tasks.add(call.turn_task)
        tasks.discard(asyncio.current_task())
        for task in tasks:
            task.cancel()
        try:
            if hangup:
                async with asyncio.timeout(self.cleanup_timeout_seconds):
                    await self.provider.hangup(call.session.call_id)
        except Exception:
            logger.warning("Phone hangup failed")
        finally:
            try:
                async with asyncio.timeout(self.cleanup_timeout_seconds):
                    await self.provider.close(call.session.call_id)
            except Exception:
                logger.warning("Phone provider cleanup failed")
        if tasks:
            # A broken dependency that suppresses cancellation cannot hold the registry open.
            await asyncio.wait(tasks, timeout=self.cleanup_timeout_seconds)

    async def shutdown(self) -> None:
        await asyncio.gather(
            *(self.end_call(call_id, cancel=True) for call_id in tuple(self._calls))
        )
