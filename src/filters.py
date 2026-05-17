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


def _resolve_target(target: str, watchlist: dict[str, list[str]]) -> list[str]:
    """
    Map a user-supplied target string to a list of lowercase tickers.
    Priority: exact category name → unique startswith match → raw ticker.
    """
    t = target.lower()
    if t in watchlist:
        return [tk.lower() for tk in watchlist[t]]
    # startswith match — only use if exactly one category matches
    matches = [cat for cat in watchlist if cat.startswith(t)]
    if len(matches) == 1:
        return [tk.lower() for tk in watchlist[matches[0]]]
    return [t]  # treat as raw ticker / text search


def filter_articles(
    articles: list[dict],
    target: str | None = None,
    mark_seen: bool = True,
) -> list[dict]:
    """
    3-layer filter:
      Layer 1 — heuristics: blacklist drop, watchlist score (drop score == 0)
      Layer 2a — URL hash dedup against SQLite seen_articles table
      Layer 2b — headline similarity dedup within the current batch
    mark_seen=False skips recording survivors in the seen_articles table,
    so ondemand/breaking runs don't consume articles for the scheduled digest.
    """
    # Layer 1
    after_l1 = []

    target_tickers = None
    if target:
        watchlist = db.get_watchlist()
        target_tickers = _resolve_target(target, watchlist)

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

    # Mark survivors as seen (skip for ondemand/breaking so scheduled digest isn't starved)
    if mark_seen:
        for a in accepted:
            db.mark_seen(a["link"])

    return accepted
