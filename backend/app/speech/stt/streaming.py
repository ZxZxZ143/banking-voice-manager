"""Transport-neutral one-utterance relay shared by browser and backend phone STT."""

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, Protocol

from app.speech.audio import PCM_BYTES_PER_SECOND, validate_pcm_frame
from app.speech.structured.context import TranscriptionContext
from app.speech.structured.recognition import resolve_recognition


@dataclass(frozen=True)
class StreamInput:
    kind: Literal["audio", "finish", "cancel"]
    audio: bytes | None = None


ReceiveInput = Callable[[], Awaitable[StreamInput]]
EmitEvent = Callable[[dict[str, Any]], Awaitable[None]]


class StreamingSTT(Protocol):
    async def run(self, receive: ReceiveInput, emit: EmitEvent) -> None:
        """One utterance: emits partials/final/empty; cancellation releases resources."""
        ...


async def relay_stream(
    receive: ReceiveInput,
    emit: EmitEvent,
    upstream,
    detector,
    *,
    phone_timing: bool = False,
    context: TranscriptionContext | None = None,
    second_pass=None,
    record_recognition=None,
):
    context = context or TranscriptionContext()
    utterance_audio = bytearray()
    committed_at = None
    transcript_received = False
    ended = asyncio.Event()
    total_bytes = 0
    start = perf_counter()
    last_speech_at = None
    speech_end_reported = False

    async def commit():
        nonlocal committed_at
        if committed_at is not None:
            return
        if not detector.tracker.has_speech:
            await emit({"type": "empty", "message": "Речь не обнаружена."})
            ended.set()
            return
        committed_at = perf_counter()
        if phone_timing:
            await emit(
                {
                    "type": "endpoint.decided",
                    "at": committed_at,
                    "silence_ms": detector.tracker.silence_ms,
                }
            )
        await emit({"type": "committed"})
        await upstream.send(json.dumps({"type": "input_audio_buffer.commit"}))

    async def receive_audio():
        nonlocal total_bytes, last_speech_at, speech_end_reported
        while not ended.is_set():
            message = await receive()
            if message.kind == "cancel":
                ended.set()
                return
            pcm = message.audio if message.kind == "audio" else None
            if pcm is not None:
                if committed_at is not None:
                    continue
                validate_pcm_frame(pcm)
                total_bytes += len(pcm)
                if total_bytes > PCM_BYTES_PER_SECOND * 120:
                    raise ValueError("Audio limit exceeded")
                if context.expected_kind != "none":
                    utterance_audio.extend(pcm)
                await upstream.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(pcm).decode("ascii"),
                        }
                    )
                )
                finished, probability = await asyncio.to_thread(detector.feed, pcm)
                if phone_timing and detector.tracker.has_speech:
                    if detector.tracker.silence_ms == 0:
                        last_speech_at = perf_counter()
                        speech_end_reported = False
                    elif last_speech_at is not None and not speech_end_reported:
                        # Last VAD-positive processing time, not an exact acoustic timestamp.
                        speech_end_reported = True
                        await emit({"type": "speech.end", "at": last_speech_at})
                await emit(
                    {
                        "type": "activity",
                        "speech": probability >= 0.5,
                        "has_speech": detector.tracker.has_speech,
                        "silence_ms": detector.tracker.silence_ms,
                        "audio_ms": round(total_bytes * 1000 / PCM_BYTES_PER_SECOND),
                    }
                )
                if finished:
                    await commit()
                elif not detector.tracker.has_speech and total_bytes >= PCM_BYTES_PER_SECOND * 15:
                    await commit()
            elif message.kind == "finish":
                await commit()
            else:
                raise ValueError("Unknown stream input")

    async def receive_text():
        nonlocal transcript_received
        async for raw in upstream:
            event = json.loads(raw)
            kind = event.get("type", "")
            if kind == "error" or kind.endswith(".failed"):
                raise RuntimeError("Provider error")
            if kind.endswith("input_audio_transcription.delta"):
                await emit(
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
                transcript_received = True
                extra = {}
                if context.expected_kind != "none":
                    first_ms = (perf_counter() - committed_at) * 1000
                    outcome = await resolve_recognition(
                        event["transcript"], bytes(utterance_audio), context, second_pass, first_ms
                    )
                    utterance_audio.clear()
                    extra["recognition"] = outcome.metadata.model_dump()
                    if record_recognition:
                        extra["recognition_id"] = record_recognition(event["transcript"], outcome)
                await emit(
                    {
                        "type": "utterance.final",
                        "text": event["transcript"],
                        "item_id": event.get("item_id"),
                        "language": None,
                        "stt_after_commit_ms": round((perf_counter() - committed_at) * 1000),
                        "endpoint_silence_ms": detector.tracker.silence_ms,
                        "audio_ms": round(total_bytes * 1000 / PCM_BYTES_PER_SECOND),
                        **extra,
                    }
                )
                ended.set()
                return
        if not ended.is_set():
            raise RuntimeError("Provider disconnected")

    async def commit_deadline():
        while not ended.is_set():
            await asyncio.sleep(0.2)
            if (
                committed_at is not None
                and not transcript_received
                and perf_counter() - committed_at > 30
            ):
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
        utterance_audio.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
