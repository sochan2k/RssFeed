import logging
from difflib import SequenceMatcher

from src.config import (
    BLACKLIST_KEYWORDS,
    HEADLINE_SIMILARITY_THRESHOLD,
    MACRO_TERMS,
)
from src import db

logger = logging.getLogger(__name__)


def _watchlist_score(article: dict) -> int:
    watchlist = db.get_watchlist()
    all_tickers = [t for group in watchlist.values() for t in group]
    
    text = f"{article['title']} {article['summary']}".upper()
    score = sum(1 for t in all_tickers if t.upper() in text)
    score += sum(1 for t in MACRO_TERMS if t.upper() in text)
    return score


def _is_blacklisted(article: dict) -> bool:
    text = f"{article['title']} {article['summary']}".lower()
    return any(kw.lower() in text for kw in BLACKLIST_KEYWORDS)


def _similar(a: str, b: str) -> bool:
    ratio = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return ratio >= HEADLINE_SIMILARITY_THRESHOLD


def filter_articles(articles: list[dict], target: str | None = None) -> list[dict]:
    """
    3-layer filter:
      Layer 1 — heuristics: blacklist drop, watchlist score (drop score == 0)
      Layer 2a — URL hash dedup against SQLite seen_articles table
      Layer 2b — headline similarity dedup within the current batch
    Returns the survivors, also marking them as seen in the DB.
    """
    # Layer 1
    after_l1 = []
    
    target_tickers = None
    if target:
        target = target.lower()
        watchlist = db.get_watchlist()
        if target in watchlist:
            target_tickers = [t.lower() for t in watchlist[target]]
        else:
            target_tickers = [target]

    for a in articles:
        if target_tickers:
            text = f"{a['title']} {a['summary']}".lower()
            if not any(t in text for t in target_tickers):
                continue
        else:
            if _is_blacklisted(a):
                continue
            if _watchlist_score(a) == 0:
                continue
        after_l1.append(a)
    logger.info("Layer 1 (heuristics): %d → %d", len(articles), len(after_l1))

    # Layer 2a — URL hash dedup
    after_l2a = [a for a in after_l1 if not db.is_seen(a["link"])]
    logger.info("Layer 2a (url dedup): %d → %d", len(after_l1), len(after_l2a))

    # Layer 2b — headline similarity within batch
    accepted: list[dict] = []
    for candidate in after_l2a:
        if any(_similar(candidate["title"], seen["title"]) for seen in accepted):
            continue
        accepted.append(candidate)
    logger.info("Layer 2b (similarity): %d → %d", len(after_l2a), len(accepted))

    # Mark survivors as seen
    for a in accepted:
        db.mark_seen(a["link"])

    return accepted
