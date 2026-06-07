"""Unit tests for src/prices.py — P&L math, quote caching, graceful fallback."""
from unittest.mock import AsyncMock, patch

import pytest

from src import prices


def _holding(ticker, shares, cost, target=None):
    h = {"ticker": ticker, "shares": shares, "avg_cost": cost, "target_price": target,
         "note": None}
    h["expected_return"] = (target - cost) / cost if target is not None and cost else None
    return h


class TestComputePnl:
    def test_unrealized_return_and_pl(self):
        holdings = [_holding("NVDA", 10, 100.0, 200.0)]
        out = prices.compute_pnl(holdings, {"NVDA": 150.0})[0]
        assert out["current_price"] == 150.0
        assert out["market_value"] == 1500.0
        assert out["cost_basis"] == 1000.0
        assert out["unrealized_pl"] == 500.0
        assert out["unrealized_return"] == pytest.approx(0.5)

    def test_to_target_is_remaining_move_from_price(self):
        out = prices.compute_pnl([_holding("NVDA", 1, 100.0, 200.0)], {"NVDA": 160.0})[0]
        # (200 - 160) / 160 = 0.25 still to go
        assert out["to_target"] == pytest.approx(0.25)

    def test_missing_price_yields_none_fields(self):
        out = prices.compute_pnl([_holding("NVDA", 10, 100.0, 200.0)], {})[0]
        assert out["current_price"] is None
        assert out["unrealized_pl"] is None
        assert out["to_target"] is None
        # expected_return (from cost) is still available as a fallback
        assert out["expected_return"] == pytest.approx(1.0)

    def test_weights_sum_to_one(self):
        holdings = [_holding("NVDA", 10, 100.0), _holding("AAPL", 10, 100.0)]
        out = prices.compute_pnl(holdings, {"NVDA": 300.0, "AAPL": 100.0})
        weights = [h["weight"] for h in out]
        assert sum(weights) == pytest.approx(1.0)
        # NVDA worth 3000, AAPL 1000 -> 75% / 25%
        assert out[0]["weight"] == pytest.approx(0.75)

    def test_weight_falls_back_to_cost_when_unpriced(self):
        holdings = [_holding("NVDA", 10, 100.0), _holding("AAPL", 10, 100.0)]
        out = prices.compute_pnl(holdings, {})  # no prices at all
        assert sum(h["weight"] for h in out) == pytest.approx(1.0)


def _forecast(target, base=None, source="user", created_days_ago=0):
    from datetime import datetime, timedelta, timezone
    created = (datetime.now(timezone.utc) - timedelta(days=created_days_ago)).isoformat()
    return {"ticker": "NVDA", "target_price": target, "base_price": base,
            "source": source, "note": None, "created_at": created}


class TestComputeForecastStatus:
    def test_gap_to_target_from_current_only(self):
        s = prices.compute_forecast_status(_forecast(200.0), 160.0)
        # (200 - 160) / 160 = 0.25 still to go
        assert s["gap_to_target"] == pytest.approx(0.25)
        assert s["progress"] is None  # no base price

    def test_progress_when_base_set(self):
        s = prices.compute_forecast_status(_forecast(200.0, base=100.0), 180.0)
        # (180 - 100) / (200 - 100) = 0.8
        assert s["progress"] == pytest.approx(0.8)

    def test_reached_upside(self):
        assert prices.compute_forecast_status(_forecast(200.0, base=100.0), 205.0)["reached"] is True
        assert prices.compute_forecast_status(_forecast(200.0, base=100.0), 195.0)["reached"] is False

    def test_reached_downside(self):
        # target below base = downside target
        s_hit = prices.compute_forecast_status(_forecast(150.0, base=200.0), 140.0)
        s_miss = prices.compute_forecast_status(_forecast(150.0, base=200.0), 160.0)
        assert s_hit["reached"] is True
        assert s_miss["reached"] is False

    def test_missing_current_price_is_graceful(self):
        s = prices.compute_forecast_status(_forecast(200.0, base=100.0), None)
        assert s["gap_to_target"] is None
        assert s["progress"] is None
        assert s["reached"] is None

    def test_age_days(self):
        s = prices.compute_forecast_status(_forecast(200.0, created_days_ago=30), 150.0)
        assert s["age_days"] == 30


@pytest.mark.asyncio
class TestGetQuotes:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        prices._cache.clear()
        yield
        prices._cache.clear()

    async def test_caches_within_ttl(self):
        fetch = AsyncMock(return_value={"NVDA": 150.0})
        with patch("src.prices._fetch", fetch):
            a = await prices.get_quotes(["NVDA"])
            b = await prices.get_quotes(["NVDA"])
        assert a == b == {"NVDA": 150.0}
        fetch.assert_awaited_once()  # second call served from cache

    async def test_failure_returns_empty_not_raises(self):
        with patch("src.prices._fetch", AsyncMock(side_effect=RuntimeError("boom"))):
            assert await prices.get_quotes(["NVDA"]) == {}

    async def test_empty_tickers_short_circuits(self):
        fetch = AsyncMock(return_value={})
        with patch("src.prices._fetch", fetch):
            assert await prices.get_quotes([]) == {}
        fetch.assert_not_awaited()
