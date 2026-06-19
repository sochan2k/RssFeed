import asyncio
import calendar
import logging
import re
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

import aiohttp
import feedparser
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import (
    ARTICLE_BODY_FETCH_CONCURRENCY,
    ARTICLE_BODY_FETCH_TIMEOUT,
    ARTICLE_BODY_MAX_CHARS,
    ARTICLE_MAX_AGE_HOURS,
    RSS_FEEDS,
)

logger = logging.getLogger(__name__)

_HTML_TAG = re.compile(r"<[^>]+>")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; StockDigestBot/1.0; +https://github.com)"
    )
}


def _strip_html(text: str) -> str:
    return _HTML_TAG.sub("", text).strip()


def _parse_date(entry: dict) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        t = entry.get(field)
        if t:
            try:
                return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
            except Exception:
                continue
    return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
    reraise=True,
)
async def _fetch_one(session: aiohttp.ClientSession, url: str) -> feedparser.FeedParserDict:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        content = await resp.text()
    return await asyncio.to_thread(feedparser.parse, content)


async def fetch_articles(hours_back: int | None = None) -> list[dict]:
    """
    Fetch all RSS feeds concurrently and return articles within the time window.
    hours_back overrides ARTICLE_MAX_AGE_HOURS (used for /breaking).
    """
    max_age = hours_back or ARTICLE_MAX_AGE_HOURS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age)
    articles: list[dict] = []

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
        results = await asyncio.gather(
            *[_fetch_one(session, url) for url in RSS_FEEDS],
            return_exceptions=True,
        )

    for feed, url in zip(results, RSS_FEEDS):
        if isinstance(feed, Exception):
            logger.warning("Feed %s failed: %s", url, feed)
            continue
        feed_title = feed.feed.get("title", url)
        for entry in feed.entries:
            published = _parse_date(entry)
            if published and published < cutoff:
                continue
            title = _strip_html(entry.get("title", "")).strip()
            summary = _strip_html(entry.get("summary", "")).strip()
            link = entry.get("link", "")
            if not title or not link:
                continue
            articles.append({
                "title": title,
                "summary": summary,
                "link": link,
                "published_utc": published.isoformat() if published else None,
                "source": feed_title,
            })

    logger.info("Fetched %d raw articles from %d feeds", len(articles), len(RSS_FEEDS))
    return articles


# ---------------------------------------------------------------------------
# Article body extraction
# ---------------------------------------------------------------------------
# RSS summaries are usually just the headline restated; the body holds the real
# figures (e.g. "Azure +31%, CapEx $80B"). We fetch the page and pull paragraph
# text with the stdlib html.parser — no extra dependency (deliberate: lxml /
# trafilatura are painful to build on a Pi Zero 2 W).

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}


class _ParagraphExtractor(HTMLParser):
    """Collect text inside <p> tags, ignoring scripts/styles. The concatenated
    paragraph text is a good-enough proxy for article body across most news sites."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._in_p = 0
        self._buf: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "p":
            self._in_p += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "p" and self._in_p:
            self._in_p -= 1
            if self._in_p == 0:
                text = " ".join("".join(self._buf).split())
                if text:
                    self.paragraphs.append(text)
                self._buf = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and self._in_p:
            self._buf.append(data)


def _extract_body(html: str, max_chars: int = ARTICLE_BODY_MAX_CHARS) -> str:
    """Extract readable paragraph text from an HTML page, truncated to max_chars.

    Returns "" when no meaningful text is found. Drops very short fragments
    (nav links, captions) by keeping only paragraphs of a reasonable length.
    """
    parser = _ParagraphExtractor()
    try:
        parser.feed(html)
    except Exception:
        return ""
    paras = [p for p in parser.paragraphs if len(p) >= 40]
    if not paras:
        # Fall back to any paragraph text if nothing met the length bar.
        paras = parser.paragraphs
    body = "\n".join(paras).strip()
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "…"
    return body


async def _fetch_body_one(session: aiohttp.ClientSession, article: dict,
                          sem: asyncio.Semaphore) -> None:
    """Fetch and attach `body` to one article. Never raises — on any failure the
    article keeps only its RSS summary (no body key added)."""
    link = article.get("link")
    if not link:
        return
    try:
        async with sem:
            async with session.get(
                link, timeout=aiohttp.ClientTimeout(total=ARTICLE_BODY_FETCH_TIMEOUT)
            ) as resp:
                if resp.status != 200:
                    return
                html = await resp.text()
        body = await asyncio.to_thread(_extract_body, html)
        if body:
            article["body"] = body
    except Exception as exc:
        logger.warning("Body fetch failed for %s: %s", link, exc)


async def fetch_article_bodies(articles: list[dict], limit: int) -> None:
    """Fetch full-text bodies for the first `limit` articles, mutating them in
    place to add a `body` key. Bounded by limit, per-fetch timeout, and a
    concurrency cap. Never raises — failures leave articles with their RSS
    summary intact.
    """
    targets = articles[:limit] if limit else []
    if not targets:
        return
    sem = asyncio.Semaphore(ARTICLE_BODY_FETCH_CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=ARTICLE_BODY_FETCH_CONCURRENCY)
    try:
        async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
            await asyncio.gather(
                *[_fetch_body_one(session, a, sem) for a in targets],
                return_exceptions=True,
            )
    except Exception as exc:  # session/connector setup must never break the run
        logger.warning("fetch_article_bodies failed: %s", exc)
    got = sum(1 for a in targets if a.get("body"))
    logger.info("Fetched bodies for %d/%d articles", got, len(targets))
