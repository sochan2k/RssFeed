import logging

from src import db
from src.agents import run_analyst_agent, run_editor_agent, run_filter_agent
from src.feeds import fetch_articles
from src.filters import filter_articles
from src.gemini_client import generate
from src.prompts import build_prompt, build_system_prompt

logger = logging.getLogger(__name__)


async def _run_agent_chain(articles: list[dict]) -> str:
    """
    3-agent scheduled digest path:
      Filter Agent  → score & prune to high-impact articles
      Analyst Agent → generate structured plain-text analysis
      Editor Agent  → reformat into Telegram HTML
    """
    logger.info("Agent chain: starting filter agent (%d articles)", len(articles))
    high_impact = await run_filter_agent(articles)

    logger.info("Agent chain: starting analyst agent (%d articles)", len(high_impact))
    analysis = await run_analyst_agent(high_impact)

    logger.info("Agent chain: starting editor agent")
    return await run_editor_agent(analysis)


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
        msg = "No articles fetched — check RSS feeds or network."
        db.log_run(success=False, articles_fetched=0, articles_sent=0, error=msg)
        return msg

    filtered = filter_articles(articles, target=target, mark_seen=(mode == "scheduled"))

    if not filtered:
        msg = "No significant market news today — all articles filtered out."
        if target:
            msg = f"No significant news found today for '{target}'."
        db.log_run(success=True, articles_fetched=len(articles), articles_sent=0)
        return msg

    try:
        if mode == "scheduled":
            summary = await _run_agent_chain(filtered)
        else:
            prompt = build_prompt(filtered, mode=mode, hours_back=hours_back, target=target)
            summary = await generate(prompt, system_prompt=build_system_prompt(), use_cache=True)
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
