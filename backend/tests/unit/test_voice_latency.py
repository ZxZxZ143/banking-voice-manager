import asyncio
import json
from types import SimpleNamespace

import pytest

from app.speech.structured.context import context_for_slot
from app.speech.stt.adaptive_endpoint import AdaptiveEndpoint
from app.speech.stt.streaming import StreamInput, relay_stream


@pytest.mark.parametrize(
    "winner,first,second",
    [
        ("realtime", "123ABC02", "123ABD02"),
        ("bounded", "123ABC02", "123ABD02"),
        ("bounded", "непонятно", "123ABD02"),
        ("realtime", "123ABC02", "непонятно"),
    ],
)
def test_first_unique_candidate_starts_readback_and_cancels_loser(winner, first, second):
    async def run():
        audio, wire = asyncio.Queue(), asyncio.Queue()
        audio.put_nowait(StreamInput("audio", bytes(4800)))
        audio.put_nowait(StreamInput("finish"))
        committed, loser_cancelled = asyncio.Event(), asyncio.Event()
        emitted, receipts = [], []

        class Provider:
            async def transcribe(self, pcm, context):
                await committed.wait()
                if winner == "realtime":
                    if second == "непонятно":
                        return second
                    try:
                        await asyncio.Future()
                    finally:
                        loser_cancelled.set()
                if first == "непонятно":
                    await asyncio.sleep(0.01)
                return second

        class Upstream:
            async def send(self, raw):
                if json.loads(raw)["type"].endswith("commit"):
                    committed.set()
                    if winner == "realtime" or first == "непонятно":
                        wire.put_nowait(
                            json.dumps(
                                {"type": "input_audio_transcription.completed", "transcript": first}
                            )
                        )

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return await wire.get()
                except asyncio.CancelledError:
                    loser_cancelled.set()
                    raise

        class Detector:
            tracker = SimpleNamespace(has_speech=True, silence_ms=1100)

            def feed(self, pcm):
                return False, 0.9

        async def emit(event):
            emitted.append(event)

        def record(text, result):
            receipts.append((text, result))
            return "private-receipt"

        await asyncio.wait_for(
            relay_stream(
                audio.get,
                emit,
                Upstream(),
                Detector(),
                context=context_for_slot("vehicle_plate"),
                second_pass=Provider(),
                record_recognition=record,
            ),
            1,
        )
        assert len(receipts) == 1
        text, result = receipts[0]
        assert text == (first if winner == "realtime" else second)
        assert result.candidate.canonical_candidate == text
        assert result.metadata.readback_source == winner
        assert result.metadata.outcome == "confirmation_required"
        assert not result.metadata.accepted and result.accepted_value is None
        assert result.metadata.candidate_ready_ms < 500
        assert len([event for event in emitted if event["type"] == "utterance.final"]) == 1
        if first != "непонятно" and second != "непонятно":
            assert loser_cancelled.is_set()

    asyncio.run(run())


@pytest.mark.parametrize(
    "slot,partial,base,fast",
    [
        ("phone", "87775232862", 1300, 1100),
        ("region", "ноль два", 900, 750),
        (None, "Здравствуйте", 1600, 1600),
    ],
)
def test_endpoint_requires_unchanged_partial_and_bounded_stability(slot, partial, base, fast):
    time = [0.0]
    endpoint = AdaptiveEndpoint(context_for_slot(slot), clock=lambda: time[0])
    endpoint.observe(partial)
    assert endpoint.pause_ms == base
    time[0] = 0.3
    assert endpoint.pause_ms == base
    time[0] = 0.5
    assert endpoint.pause_ms == fast
    endpoint.observe(partial + " еще цифры")
    assert endpoint.pause_ms == base


@pytest.mark.parametrize(
    "text,pause",
    [("да", 650), ("иә", 650), ("нет", 650), ("Последняя цифра три", 800), ("Вторая буква B", 800)],
)
def test_confirmation_and_correction_have_short_guarded_profiles(text, pause):
    time = [0.0]
    endpoint = AdaptiveEndpoint(
        context_for_slot(None).model_copy(update={"confirmation_kind": "vehicle_plate"}),
        clock=lambda: time[0],
    )
    endpoint.observe(text)
    assert endpoint.pause_ms == (900 if pause == 800 else 750)
    time[0] = 0.5
    assert endpoint.pause_ms == pause
