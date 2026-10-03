"""Deterministic backend phone foundation checks; no live speech/Agent/provider calls."""

import asyncio
import io
import json
import logging
import wave
from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.speech.stt import streaming_provider
from app.speech.stt.endpointing import PauseTracker
from app.speech.stt.streaming_provider import OpenAIStreamingSTT
from app.telephony.audio import PcmPassThroughNormalizer
from app.telephony.base import CallEnded, CallStarted, IncomingAudio, ProviderAudio, ProviderError
from app.telephony.bench import FakePhoneTTS, ScriptedPhoneSTT
from app.telephony.providers.mock import MockTelephonyProvider
from app.telephony.runtime import PhoneRuntime
from app.telephony.sessions import ActiveCallRegistry


class AgentFixture:
    def __init__(self, response=None):
        self.response = response or {
            "response_text": "[MOCK] Ответ",
            "conversation_status": "active",
        }
        self.requests = []

    async def process(self, session_id, text, *, channel="voice"):
        assert channel == "voice"
        self.requests.append((session_id, text))
        return self.response


def make_runtime(agent=None, **options):
    return PhoneRuntime(
        agent or AgentFixture(),
        ScriptedPhoneSTT(),
        FakePhoneTTS(),
        MockTelephonyProvider(),
        cleanup_timeout_seconds=0.01,
        **options,
    )


def final(text="Вопрос", **fields):
    return {"type": "utterance.final", "text": text, **fields}


async def until(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0)


def test_runtime_uses_current_voice_channel_without_a_parallel_event_store():
    runtime = make_runtime()
    assert runtime.start_call(CallStarted("call")).channel == "voice"
    assert not hasattr(runtime, "event_store")


def test_call_identity_capacity_and_replay_protection():
    registry = ActiveCallRegistry(max_active=1, max_calls=2)
    metadata = {"synthetic": True}
    first = registry.start("call-1", metadata)
    metadata["synthetic"] = False
    assert first.channel == "voice"
    assert first.started_at.tzinfo is not None
    assert first.provider_metadata == {"synthetic": True}
    assert registry.start("call-1", {}) is first
    with pytest.raises(ValueError):
        registry.start("call-2", {})
    registry.remove("call-1")
    assert registry.get("call-1") is None
    with pytest.raises(ValueError):
        registry.start("call-1", {})
    second = registry.start("call-2", {})
    assert second.session_id != first.session_id
    registry.remove("call-2")
    with pytest.raises(ValueError):
        registry.start("call-3", {})


@pytest.mark.parametrize(
    "audio",
    [
        ProviderAudio(b"x"),
        ProviderAudio(b""),
        ProviderAudio(bytes(4802)),
        ProviderAudio(bytes(100), encoding="unsupported"),
        ProviderAudio(bytes(100), sample_rate_hz=8000),
        ProviderAudio(bytes(100), channels=2),
    ],
)
def test_normalizer_rejects_unimplemented_formats_and_invalid_frames(audio):
    with pytest.raises(ValueError):
        PcmPassThroughNormalizer().normalize(audio)


def test_normalizer_passes_canonical_pcm_and_fake_tts_is_honest_wav():
    pcm = bytes(4800)
    assert PcmPassThroughNormalizer().normalize(ProviderAudio(pcm)) == pcm

    async def run():
        tts = FakePhoneTTS()
        first = await tts.synthesize("Сәлем", "kk")
        second = await tts.synthesize("Другой текст", "ru")
        assert first.audio == second.audio
        assert first.content_type == "audio/wav"
        with wave.open(io.BytesIO(first.audio), "rb") as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
            assert wav.getnframes() == 2400

    asyncio.run(run())


