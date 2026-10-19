"""Offline behavior checks: packaged fixtures, lifecycle, rolling dates and owned repair."""

import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.analytics import demo
from app.analytics.demo import DemoDataLoader, DemoDataset, load_demo_dataset
from app.analytics.models import EventQuery, make_event
from app.analytics.sqlite import SQLiteEventStore
from app.core.config import Settings
from app.main import create_app

NOW = datetime(2030, 3, 10, 18, 1, tzinfo=UTC)


def app_at(path, monkeypatch, *, enabled=True, now=NOW):
    monkeypatch.setattr(demo, "utc_now", lambda: now)
    return create_app(
        Settings(_env_file=None, event_db_path=path, analytics_demo_data_enabled=enabled)
    )


def stored(path, table="events"):
    assert table in {"events", "demo_datasets", "demo_dataset_events"}
    with sqlite3.connect(path) as db:
        return db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def unrelated(source="runtime"):
    values = load_demo_dataset().fixture.core[0].model_dump(exclude={"event_id"})
    values.update(
        session_id=f"unrelated-{source}", source=source, created_at=NOW - timedelta(days=9)
    )
    return make_event(**values)


def updated_dataset():
    original = load_demo_dataset()
    fixture = original.fixture.model_copy(deep=True)
    fixture.version = "2"
    fixture.core = fixture.core[1:]  # A version may retire owned rows as well as add them.
    fixture.core[0].created_at += timedelta(seconds=1)
    return DemoDataset(fixture, "new-version-test-fingerprint")


def test_packaged_fixture_preserves_existing_core_and_anomaly_data():
    dataset = load_demo_dataset()
    assert dataset.fixture.version == "1"
    assert len(dataset.fixture.core) == 640
    assert len({e.session_id for e in dataset.fixture.core}) == 120
    assert len(dataset.fixture.anomalies) == 48
    assert len({e.session_id for e in dataset.fixture.anomalies}) == 24
    assert {e.created_at.date().isoformat() for e in dataset.fixture.core} == {"2026-10-03"}
    assert {e.source for e in dataset.events_at(NOW)} == {"synthetic_demo"}
    assert all(e.event_type != "performance_sample" for e in dataset.events_at(NOW))


def test_startup_api_sessions_journey_filters_and_anomalies(tmp_path, monkeypatch):
    app = app_at(tmp_path / "fresh.db", monkeypatch)
    with TestClient(app) as client:
        services = app.state.services
        assert services.demo_data.store is services.events.store is services.analytics.store
        health = client.get("/health").json()["analytics_demo"]
        assert health == {
            "enabled": True,
            "version": "1",
            "time_policy": "rolling_5m",
            "refresh_seconds": 300,
        }
        params = {"as_of": NOW.isoformat(), "source": "synthetic_demo"}
        overview = client.get("/api/analytics/overview", params=params).json()
        assert overview["total_sessions"] == 144
        assert overview["retained_events"] == 688
        assert overview["latency"]["agent_ms"] == {"average_ms": None, "samples": 0}
        assert (
            client.get("/api/analytics/sessions", params={**params, "active": True}).json()["total"]
            == 0
        )
        assert (
            client.get("/api/analytics/events", params={"source": "runtime"}).json()["total"] == 0
        )
        params.update({"from": (NOW - timedelta(hours=11)).isoformat(), "to": NOW.isoformat()})
        first = client.get("/api/analytics/sessions", params={**params, "limit": 7}).json()
        second = client.get(
            "/api/analytics/sessions", params={**params, "limit": 7, "offset": 7}
        ).json()
        assert first["total"] == second["total"] == 144
        assert {s["session_id"] for s in first["sessions"]}.isdisjoint(
            s["session_id"] for s in second["sessions"]
        )
        identity = "synthetic-demo-v1-002"
        detail = client.get(f"/api/analytics/sessions/{identity}/detail", params=params).json()
        journey = client.get(f"/api/analytics/sessions/{identity}/journey", params=params).json()
        assert detail["summary"]["completed"] and not detail["summary"]["active"]
        assert [s["id"] for s in journey["stages"]] == [
            e["event_id"] for e in detail["timeline"] if e["event_type"] != "conversation_turn"
        ]
        anomalies = client.get(
            "/api/analytics/anomalies",
            params={"as_of": NOW.isoformat(), "source": "synthetic_demo"},
        ).json()
        assert anomalies["anomalies"]
        assert (
            client.get("/api/analytics/anomalies", params={"source": "runtime"}).json()["anomalies"]
            == []
        )


def test_restart_and_recreated_ephemeral_db_without_cli(tmp_path, monkeypatch):
    path = tmp_path / "original.db"
    for _ in range(2):
        with TestClient(app_at(path, monkeypatch)) as client:
            assert client.get("/api/analytics/events").json()["total"] == 688
        if _ == 0:
            original = stored(path)
        else:
            assert stored(path) == original
    # An unrelated empty path models a completely recreated container filesystem.
    replacement = tmp_path / "replacement.db"
    with TestClient(app_at(replacement, monkeypatch)) as client:
        assert client.get("/api/analytics/events").json()["total"] == 688
    assert stored(replacement) == original


