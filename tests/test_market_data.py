"""Unit tests for src/market_data.py — snapshot building, caching, degradation."""
from unittest.mock import patch

import pytest

import src.market_data as md


@pytest.fixture(autouse=True)
def _clear_cache():
    md._cache.clear()
    yield
    md._cache.clear()


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_pct_basic(self):
        assert md._pct(110, 100) == pytest.approx(0.10)

    def test_pct_none_inputs(self):
        assert md._pct(None, 100) is None
        assert md._pct(100, None) is None
        assert md._pct(100, 0) is None


# ---------------------------------------------------------------------------
# get_market_snapshot — uses a mocked synchronous fetcher
# ---------------------------------------------------------------------------

class TestGetMarketSnapshot:
    @pytest.mark.asyncio
    async def test_returns_snapshots(self):
        fake = {"MSFT": {"ticker": "MSFT", "price": 410.0, "chg_1d": -0.042}}
        with patch("src.market_data._fetch_snapshots", return_value=fake) as m:
            out = await md.get_market_snapshot(["MSFT"])
        assert out["MSFT"]["price"] == 410.0
        m.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_input(self):
        out = await md.get_market_snapshot([])
        assert out == {}

    @pytest.mark.asyncio
    async def test_dedup_and_uppercase(self):
        captured = {}

        def _fake(tickers):
            captured["tickers"] = tickers
            return {t.upper(): {"ticker": t.upper(), "price": 1.0} for t in tickers}

        with patch("src.market_data._fetch_snapshots", side_effect=_fake):
            await md.get_market_snapshot(["msft", "MSFT", "nvda"])
        # de-duped, upper-cased
        assert captured["tickers"] == ["MSFT", "NVDA"]

    @pytest.mark.asyncio
    async def test_caps_to_max_tickers(self):
        captured = {}

        def _fake(tickers):
            captured["tickers"] = tickers
            return {t: {"ticker": t, "price": 1.0} for t in tickers}

        with patch("src.market_data.MARKET_DATA_MAX_TICKERS", 2), \
             patch("src.market_data._fetch_snapshots", side_effect=_fake):
            await md.get_market_snapshot(["A", "B", "C", "D"])
        assert captured["tickers"] == ["A", "B"]

    @pytest.mark.asyncio
    async def test_uses_cache_on_second_call(self):
        fake = {"MSFT": {"ticker": "MSFT", "price": 410.0}}
        with patch("src.market_data._fetch_snapshots", return_value=fake) as m:
            await md.get_market_snapshot(["MSFT"])
            await md.get_market_snapshot(["MSFT"])  # should hit cache
        assert m.call_count == 1

    @pytest.mark.asyncio
    async def test_never_raises_on_fetch_error(self):
        with patch("src.market_data._fetch_snapshots", side_effect=RuntimeError("boom")):
            out = await md.get_market_snapshot(["MSFT"])
        assert out == {}  # degrades gracefully


# ---------------------------------------------------------------------------
# _fetch_snapshots — drops tickers with no usable price
# ---------------------------------------------------------------------------

class TestFetchSnapshots:
    def test_drops_priceless_snapshot(self):
        def _one(t):
            return {"ticker": t.upper()} if t == "BAD" else {"ticker": t.upper(), "price": 5.0}

        with patch("src.market_data._snapshot_one", side_effect=_one):
            out = md._fetch_snapshots(["GOOD", "BAD"])
        assert "GOOD" in out
        assert "BAD" not in out

    def test_one_bad_ticker_does_not_sink_batch(self):
        def _one(t):
            if t == "BOOM":
                raise ValueError("nope")
            return {"ticker": t.upper(), "price": 1.0}

        with patch("src.market_data._snapshot_one", side_effect=_one):
            out = md._fetch_snapshots(["BOOM", "OK"])
        assert "OK" in out
        assert "BOOM" not in out
