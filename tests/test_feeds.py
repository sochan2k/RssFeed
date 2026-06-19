"""Unit tests for src/feeds.py — date parsing, age filtering, HTML stripping."""
import asyncio
import calendar
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import feedparser
import pytest

from src.feeds import (
    _extract_body,
    _parse_date,
    _strip_html,
    fetch_article_bodies,
    fetch_articles,
)


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


# ---------------------------------------------------------------------------
# _extract_body — paragraph extraction from HTML
# ---------------------------------------------------------------------------

class TestExtractBody:
    def test_extracts_paragraph_text(self):
        html = (
            "<html><body>"
            "<p>Microsoft reported Azure revenue grew 31% year over year, below the "
            "33% analysts had expected.</p>"
            "<p>The company also guided capital expenditure to roughly $80 billion "
            "for the fiscal year, well above prior estimates.</p>"
            "</body></html>"
        )
        body = _extract_body(html)
        assert "Azure revenue grew 31%" in body
        assert "$80 billion" in body

    def test_drops_script_and_style(self):
        html = (
            "<p>Real content here that is definitely long enough to be kept in body.</p>"
            "<script>var x = 'tracking pixel garbage should not appear';</script>"
            "<style>.cls { color: red; }</style>"
        )
        body = _extract_body(html)
        assert "Real content here" in body
        assert "tracking pixel" not in body
        assert "color: red" not in body

    def test_truncates_to_max_chars(self):
        long_para = "<p>" + ("word " * 1000) + "</p>"
        body = _extract_body(long_para, max_chars=100)
        assert len(body) <= 101  # 100 + the ellipsis char
        assert body.endswith("…")

    def test_empty_on_no_paragraphs(self):
        assert _extract_body("<div>no paragraph tags here</div>") == ""

    def test_malformed_html_does_not_raise(self):
        # Unclosed tags / garbage must not raise.
        assert isinstance(_extract_body("<p>unclosed <b>bold text that is long enough"), str)


# ---------------------------------------------------------------------------
# fetch_article_bodies — bounded, mutating, non-raising
# ---------------------------------------------------------------------------

def _body_html(text: str) -> str:
    return f"<html><body><p>{text}</p></body></html>"


class _FakeResp:
    def __init__(self, status: int, text: str):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    """Minimal aiohttp.ClientSession stand-in keyed by URL → (status, html)."""

    def __init__(self, pages: dict):
        self._pages = pages

    def get(self, url, **kwargs):
        status, html = self._pages.get(url, (404, ""))
        return _FakeResp(status, html)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_fetch_article_bodies_attaches_body():
    articles = [
        {"title": "MSFT", "link": "https://news/msft"},
        {"title": "NVDA", "link": "https://news/nvda"},
    ]
    pages = {
        "https://news/msft": (200, _body_html("Azure grew 31% year over year, a slowdown from prior quarters.")),
        "https://news/nvda": (200, _body_html("Nvidia data center revenue surged on strong AI chip demand worldwide.")),
    }
    with patch("src.feeds.aiohttp.ClientSession", return_value=_FakeSession(pages)):
        await fetch_article_bodies(articles, limit=5)

    assert "Azure grew 31%" in articles[0]["body"]
    assert "data center revenue surged" in articles[1]["body"]


@pytest.mark.asyncio
async def test_fetch_article_bodies_respects_limit():
    articles = [{"title": str(i), "link": f"https://news/{i}"} for i in range(5)]
    pages = {f"https://news/{i}": (200, _body_html("Some sufficiently long article body text here.")) for i in range(5)}
    with patch("src.feeds.aiohttp.ClientSession", return_value=_FakeSession(pages)):
        await fetch_article_bodies(articles, limit=2)

    assert articles[0].get("body") and articles[1].get("body")
    assert all("body" not in a for a in articles[2:])


@pytest.mark.asyncio
async def test_fetch_article_bodies_skips_non_200_and_does_not_raise():
    articles = [
        {"title": "ok", "link": "https://news/ok"},
        {"title": "missing", "link": "https://news/missing"},
    ]
    pages = {"https://news/ok": (200, _body_html("A perfectly valid and sufficiently long body of text."))}
    with patch("src.feeds.aiohttp.ClientSession", return_value=_FakeSession(pages)):
        await fetch_article_bodies(articles, limit=5)  # missing -> 404

    assert articles[0].get("body")
    assert "body" not in articles[1]
