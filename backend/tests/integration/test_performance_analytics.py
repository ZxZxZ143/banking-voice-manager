"""Isolated deterministic performance samples; never seed the runtime database or call providers."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.analytics.dashboard import AnalyticsService
from app.analytics.dashboard_models import DashboardQuery
from app.analytics.models import (
    PERFORMANCE_METRICS,
    EventQuery,
    PerformancePayload,
    TurnPayload,
    make_event,
)
from app.analytics.recorder import EventRecorder
from app.analytics.sqlite import SQLiteEventStore
from app.core.config import Settings
from app.main import create_app
from app.speech.tts.base import SpeechResult
from app.telephony.base import CallStarted, PlaybackTiming
from app.telephony.bench import ScriptedPhoneSTT
from app.telephony.providers.mock import MockTelephonyProvider
from app.telephony.runtime import PhoneRuntime, _Capture

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
COMPLETE = dict(zip(PERFORMANCE_METRICS, (1200, 700, 3100, 2000, 6000, 8200), strict=True))


def event(turn=1, *, metrics=None, session="timing", source="runtime", channel="voice", **extra):
    payload = (
        PerformancePayload(**metrics)
        if metrics is not None
        else TurnPayload(assistant_initiated=False)
    )
    return make_event(
        created_at=NOW,
        session_id=session,
        turn_number=turn,
        sequence=8 if metrics is not None else 0,
        channel=channel,
        assistant_id="insurance_manager",
        conversation_status="active",
        event_type=payload.kind,
        payload=payload,
        source=source,
        **extra,
    )


@pytest.fixture
def analytics(tmp_path):
    return AnalyticsService(SQLiteEventStore(tmp_path / "isolated.db"), Settings(_env_file=None))


def metrics(service, **query):
    return service.overview(DashboardQuery(as_of=NOW, **query)).latency


def test_complete_sample_persists_and_survives_restart(analytics):
    store = analytics.store
    store.append(event())
    assert store.append(event(metrics=COMPLETE)) == 1
    assert (
        store.append(event(metrics=COMPLETE)) == 0
    )  # Existing per-source/session/turn idempotency.
    page = store.query_events(EventQuery(event_type="performance_sample"))
    assert page.total == 1
    assert page.events[0].payload.model_dump(exclude={"kind"}) == COMPLETE
    reopened = AnalyticsService(SQLiteEventStore(store.path), analytics.settings)
    for key, expected in COMPLETE.items():
        assert metrics(reopened)[key].model_dump() == {"average_ms": expected, "samples": 1}
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_averages_and_independent_counts_missing_is_not_zero(analytics):
    analytics.store.append_many(
        [
            event(),
            event(metrics=COMPLETE),
            event(2, metrics={"agent_ms": 1000, "tts_ms": 0}),
            event(3, metrics={"agent_ms": None, "endpointing_ms": 1400}),
            event(4),
        ]
    )
    result = metrics(analytics)
    assert result["agent_ms"].average_ms == 2050 and result["agent_ms"].samples == 2
    assert result["tts_ms"].average_ms == 1000 and result["tts_ms"].samples == 2
    assert result["endpointing_ms"].average_ms == 1300 and result["endpointing_ms"].samples == 2
    assert result["stt_final_ms"].average_ms == 700 and result["stt_final_ms"].samples == 1
    assert result["speech_end_to_playback_complete_ms"].samples == 1


def test_old_events_and_text_only_sessions_have_no_fabricated_voice_data(analytics):
    analytics.store.append(event(channel="text"))
    assert all(
        value.average_ms is None and value.samples == 0 for value in metrics(analytics).values()
    )
    # Even a mis-tagged text sample cannot populate voice fields.
    analytics.store.append(event(channel="text", metrics=COMPLETE))
    values = metrics(analytics)
    assert values["agent_ms"].samples == 1
    assert all(values[key].samples == 0 for key in PERFORMANCE_METRICS if key != "agent_ms")


@pytest.mark.parametrize(
    "invalid", [-1, float("nan"), float("inf"), "42", True, {}, [], 600001, 10**1000]
)
def test_invalid_individual_durations_are_unknown(invalid, analytics):
    analytics.store.append_many([event(), event(metrics={"agent_ms": invalid, "tts_ms": 75})])
    result = metrics(analytics)
    assert result["agent_ms"].average_ms is None and result["agent_ms"].samples == 0
    assert result["tts_ms"].average_ms == 75


def test_malformed_stored_duration_does_not_break_analytics(analytics):
    analytics.store.append_many([event(), event(metrics={"agent_ms": 10})])
    with sqlite3.connect(analytics.store.path) as db:
        db.execute(
            "UPDATE events SET payload_json=? WHERE event_type='performance_sample'",
            (
                json.dumps(
                    {
                        "kind": "performance_sample",
                        "agent_ms": -20,
                        "tts_ms": "bad",
                        "stt_final_ms": 35,
                    }
                ),
            ),
        )
    values = metrics(analytics)
    assert values["agent_ms"].samples == values["tts_ms"].samples == 0
    assert values["stt_final_ms"].average_ms == 35


def test_sources_filters_and_business_aggregates_remain_separate(analytics):
    analytics.store.append_many([event(), event(session="demo", source="synthetic_demo")])
    before = analytics.overview(DashboardQuery(as_of=NOW))
    sessions_before = analytics.sessions(DashboardQuery(as_of=NOW)).model_dump()
    anomalies_before = analytics.anomalies(DashboardQuery(as_of=NOW)).model_dump()
    journey_before = analytics.journey("timing", DashboardQuery()).model_dump()
    analytics.store.append_many(
        [
            event(metrics=COMPLETE),
            event(session="demo", source="synthetic_demo", metrics={"agent_ms": 9999}),
        ]
    )
    after = analytics.overview(DashboardQuery(as_of=NOW))
    assert after.risk == before.risk and after.handoff_count == before.handoff_count
    assert after.total_sessions == before.total_sessions
    assert analytics.sessions(DashboardQuery(as_of=NOW)).model_dump() == sessions_before
    assert analytics.anomalies(DashboardQuery(as_of=NOW)).model_dump() == anomalies_before
    assert analytics.journey("timing", DashboardQuery()).model_dump() == journey_before
    assert metrics(analytics)["agent_ms"].average_ms == COMPLETE["agent_ms"]
    assert metrics(analytics, source="runtime")["agent_ms"].samples == 1
    assert metrics(analytics, source="synthetic_demo")["agent_ms"].samples == 0
    assert metrics(analytics, assistant_id="card_promoter")["agent_ms"].samples == 0
    assert metrics(analytics, from_time=NOW + timedelta(seconds=1))["agent_ms"].samples == 0


def test_recorder_is_numeric_only_idempotent_and_failure_safe(analytics):
    recorder = EventRecorder(analytics.store)
    response = SimpleNamespace(
        trace={"turn": 1, "scenario_pack_id": "insurance_manager"}, conversation_status="active"
    )

    async def run():
        await recorder.record_performance(
            "safe-session",
            response,
            {**COMPLETE, "transcript": "PRIVATE", "phone": "+77010000000", "api_key": "PRIVATE"},
            channel="voice",
        )
        await recorder.record_performance("safe-session", response, COMPLETE, channel="voice")

    asyncio.run(run())
    page = analytics.store.query_events(EventQuery(event_type="performance_sample"))
    assert page.total == 1
    payload = page.events[0].payload.model_dump_json()
    assert "PRIVATE" not in payload and "+77010000000" not in payload
    assert set(json.loads(payload)) == {"kind", *PERFORMANCE_METRICS}
    with pytest.raises(ValidationError):
        PerformancePayload(transcript="PRIVATE")
    # Best-effort mapping/storage failure never propagates into a voice turn.
    asyncio.run(
        recorder.record_performance("safe", SimpleNamespace(trace=None), COMPLETE, channel="voice")
    )
    assert recorder.health().failure_count == 1


@pytest.mark.parametrize("tts_fails", [False, True])
def test_phone_runtime_emits_existing_measured_clocks_to_sqlite(analytics, monkeypatch, tts_fails):
    clock = SimpleNamespace(now=10.0)
    monkeypatch.setattr("app.telephony.runtime.perf_counter", lambda: clock.now)
    recorder = EventRecorder(analytics.store)

    class Agent:
        events = recorder

        async def process(self, session_id, text, **options):
            clock.now = 11.3
            return {
                "response_text": "PRIVATE_REPLY",
                "conversation_status": "active",
                "trace": {"turn": 3, "scenario_pack_id": "insurance_manager"},
            }

    class TTS:
        async def synthesize(self, *args):
            if tts_fails:
                raise RuntimeError("fixture failure")
            clock.now = 12.0
            return SpeechResult(audio=b"fixture", content_type="audio/wav", language="ru")

    class Provider(MockTelephonyProvider):
        async def send_audio(self, *args):
            clock.now = 13.7
            return PlaybackTiming(12.2, 13.7)

    async def run():
        runtime = PhoneRuntime(Agent(), ScriptedPhoneSTT(), TTS(), Provider())
        session = runtime.start_call(CallStarted("private-provider-id"))
        analytics.store.append(event(session=session.session_id))
        runtime._calls[session.call_id].capture = _Capture(speech_end_at=8.0, endpoint_at=9.2)
        await runtime.handle_transcript(
            session.call_id,
            {"type": "utterance.final", "item_id": "once", "text": "PRIVATE_TRANSCRIPT"},
        )
        assert not await runtime.handle_transcript(
            session.call_id,
            {"type": "utterance.final", "item_id": "once", "text": "PRIVATE_TRANSCRIPT"},
        )
        await runtime.shutdown()

    asyncio.run(run())
    samples = analytics.store.query_events(EventQuery(event_type="performance_sample"))
    assert samples.total == 1
    sample = samples.events[0]
    assert sample.turn_number == 3 and sample.channel == "voice" and sample.source == "runtime"
    assert (
        "PRIVATE" not in sample.model_dump_json()
        and "private-provider-id" not in sample.model_dump_json()
    )
    values = metrics(analytics)
    expected = {"endpointing_ms": 1200, "stt_final_ms": 800, "agent_ms": 1300}
    if not tts_fails:
        expected.update(
            tts_ms=700,
            speech_end_to_playback_submit_ms=4200,
            speech_end_to_playback_complete_ms=5700,
        )
    for key, value in expected.items():
        assert values[key].average_ms == pytest.approx(value)
        assert values[key].samples == 1
    if tts_fails:
        assert values["tts_ms"].samples == 0
        assert values["speech_end_to_playback_complete_ms"].samples == 0


def test_analytics_endpoint_reads_persisted_partial_sample(analytics):
    analytics.store.append_many([event(), event(metrics={"agent_ms": 500})])
    with TestClient(create_app(Settings(_env_file=None))) as client:
        client.app.state.services.analytics = analytics
        response = client.get("/api/analytics/overview", params={"source": "runtime"})
    assert response.status_code == 200
    latency = response.json()["latency"]
    assert latency["agent_ms"] == {"average_ms": 500, "samples": 1}
    assert latency["endpointing_ms"] == {"average_ms": None, "samples": 0}


@pytest.mark.parametrize("channel", ["text", "voice"])
def test_http_message_persists_measured_agent_only_and_skips_proactive_opening(channel):
    from app.packs.insurance_manager.agent.schemas import RouterDecision

    class Router:
        async def route(self, text, state):
            return RouterDecision(
                language="ru",
                response_language="ru",
                scenarios=[dict(scenario_id="SC33", confidence=0.99, reason="Offline fixture")],
            )

    with TestClient(create_app(Settings(_env_file=None), router_override=Router())) as client:
        opened = client.post(
            "/api/conversation/start",
            json={"session_id": "http", "scenario_mode": "insurance_manager"},
        )
        assert opened.status_code == 200
        assert (
            client.get("/api/analytics/events", params={"event_type": "performance_sample"}).json()[
                "total"
            ]
            == 0
        )
        result = client.post(
            "/api/message",
            json={"session_id": "http", "text": "Справочная информация", "channel": channel},
        )
        assert result.status_code == 200
        events = client.get(
            "/api/analytics/events", params={"event_type": "performance_sample"}
        ).json()
        assert events["total"] == 1
        sample = events["events"][0]
        assert sample["turn_number"] == result.json()["trace"]["turn"]
        assert sample["channel"] == channel
        assert sample["payload"]["agent_ms"] == result.json()["trace"]["latency_ms"]["total"]
        overview = client.get("/api/analytics/overview").json()["latency"]
        assert overview["agent_ms"]["samples"] == 1
        for key in PERFORMANCE_METRICS:
            if key != "agent_ms":
                assert overview[key] == {"average_ms": None, "samples": 0}


@pytest.mark.parametrize("name", ["vonage", "twilio"])
def test_provider_receipt_uses_post_conversion_submission_and_native_ack_clock(monkeypatch, name):
    from importlib import import_module

    module = import_module("app.telephony.providers." + name)
    clock = SimpleNamespace(now=1.0)
    monkeypatch.setattr(module, "perf_counter", lambda: clock.now)

    def convert(speech):
        clock.now = 2.0
        return b"\0" * 640

    monkeypatch.setattr(module, "speech_to_l16" if name == "vonage" else "speech_to_mulaw", convert)
    provider = (
        module.VonageTelephonyProvider() if name == "vonage" else module.TwilioTelephonyProvider()
    )

    class Socket:
        first_media_at = None

        async def send_bytes(self, frame):
            self.first_media_at = self.first_media_at or clock.now

        async def send_json(self, message):
            if message.get("event") == "media":
                self.first_media_at = self.first_media_at or clock.now
            else:
                clock.now = 5.0
                reply = (
                    message["payload"]["reply_id"] if name == "vonage" else message["mark"]["name"]
                )
                provider.acknowledge(stream, reply)

    socket = Socket()
    stream = (
        provider.bind("call", socket)
        if name == "vonage"
        else provider.bind("call", "stream", socket)
    )
    receipt = asyncio.run(
        provider.send_audio(
            "call", SpeechResult(audio=b"fixture", content_type="audio/wav", language="ru")
        )
    )
    assert receipt.submitted_at == socket.first_media_at == 2.0
    assert receipt.completed_at == 5.0
