"""Transport-neutral one-utterance relay shared by browser and backend phone STT."""

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, Protocol

from app.speech.audio import PCM_BYTES_PER_SECOND, validate_pcm_frame
from app.speech.structured.capture import recognize_context
from app.speech.structured.context import TranscriptionContext
from app.speech.structured.policy import RecognitionHypothesis, StructuredRecognitionPolicy
from app.speech.structured.recognition import (
    bounded_hypothesis,
    pending_readback,
    resolve_recognition,
)


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
    adaptive_endpoint=None,
):
    context = context or TranscriptionContext()
    utterance_audio = bytearray()
    committed_at = None
    second_task = None
    second_watcher = None
    first_hypothesis = None
    first_final_ms = None
    final_sent = False
    race = context.capture_part == "whole" and StructuredRecognitionPolicy.requires_consensus(
        context.expected_kind
    )
    transcript_received = False
    ended = asyncio.Event()
    total_bytes = 0
    start = perf_counter()
    last_speech_at = None
    speech_end_reported = False
    speech_start_reported = False
    partial_text = ""

    async def commit():
        nonlocal committed_at, second_task, second_watcher
        if committed_at is not None:
            return
        if not detector.tracker.has_speech:
            await emit({"type": "empty", "message": "Речь не обнаружена."})
            ended.set()
            return
        committed_at = perf_counter()
        if (
            StructuredRecognitionPolicy.requires_consensus(context.expected_kind)
            and utterance_audio
            and second_pass
        ):
            second_task = asyncio.create_task(
                bounded_hypothesis(bytes(utterance_audio), context, second_pass)
            )
            if race:
                second_watcher = asyncio.create_task(watch_bounded())
        if phone_timing:
            await emit(
                {
                    "type": "endpoint.decided",
                    "at": committed_at,
                    "silence_ms": detector.tracker.silence_ms,
                }
            )
        await emit(
            {
                "type": "committed",
                **({"silence_ms": detector.tracker.silence_ms} if adaptive_endpoint else {}),
            }
        )
        await upstream.send(json.dumps({"type": "input_audio_buffer.commit"}))

    async def publish(text, outcome=None, item_id=None):
        nonlocal final_sent
        if final_sent or ended.is_set():
            return
        final_sent = True
        extra = {}
        bounded = second_task.result() if second_task and second_task.done() else None
        extra["timing"] = {
            "realtime_final_ms": first_final_ms,
            "bounded_final_ms": bounded.elapsed_ms if bounded else None,
        }
        if outcome is not None:
            extra["recognition"] = outcome.metadata.model_dump()
            if record_recognition:
                extra["recognition_id"] = record_recognition(text, outcome)
        utterance_audio.clear()
        await emit(
            {
                "type": "utterance.final",
                "text": text,
                "item_id": item_id,
                "language": None,
                "stt_after_commit_ms": round((perf_counter() - committed_at) * 1000),
                "endpoint_silence_ms": detector.tracker.silence_ms,
                "audio_ms": round(total_bytes * 1000 / PCM_BYTES_PER_SECOND),
                **extra,
            }
        )
        ended.set()

    async def watch_bounded():
        result = await second_task
        if result.hypothesis.valid_schema and not ended.is_set():
            await publish(
                result.text,
                pending_readback(
                    result.hypothesis,
                    elapsed_ms=(perf_counter() - committed_at) * 1000,
                    first=first_hypothesis,
                    first_final_ms=first_final_ms,
                    second=result,
                    second_used=True,
                ),
            )

    async def receive_audio():
        nonlocal total_bytes, last_speech_at, speech_end_reported, speech_start_reported
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
                if adaptive_endpoint:
                    detector.tracker.pause_ms = adaptive_endpoint.pause_ms
                finished, probability = await asyncio.to_thread(detector.feed, pcm)
                if adaptive_endpoint and detector.tracker.has_speech and not speech_start_reported:
                    speech_start_reported = True
                    await emit({"type": "speech.started"})
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
        nonlocal transcript_received, first_hypothesis, partial_text, first_final_ms
        async for raw in upstream:
            event = json.loads(raw)
            kind = event.get("type", "")
            if kind == "error" or kind.endswith(".failed"):
                if race and second_task:
                    result = await second_task
                    if result.hypothesis.valid_schema:
                        await second_watcher
                        return
                raise RuntimeError("Provider error")
            if kind.endswith("input_audio_transcription.delta"):
                partial_text = (partial_text + event.get("delta", ""))[:10000]
                if adaptive_endpoint:
                    adaptive_endpoint.observe(partial_text)
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
                first_final_ms = (perf_counter() - committed_at) * 1000
                outcome = None
                if context.expected_kind != "none":
                    first_ms = (perf_counter() - committed_at) * 1000
                    first_hypothesis = RecognitionHypothesis.from_normalized(
                        "realtime", recognize_context(event["transcript"], context)
                    )
                    if race and first_hypothesis.valid_schema:
                        second = (
                            second_task.result() if second_task and second_task.done() else None
                        )
                        outcome = pending_readback(
                            first_hypothesis,
                            elapsed_ms=first_ms,
                            first=first_hypothesis,
                            first_final_ms=first_final_ms,
                            second=second,
                            second_used=second_task is not None,
                        )
                    else:
                        outcome = await resolve_recognition(
                            event["transcript"],
                            bytes(utterance_audio),
                            context,
                            second_pass,
                            first_ms,
                            second_task=second_task,
                        )
                        if race and second_watcher:
                            await second_watcher
                await publish(event["transcript"], outcome, event.get("item_id"))
                return
        if not ended.is_set():
            if race and second_task:
                result = await second_task
                if result.hypothesis.valid_schema:
                    await second_watcher
                    return
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
        if second_task is not None:
            tasks.append(second_task)
        if second_watcher is not None:
            tasks.append(second_watcher)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