def test_runtime_only_database_migrates_and_version_replaces_only_owned_rows(tmp_path):
    path = tmp_path / "existing.db"
    store = SQLiteEventStore(path)
    store.append_many([unrelated(), unrelated("synthetic_demo")])
    original = stored(path)
    with sqlite3.connect(path) as db:
        db.executescript(
            "DROP TABLE demo_datasets; DROP TABLE demo_dataset_events; PRAGMA user_version=1;"
        )
    store = SQLiteEventStore(path)
    assert DemoDataLoader(store, clock=lambda: NOW).ensure_current()
    assert not DemoDataLoader(store, clock=lambda: NOW).ensure_current()
    assert DemoDataLoader(store, dataset=updated_dataset(), clock=lambda: NOW).ensure_current()
    assert len(stored(path)) == 689  # 687 v2 rows + 2 unrelated rows.
    for row in original:
        assert row in stored(path)
    assert stored(path, "demo_datasets")[0][1] == "2"
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


@pytest.mark.parametrize("damage", ["event", "membership", "marker", "timestamp"])
def test_partial_dataset_is_repaired_even_with_current_version(tmp_path, damage):
    path = tmp_path / "partial.db"
    store = SQLiteEventStore(path)
    DemoDataLoader(store, clock=lambda: NOW).ensure_current()
    expected = [stored(path, table) for table in ("events", "demo_datasets", "demo_dataset_events")]
    with sqlite3.connect(path) as db:
        event_id = str(load_demo_dataset().fixture.core[0].event_id)
        if damage == "event":
            db.execute("DELETE FROM events WHERE event_id=?", (event_id,))
        elif damage == "membership":
            db.execute("DELETE FROM demo_dataset_events WHERE event_id=?", (event_id,))
        elif damage == "marker":
            db.execute("DELETE FROM demo_datasets")
        else:
            db.execute(
                "UPDATE events SET created_at='2000-01-01T00:00:00Z' WHERE event_id=?", (event_id,)
            )
    assert DemoDataLoader(store, clock=lambda: NOW).ensure_current()
    assert [
        stored(path, table) for table in ("events", "demo_datasets", "demo_dataset_events")
    ] == expected


def test_legacy_exact_seed_is_adopted_without_duplicate_ids(tmp_path):
    store = SQLiteEventStore(tmp_path / "legacy.db")
    store.append_many(demo.synthetic_events())
    DemoDataLoader(store, clock=lambda: NOW).ensure_current()
    assert store.query_events(EventQuery()).total == 688
    assert len(stored(store.path, "demo_dataset_events")) == 688


def test_long_lived_process_refreshes_before_read_without_growth(tmp_path, monkeypatch):
    path = tmp_path / "rolling.db"
    with TestClient(app_at(path, monkeypatch)) as client:
        loader = client.app.state.services.demo_data
        runtime = unrelated()
        loader.store.append(runtime)
        original = loader.store.get_event(runtime.event_id).model_dump()
        identities = {row[0] for row in stored(path)}
        for delta in (timedelta(minutes=2), timedelta(days=2), timedelta(days=400)):
            now = NOW + delta
            loader.clock = lambda: now
            params = {
                "as_of": now.isoformat(),
                "from": (now - timedelta(hours=11)).isoformat(),
                "to": now.isoformat(),
                "source": "synthetic_demo",
            }
            assert client.get("/api/analytics/sessions", params=params).json()["total"] == 144
            assert client.get(
                "/api/analytics/anomalies",
                params={"as_of": now.isoformat(), "source": "synthetic_demo"},
            ).json()["anomalies"]
            assert {row[0] for row in stored(path)} == identities
            assert loader.store.get_event(runtime.event_id).model_dump() == original
            assert not loader.ensure_current()

        # Actual polling cannot trigger even a database install/check inside the bucket.
        def forbidden(*args):
            pytest.fail("polling must not reinstall the dataset")

        monkeypatch.setattr(loader.store, "install_demo_dataset", forbidden)
        for _ in range(3):
            assert client.get("/api/analytics/overview", params=params).status_code == 200


def test_parallel_initializers_converge(tmp_path):
    path = tmp_path / "parallel.db"
    SQLiteEventStore(path).initialize()

    def install(_):
        return DemoDataLoader(SQLiteEventStore(path, timeout=5), clock=lambda: NOW).ensure_current()

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sum(pool.map(install, range(3))) == 1
    assert len(stored(path)) == 688


