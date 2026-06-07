"""Unit tests for src/db.py forecast helpers, against a temp DB."""
import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Reload db with DB_PATH/DATA_DIR pointed at an isolated temp directory."""
    from src import db as _db
    monkeypatch.setattr(_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(_db, "DB_PATH", tmp_path / "test.db")
    _db.init_db()
    return _db


class TestForecasts:
    def test_add_and_get(self, db):
        assert db.add_forecast("NVDA", 200.0, base_price=120.0, source="user") is True
        rows = db.get_forecasts("NVDA")
        assert len(rows) == 1
        assert rows[0]["target_price"] == 200.0
        assert rows[0]["base_price"] == 120.0
        assert rows[0]["source"] == "user"

    def test_dedup_identical_within_window(self, db):
        assert db.add_forecast("NVDA", 200.0, source="analyst") is True
        # identical (ticker, source, target) again → deduped
        assert db.add_forecast("NVDA", 200.0, source="analyst") is False
        assert len(db.get_forecasts("NVDA")) == 1

    def test_revised_target_inserts(self, db):
        db.add_forecast("NVDA", 200.0, source="analyst")
        assert db.add_forecast("NVDA", 220.0, source="analyst") is True
        assert len(db.get_forecasts("NVDA")) == 2

    def test_same_target_different_source_inserts(self, db):
        db.add_forecast("NVDA", 200.0, source="user")
        assert db.add_forecast("NVDA", 200.0, source="analyst") is True
        assert len(db.get_forecasts("NVDA")) == 2

    def test_get_latest_returns_newest(self, db):
        db.add_forecast("NVDA", 200.0, source="user")
        db.add_forecast("NVDA", 250.0, source="user")
        assert db.get_latest_forecast("NVDA")["target_price"] == 250.0

    def test_get_latest_source_filter(self, db):
        db.add_forecast("NVDA", 200.0, source="user")
        db.add_forecast("NVDA", 300.0, source="analyst")
        assert db.get_latest_forecast("NVDA", source="user")["target_price"] == 200.0
