import logging
import re

from src import db
from src.agents import (
    run_analyst_agent,
    run_editor_agent,
    run_filter_agent,
    run_target_extractor,
)
from src.config import (
    ARTICLE_BODY_TOP_K,
    ENABLE_ARTICLE_BODY,
    GEMINI_TEMPERATURE_ANALYSIS,
)
from src.feeds import fetch_article_bodies, fetch_articles
from src.filters import filter_articles
from src.gemini_client import generate
from src.market_data import get_market_snapshot
from src.prices import get_quotes, status_for_forecasts
from src.prompts import build_prompt, build_system_prompt

logger = logging.getLogger(__name__)


def _relevant_tickers(articles: list[dict]) -> list[str]:
    """Watchlist tickers mentioned in the given articles (word-boundary match on
    title + summary + body), most-frequent first. Bounds market-data fetching to
    symbols people actually wrote about today."""
    watchlist = db.get_watchlist()
    all_tickers = sorted({t for group in watchlist.values() for t in group})
    counts: dict[str, int] = {}
    for a in articles:
        text = f"{a.get('title', '')} {a.get('summary', '')} {a.get('body', '')}".upper()
        for t in all_tickers:
            if re.search(r"\b" + re.escape(t) + r"\b", text):
                counts[t] = counts.get(t, 0) + 1
    return sorted(counts, key=lambda t: counts[t], reverse=True)


async def _enrich(articles: list[dict], top_k: int) -> dict[str, dict]:
    """Attach full-text bodies (in place) to the top-k articles and return live
    market snapshots for the watchlist tickers they mention.

    Bodies are fetched first so their text feeds ticker detection. Never raises —
    on any failure the digest proceeds with whatever data was gathered.
    """
    try:
        if ENABLE_ARTICLE_BODY and top_k:
            await fetch_article_bodies(articles, limit=top_k)
    except Exception as exc:
        logger.warning("Article body enrichment failed: %s", exc)
    try:
        tickers = _relevant_tickers(articles)
        return await get_market_snapshot(tickers) if tickers else {}
    except Exception as exc:
        logger.warning("Market snapshot enrichment failed: %s", exc)
        return {}


async def _current_forecasts() -> list[dict]:
    """Latest tracked forecast per ticker, enriched with live price comparison.

    Shared by all modes so on-demand digests get the same forecast context the
    scheduled chain has. Never raises — returns [] on any failure."""
    try:
        all_forecasts = db.get_forecasts(limit=20)
        latest_by_ticker: dict[str, dict] = {}
        for fc in all_forecasts:
            latest_by_ticker.setdefault(fc["ticker"], fc)
        if not latest_by_ticker:
            return []
        return await status_for_forecasts(list(latest_by_ticker.values()))
    except Exception as exc:
        logger.warning("Forecast context build failed: %s", exc)
        return []


async def _run_agent_chain(articles: list[dict]) -> str:
    """
    3-agent scheduled digest path:
      Filter Agent  → score & prune to high-impact articles
      Analyst Agent → generate structured plain-text analysis
      Editor Agent  → reformat into Telegram HTML (with digest history injected)
    """
    history = db.get_recent_digests(limit=3)

    logger.info("Agent chain: starting filter agent (%d articles)", len(articles))
    high_impact = await run_filter_agent(articles)

    # Enrich the surviving stories with full-text bodies + live market snapshots.
    market = await _enrich(high_impact, top_k=ARTICLE_BODY_TOP_K)

    # Extract & log analyst price targets from today's news (scheduled only).
    try:
        targets = await run_target_extractor(high_impact)
        if targets:
            tq = await get_quotes([t["ticker"] for t in targets])
            for t in targets:
                db.add_forecast(
                    t["ticker"], t["target"],
                    base_price=tq.get(t["ticker"].upper()),
                    source="analyst", note=(t.get("firm") or None),
                )
    except Exception as exc:  # extraction must never break the digest
        logger.warning("Target extraction failed: %s", exc)

    # Build forecast context: compare tracked forecasts to today's prices.
    forecasts = await _current_forecasts()

    logger.info("Agent chain: starting analyst agent (%d articles)", len(high_impact))
    analysis = await run_analyst_agent(high_impact, forecasts=forecasts, market=market)

    logger.info("Agent chain: starting editor agent (history=%d)", len(history))
    return await run_editor_agent(analysis, history=history)


async def run(
    mode: str = "scheduled",
    hours_back: int | None = None,
    target: str | None = None,
) -> str:
    """
    Full pipeline: fetch → filter → summarise.
    Returns the summary text; the caller is responsible for delivery.

    mode: "scheduled" | "ondemand" | "breaking"
      scheduled — 3-agent chain (Filter → Analyst → Editor) for maximum quality
      ondemand  — single Gemini call, compact digest
      breaking  — single Gemini call, last N hours only
    hours_back: override article age window (used by breaking mode)
    """
    db.init_db()
    db.cleanup_old()

    articles = await fetch_articles(hours_back=hours_back)

    if not articles:
        msg = "ไม่พบข่าวจากฟีด — โปรดตรวจสอบ RSS feeds หรือการเชื่อมต่อเครือข่าย"
        db.log_run(success=False, articles_fetched=0, articles_sent=0, error=msg)
        return msg

    filtered = filter_articles(articles, target=target, mark_seen=(mode == "scheduled"))

    if not filtered:
        msg = "วันนี้ไม่มีข่าวตลาดที่มีนัยสำคัญ — บทความทั้งหมดถูกกรองออก"
        if target:
            msg = f"วันนี้ไม่พบข่าวที่มีนัยสำคัญสำหรับ '{target}'"
        db.log_run(success=True, articles_fetched=len(articles), articles_sent=0)
        return msg

    try:
        if mode == "scheduled":
            summary = await _run_agent_chain(filtered)
            db.save_digest("scheduled", summary)
        else:
            # Enrich on-demand/breaking too. Breaking uses a smaller body budget
            # to stay snappy for the user waiting on the reply.
            top_k = max(1, ARTICLE_BODY_TOP_K // 2) if mode == "breaking" else ARTICLE_BODY_TOP_K
            market = await _enrich(filtered, top_k=top_k)
            forecasts = await _current_forecasts()
            prompt = build_prompt(
                filtered, mode=mode, hours_back=hours_back, target=target,
                forecasts=forecasts, market=market,
            )
            summary = await generate(
                prompt,
                system_prompt=build_system_prompt(),
                use_cache=True,
                temperature=GEMINI_TEMPERATURE_ANALYSIS,
            )
    except Exception as exc:
        error_msg = f"Gemini error: {exc}"
        logger.error(error_msg)
        db.log_run(success=False, articles_fetched=len(articles),
                   articles_sent=len(filtered), error=error_msg)
        raise

    db.log_run(success=True, articles_fetched=len(articles), articles_sent=len(filtered))
    logger.info("Pipeline complete: fetched=%d filtered=%d mode=%s",
                len(articles), len(filtered), mode)
    return summary
