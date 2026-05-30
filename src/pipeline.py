import logging

from src import db
from src.agents import run_analyst_agent, run_editor_agent, run_filter_agent
from src.config import GEMINI_TEMPERATURE_ANALYSIS
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
      Editor Agent  → reformat into Telegram HTML (with digest history injected)
    """
    history = db.get_recent_digests(limit=3)

    logger.info("Agent chain: starting filter agent (%d articles)", len(articles))
    high_impact = await run_filter_agent(articles)

    logger.info("Agent chain: starting analyst agent (%d articles)", len(high_impact))
    analysis = await run_analyst_agent(high_impact)

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
            prompt = build_prompt(filtered, mode=mode, hours_back=hours_back, target=target)
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
