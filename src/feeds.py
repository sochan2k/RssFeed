import asyncio
import calendar
import logging
import re
from datetime import datetime, timezone, timedelta

import aiohttp
import feedparser
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import ARTICLE_MAX_AGE_HOURS, RSS_FEEDS

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