def test_final_only_two_turns_one_session_tts_and_events():
    async def run():
        runtime = make_runtime()
        session = runtime.start_call(CallStarted("call", {"synthetic": True}))
        assert runtime.start_call(CallStarted("call")) is session
        assert not await runtime.handle_transcript(
            "call", {"type": "transcript.partial", "text": "part"}
        )
        assert not await runtime.handle_transcript("call", final("  "))
        assert runtime.agent.messages.requests == []
        assert await runtime.handle_transcript(
            "call", final("  Первый  ", item_id="1", language="kk")
        )
        assert not await runtime.handle_transcript("call", final("Первый", item_id="1"))
        assert await runtime.handle_transcript("call", final("Второй", item_id="2"))
        assert runtime.agent.messages.requests == [
            (session.session_id, "Первый"),
            (session.session_id, "Второй"),
        ]
        assert len(runtime.provider.outgoing["call"]) == 2
        assert [r.language for r in runtime.tts.requests] == ["kk", "kk"]
        assert session.status == "active"
        await runtime.end_call("call")
        await runtime.end_call("call")
        assert session.status == "ended"
        assert runtime.registry.get("call") is None
        assert "call" in runtime.provider.closed
        assert "call" in runtime.provider.hung_up
        with pytest.raises(ValueError):
            runtime.start_call(CallStarted("call"))

    asyncio.run(run())


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"risk": None, "routing": None, "state": None, "trace": None},
        {"risk": {"signals": []}, "routing": "partial", "trace": {}, "state": []},
        {
            "routing": {
                "response_language": "kk",
                "scenarios": [{"scenario_id": "SC01", "confidence": 0.5}],
            },
            "risk": {"level": "low"},
        },
    ],
)
def test_partial_agent_response_is_preserved(payload):
    async def run():
        response = {"response_text": "Ответ", "conversation_status": "awaiting_user", **payload}
        runtime = make_runtime(AgentFixture(response))
        runtime.start_call(CallStarted("call"))
        await runtime.handle_transcript("call", final())
        event = await runtime.agent.respond("envelope-fixture", "check")
        for key in ("risk", "routing", "state", "trace"):
            assert getattr(event, key) == response.get(key)
        assert runtime.registry.get("call").status == "active"
        if payload.get("routing") and isinstance(payload["routing"], dict):
            assert runtime.provider.outgoing["call"][0].language == "kk"
        await runtime.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize("status", ["handoff", "ended"])
def test_explicit_clarification_and_terminal_response(status):
    async def run():
        response = {
            "response_text": "Ответ",
            "conversation_status": status,
            "trace": {
                "clarification": True,
                "scenarios": [{"scenario_id": "SC01", "confidence": 0.7}],
            },
        }
        runtime = make_runtime(AgentFixture(response))
        session = runtime.start_call(CallStarted("call"))
        await runtime.handle_transcript("call", final())
        assert session.status == status
        assert runtime.registry.get("call") is None
        assert not await runtime.handle_transcript("call", final("late"))
        assert session.conversation_status == status
        assert len(runtime.provider.outgoing["call"]) == 1
        assert "call" in runtime.provider.closed

    asyncio.run(run())


def test_question_and_handoff_flags_do_not_infer_terminal_state():
    async def run():
        runtime = make_runtime(
            AgentFixture(
                {
                    "response_text": "Уточните",
                    "conversation_status": "awaiting_user",
                    "routing": {"clarification_question": "Что уточнить?"},
                    "trace": {"handoff": True},
                }
            )
        )
        runtime.start_call(CallStarted("call"))
        await runtime.handle_transcript("call", final())
        assert runtime.registry.get("call").conversation_status == "awaiting_user"
        assert runtime.registry.get("call").status == "active"
        await runtime.shutdown()

    asyncio.run(run())


def test_overlapping_finals_and_audio_during_processing_or_playback_are_rejected():
    async def run():
        started, release, playback, finish = (asyncio.Event() for _ in range(4))

        class DelayedAgent(AgentFixture):
            async def process(self, session_id, text, *, channel="voice"):
                started.set()
                await release.wait()
                return await super().process(session_id, text, channel=channel)

        class DelayedOutput(MockTelephonyProvider):
            async def send_audio(self, call_id, speech):
                playback.set()
                await finish.wait()
                await super().send_audio(call_id, speech)

        runtime = make_runtime(DelayedAgent())
        runtime.provider = DelayedOutput()
        runtime.start_call(CallStarted("call"))
        turn = asyncio.create_task(runtime.handle_transcript("call", final()))
        await started.wait()
        assert not await runtime.handle_transcript("call", final("overlap"))
        assert not await runtime.feed_audio("call", ProviderAudio(bytes(4800)))
        release.set()
        await playback.wait()
        assert runtime.registry.get("call").status == "speaking"
        assert not await runtime.feed_audio("call", ProviderAudio(bytes(4800)))
        finish.set()
        await turn
        assert len(runtime.agent.messages.requests) == 1
        assert runtime.stt.frames == []
        assert runtime.registry.get("call").status == "active"
        await runtime.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["agent", "tts"])
