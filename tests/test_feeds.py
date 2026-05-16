"""Unit tests for src/feeds.py — date parsing, age filtering, HTML stripping."""
import asyncio
import calendar
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import feedparser
import pytest

from src.feeds import _parse_date, _strip_html, fetch_articles


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------

class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<b>Bold</b> text") == "Bold text"

    def test_plain_text_unchanged(self):
        assert _strip_html("No tags here") == "No tags here"

    def test_strips_whitespace(self):
        assert _strip_html("  hello  ") == "hello"

    def test_nested_tags(self):
        assert _strip_html("<div><p>Hello</p></div>") == "Hello"


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def _make_entry(self, field: str, dt: datetime) -> dict:
        ts = calendar.timegm(dt.utctimetuple())
        return {field: time.gmtime(ts)}

    def test_published_parsed_preferred(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        entry = self._make_entry("published_parsed", now)
        result = _parse_date(entry)
        assert result is not None
        assert abs((result - now).total_seconds()) < 2

    def test_falls_back_to_updated_parsed(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        entry = self._make_entry("updated_parsed", now)
        result = _parse_date(entry)
        assert result is not None

    def test_returns_none_when_no_date(self):
        assert _parse_date({}) is None

    def test_result_is_utc_aware(self):
        now = datetime.now(timezone.utc)
        entry = self._make_entry("published_parsed", now)
        result = _parse_date(entry)
        assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# fetch_articles — age filtering
# ---------------------------------------------------------------------------

def _make_feed(entries: list[dict]) -> MagicMock:
    feed = MagicMock()
    feed.feed.get.return_value = "Test Feed"
    feed.entries = entries
    return feed


def _make_entry(title: str, dt: datetime, link: str = "https://example.com/article") -> dict:
    ts = calendar.timegm(dt.utctimetuple())
    entry = MagicMock()
    entry.get = MagicMock(side_effect=lambda k, d=None: {
        "title": title,
        "summary": "",
        "link": link,
        "published_parsed": time.gmtime(ts),
    }.get(k, d))
    return entry


@pytest.mark.asyncio
async def test_fetch_articles_excludes_old_articles():
    """Articles older than ARTICLE_MAX_AGE_HOURS must be dropped."""
    now = datetime.now(timezone.utc)
    recent = _make_entry("AAPL earnings beat", now - timedelta(hours=1))
    old = _make_entry("NVDA old news", now - timedelta(hours=30))
    feed = _make_feed([recent, old])

    with patch("src.feeds.RSS_FEEDS", ["https://fake.feed/rss"]), \
         patch("src.feeds._fetch_one", new=AsyncMock(return_value=feed)):
        articles = await fetch_articles()

    assert len(articles) == 1
    assert "AAPL" in articles[0]["title"]


@pytest.mark.asyncio
async def test_fetch_articles_breaking_window():
    """hours_back overrides the default 24h window."""
    now = datetime.now(timezone.utc)
    very_recent = _make_entry("Fed decision", now - timedelta(minutes=30))
    hour_old = _make_entry("MSFT guidance", now - timedelta(hours=3))
    feed = _make_feed([very_recent, hour_old])

    with patch("src.feeds.RSS_FEEDS", ["https://fake.feed/rss"]), \
         patch("src.feeds._fetch_one", new=AsyncMock(return_value=feed)):
        articles = await fetch_articles(hours_back=2)

    assert len(articles) == 1
    assert "Fed" in articles[0]["title"]


@pytest.mark.asyncio
async def test_fetch_articles_failed_feed_skipped():
    """A feed that raises an exception should be skipped, not crash the pipeline."""
    now = datetime.now(timezone.utc)
    good_feed = _make_feed([_make_entry("GOOGL earnings", now - timedelta(hours=1))])

    async def _side_effect(session, url):
        if "bad" in url:
            raise ConnectionError("timeout")
        return good_feed

    with patch("src.feeds.RSS_FEEDS", ["https://good.feed/rss", "https://bad.feed/rss"]), \
         patch("src.feeds._fetch_one", new=AsyncMock(side_effect=_side_effect)):
        articles = await fetch_articles()

    assert len(articles) == 1
