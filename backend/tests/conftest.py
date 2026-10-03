"""Every offline application test writes analytics only to its temporary directory."""

import pytest


@pytest.fixture(autouse=True)
def isolated_analytics_db(tmp_path, monkeypatch):
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "events.db"))
