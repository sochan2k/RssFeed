"""Unit tests for src/filters.py — heuristics, watchlist scoring, headline dedup."""
from unittest.mock import patch

import pytest

from src.filters import _is_blacklisted, _similar, _watchlist_score, filter_articles


def _article(title: str, summary: str = "", link: str = "https://example.com/a") -> dict:
    return {"title": title, "summary": summary, "link": link, "published_utc": None, "source": "test"}


# Sample ticker list passed to _watchlist_score (the function takes a pre-fetched
# list so it doesn't hit the DB per article — see filters.py).
_TICKERS = ["AAPL", "NVDA", "MSFT", "GOOG", "TSLA"]


# ---------------------------------------------------------------------------
# _is_blacklisted
# ---------------------------------------------------------------------------

class TestIsBlacklisted:
    def test_clean_article_not_blacklisted(self):
        assert not _is_blacklisted(_article("Apple earnings beat estimates"))

    def test_opinion_keyword_blacklisted(self):
        assert _is_blacklisted(_article("My opinion on Fed policy"))

    def test_blacklist_in_summary(self):
        assert _is_blacklisted(_article("Market update", "sponsored content by XYZ"))

    def test_case_insensitive(self):
        assert _is_blacklisted(_article("CELEBRITY investor buys Tesla"))


# ---------------------------------------------------------------------------
# _watchlist_score
# ---------------------------------------------------------------------------

class TestWatchlistScore:
    def test_watchlist_ticker_scores(self):
        assert _watchlist_score(_article("AAPL stock rises after earnings"), _TICKERS) >= 1

    def test_macro_term_scores(self):
        assert _watchlist_score(_article("Fed raises interest rate by 25bps"), _TICKERS) >= 1

    def test_irrelevant_article_scores_zero(self):
        assert _watchlist_score(_article("Local restaurant opens downtown"), _TICKERS) == 0

    def test_multiple_matches_additive(self):
        score = _watchlist_score(_article("NVDA MSFT earnings beat; Fed holds rate"), _TICKERS)
        assert score >= 3


# ---------------------------------------------------------------------------
# _similar
# ---------------------------------------------------------------------------

class TestSimilar:
    def test_identical_headlines_similar(self):
        assert _similar("Apple beats earnings", "Apple beats earnings")

    def test_slightly_different_similar(self):
        assert _similar(
            "Apple reports record quarterly earnings",
            "Apple reports record quarterly earnings beat",
        )

    def test_completely_different_not_similar(self):
        assert not _similar("Apple earnings beat", "Fed raises interest rates today")

    def test_case_insensitive(self):
        assert _similar("AAPL EARNINGS BEAT", "aapl earnings beat")


# ---------------------------------------------------------------------------
# filter_articles — integration of all layers
# ---------------------------------------------------------------------------

class TestFilterArticles:
    @pytest.fixture(autouse=True)
    def _patch_watchlist(self):
        """Pin the watchlist so tests don't depend on live DB state (mutable via /add)."""
        with patch(
            "src.filters.db.get_watchlist",
            return_value={"ai_tech": ["NVDA", "AAPL", "MSFT"]},
        ):
            yield

    def _make_articles(self, specs: list[tuple]) -> list[dict]:
        """specs: list of (title, link) tuples"""
        return [_article(title, link=link) for title, link in specs]

    def test_blacklisted_article_removed(self):
        articles = [
            _article("Apple earnings beat estimates", link="https://a.com/1"),
            _article("Celebrity gossip opinion piece", link="https://a.com/2"),
        ]
        with patch("src.filters.db.is_seen", return_value=False), \
             patch("src.filters.db.mark_seen"):
            result = filter_articles(articles)
        assert all("gossip" not in a["title"].lower() for a in result)

    def test_zero_score_article_removed(self):
        articles = [
            _article("NVDA surges after AI chip announcement", link="https://a.com/1"),
            _article("Local bakery wins award", link="https://a.com/2"),
        ]
        with patch("src.filters.db.is_seen", return_value=False), \
             patch("src.filters.db.mark_seen"):
            result = filter_articles(articles)
        assert len(result) == 1
        assert "NVDA" in result[0]["title"]

    def test_already_seen_article_excluded(self):
        articles = [_article("Fed raises rates 25bps", link="https://a.com/1")]
        with patch("src.filters.db.is_seen", return_value=True), \
             patch("src.filters.db.mark_seen"):
            result = filter_articles(articles)
        assert result == []

    def test_similar_headline_dedup(self):
        articles = [
            _article("AAPL reports record quarterly earnings beat", link="https://a.com/1"),
            _article("AAPL reports record quarterly earnings beat estimates", link="https://a.com/2"),
        ]
        with patch("src.filters.db.is_seen", return_value=False), \
             patch("src.filters.db.mark_seen"):
            result = filter_articles(articles)
        assert len(result) == 1

    def test_survivors_marked_seen(self):
        articles = [_article("MSFT earnings beat guidance raised", link="https://a.com/1")]
        with patch("src.filters.db.is_seen", return_value=False) as mock_seen, \
             patch("src.filters.db.mark_seen") as mock_mark:
            filter_articles(articles)
        mock_mark.assert_called_once_with("https://a.com/1")