def test_failed_update_rolls_back_rows_membership_and_version(tmp_path, caplog):
    path = tmp_path / "atomic.db"
    store = SQLiteEventStore(path)
    store.append(unrelated())
    DemoDataLoader(store, clock=lambda: NOW).ensure_current()
    tables = ("events", "demo_datasets", "demo_dataset_events")
    before = [stored(path, table) for table in tables]
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TRIGGER fail_demo BEFORE INSERT ON events
            WHEN NEW.source='synthetic_demo' BEGIN
            SELECT RAISE(ABORT, 'PRIVATE fault detail'); END;""")
    with pytest.raises(RuntimeError, match="^analytics_demo_load_failed$"):
        DemoDataLoader(store, dataset=updated_dataset(), clock=lambda: NOW).ensure_current()
    assert [stored(path, table) for table in tables] == before
    assert "analytics_demo_load_failed" in caplog.text and "PRIVATE" not in caplog.text


def test_runtime_identity_collision_is_rejected_without_mutation(tmp_path):
    store = SQLiteEventStore(tmp_path / "collision.db")
    collision = load_demo_dataset().fixture.core[0].model_copy(update={"source": "runtime"})
    store.append(collision)
    original = stored(store.path)
    with pytest.raises(RuntimeError, match="analytics_demo_load_failed"):
        DemoDataLoader(store, clock=lambda: NOW).ensure_current()
    assert stored(store.path) == original


def test_disabled_mode_never_installs_or_removes_existing_data(tmp_path, monkeypatch):
    path = tmp_path / "disabled.db"
    store = SQLiteEventStore(path)
    store.append(unrelated())
    with TestClient(app_at(path, monkeypatch, enabled=False)) as client:
        assert not client.get("/health").json()["analytics_demo"]["enabled"]
        assert client.get("/api/analytics/events").json()["total"] == 1
    DemoDataLoader(store, clock=lambda: NOW).ensure_current()
    original = stored(path)
    with TestClient(
        app_at(path, monkeypatch, enabled=False, now=NOW + timedelta(days=1))
    ) as client:
        assert client.get("/api/analytics/events").json()["total"] == 689
    assert stored(path) == original


def test_startup_failure_is_explicit_and_refresh_failure_is_retryable(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("PRIVATE database path")

    with monkeypatch.context() as patch:
        patch.setattr(SQLiteEventStore, "install_demo_dataset", fail)
        with pytest.raises(RuntimeError, match="^analytics_demo_load_failed$"):
            with TestClient(app_at(tmp_path / "failed.db", patch)):
                pytest.fail("startup must not serve an empty enabled demo")
    with TestClient(app_at(tmp_path / "retry.db", monkeypatch)) as client:
        loader = client.app.state.services.demo_data
        loader.clock = lambda: NOW + timedelta(days=1)
        with monkeypatch.context() as patch:
            patch.setattr(loader.store, "install_demo_dataset", fail)
            response = client.get("/api/analytics/overview")
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "analytics_storage_unavailable"
            assert "PRIVATE" not in response.text
        assert client.get("/api/analytics/overview").status_code == 200


def test_cli_reset_is_scoped_and_clock_changes_keep_identities(tmp_path, monkeypatch, capsys):
    path = tmp_path / "cli.db"
    store = SQLiteEventStore(path)
    store.append_many([unrelated(), unrelated("synthetic_demo")])
    original = stored(path)
    identities = None
    for now in (NOW, NOW + timedelta(days=30)):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "seed_analytics_demo.py",
                "--db-path",
                str(path),
                "--reset",
                "--with-anomaly",
                "--as-of",
                now.isoformat(),
            ],
        )
        demo.seed_cli()
        rows = stored(path)
        assert len(rows) == 690 and all(row in rows for row in original)
        current = {row[0] for row in rows}
        assert identities is None or current == identities
        identities = current
    assert "synthetic_conversations" in capsys.readouterr().out


def test_fixture_failure_does_not_log_payload_or_path(tmp_path, monkeypatch, caplog):
    def broken():
        raise ValueError("PRIVATE fixture payload")

    monkeypatch.setattr(demo, "load_demo_dataset", broken)
    with pytest.raises(RuntimeError, match="^analytics_demo_fixture_invalid$"):
        DemoDataLoader(SQLiteEventStore(tmp_path / "invalid.db"))
    assert "analytics_demo_fixture_invalid" in caplog.text
    assert "PRIVATE" not in caplog.text


def test_enabled_data_still_requires_hosted_login(tmp_path):
    origin = "https://veyra.test"
    password = "offline-demo-password-fixture"
    app = create_app(
        Settings(
            _env_file=None,
            openai_api_key=None,
            event_db_path=tmp_path / "private.db",
            analytics_demo_data_enabled=True,
            frontend_origin=origin,
            demo_access_password=password,
            demo_session_secret="offline-cookie-signing-fixture-0123456789",
        )
    )
    with TestClient(app, base_url=origin) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/analytics/overview").status_code == 401
        response = client.post(
            "/login",
            data={"password": password},
            headers={"Origin": origin},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert client.get("/health").json()["analytics_demo"]["enabled"]
        assert client.get("/api/analytics/overview").json()["total_sessions"] == 144
