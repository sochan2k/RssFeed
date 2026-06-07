"""Unit tests for src/prices.py — P&L math, quote caching, graceful fallback."""
from unittest.mock import AsyncMock, patch

import pytest

from src import prices


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
