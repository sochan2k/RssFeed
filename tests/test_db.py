"""Unit tests for src/db.py holdings (portfolio) helpers, against a temp DB."""
import importlib

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Reload db with DB_PATH/DATA_DIR pointed at an isolated temp directory."""
    from src import db as _db
    monkeypatch.setattr(_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(_db, "DB_PATH", tmp_path / "test.db")
    _db.init_db()
    return _db


class TestHoldings:
    def test_add_and_get(self, db):
        db.add_holding("NVDA", 10, 120.0, 200.0)
        holdings = db.get_holdings()
        assert len(holdings) == 1
        h = holdings[0]
        assert h["ticker"] == "NVDA"
        assert h["shares"] == 10
        assert h["avg_cost"] == 120.0
        assert h["target_price"] == 200.0

    def test_expected_return_math(self, db):
        db.add_holding("NVDA", 10, 120.0, 200.0)
        h = db.get_holdings()[0]
        # (200 - 120) / 120 = 0.6667
        assert h["expected_return"] == pytest.approx((200.0 - 120.0) / 120.0)

    def test_expected_return_none_without_target(self, db):
        db.add_holding("AAPL", 5, 150.0)
        h = db.get_holdings()[0]
        assert h["target_price"] is None
        assert h["expected_return"] is None

    def test_ticker_uppercased(self, db):
        db.add_holding("tsla", 3, 250.0)
        assert db.get_holdings()[0]["ticker"] == "TSLA"

    def test_add_is_upsert(self, db):
        db.add_holding("NVDA", 10, 120.0, 200.0)
        db.add_holding("NVDA", 20, 130.0, 210.0)
        holdings = db.get_holdings()
        assert len(holdings) == 1
        assert holdings[0]["shares"] == 20
        assert holdings[0]["avg_cost"] == 130.0

    def test_remove(self, db):
        db.add_holding("NVDA", 10, 120.0)
        assert db.remove_holding("nvda") is True
        assert db.get_holdings() == []

    def test_remove_missing_returns_false(self, db):
        assert db.remove_holding("MSFT") is False


class TestBuyHolding:
    def test_new_position(self, db):
        h = db.buy_holding("NVDA", 10, 120.0, 200.0)
        assert h["shares"] == 10
        assert h["avg_cost"] == 120.0
        assert h["target_price"] == 200.0

    def test_rebuy_averages_cost(self, db):
        db.buy_holding("NVDA", 10, 100.0)
        h = db.buy_holding("NVDA", 10, 200.0)
        # 20 shares, weighted-avg cost = (10*100 + 10*200)/20 = 150
        assert h["shares"] == 20
        assert h["avg_cost"] == pytest.approx(150.0)

    def test_rebuy_weighted_not_simple_mean(self, db):
        db.buy_holding("NVDA", 30, 100.0)
        h = db.buy_holding("NVDA", 10, 200.0)
        # (30*100 + 10*200)/40 = 125, not the simple mean 150
        assert h["avg_cost"] == pytest.approx(125.0)

    def test_rebuy_keeps_existing_target_when_omitted(self, db):
        db.buy_holding("NVDA", 10, 100.0, 200.0)
        h = db.buy_holding("NVDA", 10, 120.0)
        assert h["target_price"] == 200.0

    def test_rebuy_updates_target_when_given(self, db):
        db.buy_holding("NVDA", 10, 100.0, 200.0)
        h = db.buy_holding("NVDA", 10, 120.0, 250.0)
        assert h["target_price"] == 250.0


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