def test_late_result_after_close_cannot_send_audio_or_reopen_call(stage):
    async def run():
        entered, cancelled, release = (asyncio.Event() for _ in range(3))

        async def stubborn():
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()

        class LateAgent(AgentFixture):
            async def process(self, session_id, text, *, channel="voice"):
                if stage == "agent":
                    await stubborn()
                return await super().process(session_id, text, channel=channel)

        class LateTTS(FakePhoneTTS):
            async def synthesize(self, text, language):
                if stage == "tts":
                    await stubborn()
                return await super().synthesize(text, language)

        runtime = make_runtime(LateAgent())
        runtime.tts = LateTTS()
        session = runtime.start_call(CallStarted("call"))
        task = asyncio.create_task(runtime.handle_transcript("call", final()))
        await entered.wait()
        await runtime.end_call("call", cancel=True)
        assert cancelled.is_set()
        assert session.status == "cancelled"
        assert runtime.registry.get("call") is None
        release.set()
        await task
        assert runtime.provider.outgoing["call"] == []
        assert "call" in runtime.provider.closed
        if stage == "agent":
            assert runtime.tts.requests == []

    asyncio.run(run())


def test_cancelled_caller_does_not_lose_reference_to_inflight_turn():
    async def run():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        class WaitingAgent(AgentFixture):
            async def process(self, session_id, text, *, channel="voice"):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        runtime = make_runtime(WaitingAgent())
        runtime.start_call(CallStarted("call"))
        task = asyncio.create_task(runtime.handle_transcript("call", final()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await runtime.end_call("call")
        assert cancelled.is_set()

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["agent", "tts", "output", "stt", "provider", "audio"])
def test_failure_in_one_call_does_not_break_another(stage, caplog):
    async def run():
        class FailingAgent(AgentFixture):
            async def process(self, session_id, text, *, channel="voice"):
                if text == "fail" and stage == "agent":
                    raise RuntimeError("private Agent details")
                return {"response_text": text, "conversation_status": "active"}

        class FailingTTS(FakePhoneTTS):
            async def synthesize(self, text, language):
                if text == "fail" and stage == "tts":
                    raise RuntimeError("private speech details")
                return await super().synthesize(text, language)

        class FailingOutput(MockTelephonyProvider):
            async def send_audio(self, call_id, speech):
                if call_id == "bad" and stage == "output":
                    raise RuntimeError("private transport details")
                await super().send_audio(call_id, speech)

        class FailingSTT:
            async def run(self, receive, emit):
                raise RuntimeError("private STT details")

        runtime = make_runtime(FailingAgent())
        runtime.tts, runtime.provider = FailingTTS(), FailingOutput()
        bad = runtime.start_call(CallStarted("bad"))
        good = runtime.start_call(CallStarted("good"))
        if stage == "stt":
            runtime.stt = FailingSTT()
            await runtime.feed_audio("bad", ProviderAudio(bytes(4800)))
            await until(lambda: runtime.registry.get("bad") is None)
        elif stage == "provider":
            await runtime.handle_event(ProviderError("bad", "private-provider-data"))
        elif stage == "audio":
            await runtime.feed_audio("bad", ProviderAudio(bytes(4), sample_rate_hz=8000))
        else:
            await runtime.handle_transcript("bad", final("fail"))
        assert bad.status == "error"
        assert runtime.registry.get("bad") is None
        await runtime.handle_transcript("good", final("good"))
        assert good.status == "active"
        assert len(runtime.provider.outgoing["good"]) == 1
        assert "private" not in caplog.text
        await runtime.shutdown()

    asyncio.run(run())


def test_scripted_audio_bench_and_provider_end_cleanup():
    async def run():
        runtime = make_runtime()
        await runtime.handle_event(CallStarted("call"))
        await runtime.handle_event(IncomingAudio("call", ProviderAudio(bytes(4800))))
        await until(lambda: len(runtime.stt.frames) == 1)
        assert runtime.agent.messages.requests == []
        await runtime.finish_utterance("call")
        await until(lambda: len(runtime.provider.outgoing["call"]) == 1)
        await runtime.handle_event(CallEnded("call"))
        assert runtime.registry.get("call") is None
        assert "call" in runtime.provider.closed
        assert "call" not in runtime.provider.hung_up

    asyncio.run(run())


def test_phone_audio_uses_the_same_streaming_relay_as_browser(monkeypatch):
    async def run():
        class Detector:
            def __init__(self):
                from types import SimpleNamespace

                self.tracker = SimpleNamespace(has_speech=True, silence_ms=0)

            def feed(self, pcm):
                return False, 0.9

        class Upstream:
            def __init__(self):
                self.events = asyncio.Queue()
                self.closed = False

            async def send(self, raw):
                kind = json.loads(raw)["type"]
                if kind.endswith("append"):
                    self.events.put_nowait(
                        {"type": "input_audio_transcription.delta", "delta": "part"}
                    )
                if kind.endswith("commit"):
                    self.events.put_nowait(
                        {
                            "type": "input_audio_transcription.completed",
                            "transcript": "Final fixture",
                        }
                    )

            def __aiter__(self):
                return self

            async def __anext__(self):
                return json.dumps(await self.events.get())

        from contextlib import asynccontextmanager

        connections = []

        @asynccontextmanager
        async def connect(url, **kwargs):
            upstream = Upstream()
            connections.append(upstream)
            try:
                yield upstream
            finally:
                upstream.closed = True

        async def recv(self):
            return json.dumps({"type": "session.updated"})

        Upstream.recv = recv
        monkeypatch.setattr(streaming_provider, "connect", connect)
        monkeypatch.setattr(streaming_provider, "SpeechEndDetector", lambda pause: Detector())
        runtime = make_runtime()
        runtime.stt = OpenAIStreamingSTT(api_key="offline-fixture-key")
        session = runtime.start_call(CallStarted("call"))
        await runtime.feed_audio("call", ProviderAudio(bytes(4800)))
        await asyncio.sleep(0)
        assert runtime.agent.messages.requests == []
        await runtime.finish_utterance("call")
        await until(lambda: len(runtime.provider.outgoing["call"]) == 1)
        assert runtime.agent.messages.requests == [(session.session_id, "Final fixture")]
        await until(lambda: connections[0].closed)
        await runtime.feed_audio("call", ProviderAudio(bytes(4800)))
        await runtime.finish_utterance("call")
        await until(lambda: len(runtime.provider.outgoing["call"]) == 2)
        assert runtime.agent.messages.requests == [(session.session_id, "Final fixture")] * 2
        await runtime.shutdown()
        assert len(connections) == 2
        assert all(connection.closed for connection in connections)

    asyncio.run(run())


@pytest.mark.parametrize("value", [799, 5001])
def test_phone_silence_cannot_be_below_800_or_above_bound(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, phone_endpoint_silence_ms=value)


def test_short_phone_endpoint_once_after_continuation_with_latency_stages(monkeypatch, caplog):
    async def run():
        detectors, upstreams = [], []

        class Detector:
            def __init__(self, pause_ms):
                self.tracker = PauseTracker(pause_ms)
                self.processed = 0
                detectors.append(self)

            def feed(self, pcm):
                speech = pcm[0] == 1  # Explicit fixture classification; real PauseTracker.
                ended = self.tracker.step(speech)
                self.processed += 1
                return ended, 0.9 if speech else 0.0

        class Upstream:
            def __init__(self):
                self.events = asyncio.Queue()
                self.commits = 0
                upstreams.append(self)

            async def send(self, raw):
                if json.loads(raw)["type"] == "input_audio_buffer.commit":
                    self.commits += 1
                    for _ in range(2):  # A repeated provider completion must not route twice.
                        self.events.put_nowait(
                            {
                                "type": "input_audio_transcription.completed",
                                "transcript": "PRIVATE_FIXTURE_TRANSCRIPT",
                                "item_id": "same-final",
                            }
                        )

            async def recv(self):
                return json.dumps({"type": "session.updated"})

            def __aiter__(self):
                return self

            async def __anext__(self):
                return json.dumps(await self.events.get())

        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield Upstream()

        monkeypatch.setattr(streaming_provider, "connect", connect)
        monkeypatch.setattr(streaming_provider, "SpeechEndDetector", Detector)
        settings = Settings(_env_file=None)
        assert settings.phone_endpoint_silence_ms == 1200
        runtime = make_runtime()
        runtime.stt = OpenAIStreamingSTT(
            api_key="PRIVATE_FIXTURE_KEY", pause_ms=settings.phone_endpoint_silence_ms
        )
        session = runtime.start_call(CallStarted("call"))
        count = 0

        async def feed(speech, frames):
            nonlocal count
            for _ in range(frames):
                count += 1
                await runtime.feed_audio("call", ProviderAudio(bytes([int(speech), 0]) * 768))
                await until(lambda: bool(detectors) and detectors[0].processed == count)

        await feed(True, 3)
        await feed(False, 37)  # 1184ms < 1200ms: no premature final/Agent turn.
        assert runtime.agent.messages.requests == [] and upstreams[0].commits == 0
        await feed(True, 3)  # Continuation resets the silence timer.
        await feed(False, 37)
        assert runtime.agent.messages.requests == [] and upstreams[0].commits == 0
        await feed(False, 1)  # 1216ms, matching the existing VAD's 32ms resolution.
        await until(lambda: len(runtime.provider.outgoing.get("call", [])) == 1)
        await until(lambda: session.status == "active")
        assert upstreams[0].commits == 1 and detectors[0].tracker.pause_ms == 1200
        assert runtime.agent.messages.requests == [
            (session.session_id, "PRIVATE_FIXTURE_TRANSCRIPT")
        ]
        assert not await runtime.handle_transcript("call", final(item_id="same-final"))
        assert runtime._calls["call"].turn_number == 1
        await runtime.shutdown()

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    stages = [
        dict(piece.split("=", 1) for piece in record.message.split() if "=" in piece)
        for record in caplog.records
        if "phone latency stage=" in record.message
    ]
    by_stage = {stage["stage"]: stage for stage in stages}
    ordered = [
        "endpointing_decision",
        "stt_final",
        "agent_start",
        "agent_done",
        "tts_start",
        "tts_ready",
        "playback_start",
        "playback_complete",
        "total_turn",
    ]
    assert [stage["stage"] for stage in stages if stage["stage"] != "speech_end"] == ordered
    assert "speech_end" in by_stage and by_stage["total_turn"]["basis"] == "speech_end"
    assert all(float(stage["duration_ms"]) >= 0 for stage in stages)
    for end, start in [
        ("agent_done", "agent_start"),
        ("tts_ready", "tts_start"),
        ("playback_complete", "playback_start"),
        ("total_turn", "speech_end"),
    ]:
        elapsed = float(by_stage[end]["monotonic_ms"]) - float(by_stage[start]["monotonic_ms"])
        assert float(by_stage[end]["duration_ms"]) == pytest.approx(elapsed, abs=0.003)
    assert "silence_ms=1216" in caplog.text
    assert (
        "PRIVATE_FIXTURE_TRANSCRIPT" not in caplog.text and "PRIVATE_FIXTURE_KEY" not in caplog.text
    )


def test_cleanup_failure_does_not_break_call_flow():
    async def run():
        class BrokenCleanup(MockTelephonyProvider):
            async def hangup(self, call_id):
                raise RuntimeError("hangup failed")

        runtime = make_runtime()
        runtime.provider = BrokenCleanup()
        runtime.start_call(CallStarted("call"))
        await runtime.handle_transcript("call", final())
        assert len(runtime.provider.outgoing["call"]) == 1
        await runtime.end_call("call")
        assert "call" in runtime.provider.closed
        assert runtime.registry.get("call") is None

    asyncio.run(run())


def test_turn_timeout_closes_call_and_cleans_up():
    async def run():
        class HangingAgent(AgentFixture):
            async def process(self, session_id, text, *, channel="voice"):
                await asyncio.Event().wait()

        runtime = make_runtime(HangingAgent(), turn_timeout_seconds=0.01)
        session = runtime.start_call(CallStarted("call"))
        await runtime.handle_transcript("call", final())
        assert session.status == "error"
        assert session.error_code == "phone_turn_failed"
        assert runtime.registry.get("call") is None
        assert "call" in runtime.provider.closed

    asyncio.run(run())


def test_stt_releases_after_final_without_waiting_for_agent_or_tts():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class WaitingAgent(AgentFixture):
            async def process(self, session_id, text, *, channel="voice"):
                entered.set()
                await release.wait()
                return await super().process(session_id, text, channel=channel)

        runtime = make_runtime(WaitingAgent())
        runtime.start_call(CallStarted("call"))
        await runtime.feed_audio("call", ProviderAudio(bytes(4800)))
        await runtime.finish_utterance("call")
        await entered.wait()
        await until(lambda: not runtime._calls["call"].capture_tasks)
        assert runtime.registry.get("call").status == "processing"
        release.set()
        await until(lambda: runtime.registry.get("call").status == "active")
        await runtime.shutdown()

    asyncio.run(run())


def test_bounded_audio_queue_overflow_closes_only_its_call():
    async def run():
        runtime = make_runtime()
        session = runtime.start_call(CallStarted("call"))
        for _ in range(16):
            assert await runtime.feed_audio("call", ProviderAudio(bytes(4800)))
        assert not await runtime.feed_audio("call", ProviderAudio(bytes(4800)))
        assert session.status == "error"
        assert session.error_code == "audio_input_failed"
        assert "call" in runtime.provider.closed
        assert runtime.registry.get("call") is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "response",
    [
        {"response_text": " ", "conversation_status": "active"},
        {"response_text": "Reply"},
        {"response_text": "Reply", "conversation_status": "invalid"},
        {"response_text": "Reply", "conversation_status": "active", "session_id": "different"},
    ],
)
def test_invalid_agent_envelope_is_not_replaced_by_mock(response):
    async def run():
        runtime = make_runtime(AgentFixture(response))
        session = runtime.start_call(CallStarted("call"))
        await runtime.handle_transcript("call", final())
        assert session.status == "error"
        assert runtime.tts.requests == []
        assert runtime.provider.outgoing["call"] == []

    asyncio.run(run())


def test_empty_stt_does_not_create_an_agent_turn():
    async def run():
        class EmptySTT:
            async def run(self, receive, emit):
                await emit({"type": "empty"})

        runtime = make_runtime()
        runtime.stt = EmptySTT()
        session = runtime.start_call(CallStarted("call"))
        await runtime.feed_audio("call", ProviderAudio(bytes(4800)))
        await until(lambda: session.status == "active")
        assert runtime.agent.messages.requests == []
        assert runtime.tts.requests == []
        await runtime.shutdown()

    asyncio.run(run())


def test_risk_guidance_speaks_current_reply_language_without_changing_business_state():
    async def run():
        runtime = make_runtime(
            AgentFixture(
                {
                    "response_text": "[MOCK] Қауіпсіздік кеңесі",
                    "conversation_status": "active",
                    "state": {"response_language": "ru"},
                    "routing": {"kind": "security_guidance", "response_language": "kk"},
                }
            )
        )
        runtime.start_call(CallStarted("risk-language"))
        await runtime.handle_transcript("risk-language", final())
        assert runtime.tts.requests[0].language == "kk"
        assert runtime.agent.messages.response["state"]["response_language"] == "ru"
        await runtime.shutdown()

    asyncio.run(run())
