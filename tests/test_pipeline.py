"""Unit tests for src/pipeline.py enrichment helpers."""
from unittest.mock import AsyncMock, patch

import pytest

import src.pipeline as p


_ARTICLES = [
    {"title": "Microsoft MSFT cloud growth slows", "summary": "Azure decelerates",
     "link": "https://news/1"},
    {"title": "Local bakery opens downtown", "summary": "", "link": "https://news/2"},
]


class TestRelevantTickers:
    def test_finds_watchlist_tickers_mentioned(self):
        with patch("src.pipeline.db.get_watchlist", return_value={"ai_tech": ["MSFT", "NVDA"]}):
            assert p._relevant_tickers(_ARTICLES) == ["MSFT"]

    def test_word_boundary_no_false_positive(self):
        # "MU" must not match inside "Museum".
        arts = [{"title": "Museum exhibit opens", "summary": "", "link": "x"}]
        with patch("src.pipeline.db.get_watchlist", return_value={"semi": ["MU"]}):
            assert p._relevant_tickers(arts) == []

    def test_matches_body_text_too(self):
        arts = [{"title": "Chip news", "summary": "", "link": "x",
                 "body": "Analysts highlighted NVDA data-center demand."}]
        with patch("src.pipeline.db.get_watchlist", return_value={"ai_tech": ["NVDA"]}):
            assert p._relevant_tickers(arts) == ["NVDA"]


class TestEnrich:
    @pytest.mark.asyncio
    async def test_enrich_fetches_bodies_and_snapshots(self):
        snap = {"MSFT": {"ticker": "MSFT", "price": 410.0, "chg_1d": -0.04}}
        with patch("src.pipeline.db.get_watchlist", return_value={"ai_tech": ["MSFT"]}), \
             patch("src.pipeline.fetch_article_bodies", new=AsyncMock()) as fb, \
             patch("src.pipeline.get_market_snapshot", new=AsyncMock(return_value=snap)) as gm:
            out = await p._enrich(_ARTICLES, top_k=5)
        assert out == snap
        fb.assert_awaited_once()
        gm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_enrich_never_raises_on_failure(self):
        with patch("src.pipeline.db.get_watchlist", return_value={"ai_tech": ["MSFT"]}), \
             patch("src.pipeline.fetch_article_bodies", new=AsyncMock(side_effect=RuntimeError("net"))), \
             patch("src.pipeline.get_market_snapshot", new=AsyncMock(side_effect=RuntimeError("boom"))):
            out = await p._enrich(_ARTICLES, top_k=5)
        assert out == {}

    @pytest.mark.asyncio
    async def test_enrich_skips_body_when_disabled(self):
        with patch("src.pipeline.ENABLE_ARTICLE_BODY", False), \
             patch("src.pipeline.db.get_watchlist", return_value={"ai_tech": ["MSFT"]}), \
             patch("src.pipeline.fetch_article_bodies", new=AsyncMock()) as fb, \
             patch("src.pipeline.get_market_snapshot", new=AsyncMock(return_value={})):
            await p._enrich(_ARTICLES, top_k=5)
        fb.assert_not_awaited()
