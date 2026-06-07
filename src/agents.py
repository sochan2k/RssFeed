import json
import logging

from src.config import (
    AI_RELEVANCE_SCORE_THRESHOLD,
    GEMINI_TEMPERATURE_ANALYSIS,
    GEMINI_TEMPERATURE_FILTER,
)
from src.gemini_client import generate
from src.prompts import (
    ANALYST_AGENT_SYSTEM,
    TARGET_EXTRACTOR_SYSTEM,
    build_analyst_prompt,
    build_editor_prompt,
    build_editor_system,
    build_filter_prompt,
    build_filter_system,
    build_target_extractor_prompt,
)

logger = logging.getLogger(__name__)


async def run_filter_agent(articles: list[dict]) -> list[dict]:
    """
    Ask Gemini to score each article 1-10 on market-moving impact.
    Returns articles whose score meets AI_RELEVANCE_SCORE_THRESHOLD.
    Falls back to passing all articles through if the response cannot be parsed.
    """
    if not articles:
        return []

    prompt = build_filter_prompt(articles)
    raw = await generate(
        prompt,
        system_prompt=build_filter_system(),
        use_cache=False,
        response_mime_type="application/json",
        temperature=GEMINI_TEMPERATURE_FILTER,
    )

    try:
        scores: list[dict] = json.loads(raw)
        high_impact = [
            articles[idx]
            for item in scores
            if isinstance(item, dict)
            and isinstance((idx := item.get("index")), int)
            and isinstance(item.get("score"), (int, float))
            and item["score"] >= AI_RELEVANCE_SCORE_THRESHOLD
            and 0 <= idx < len(articles)
        ]
        logger.info(
            "Filter agent: %d → %d articles (threshold=%d)",
            len(articles), len(high_impact), AI_RELEVANCE_SCORE_THRESHOLD,
        )
        return high_impact if high_impact else articles
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Filter agent parse error (%s) — passing all articles through", exc)
        return articles


async def run_target_extractor(articles: list[dict]) -> list[dict]:
    """Extract explicit analyst price targets from articles.

    Returns a list of {"ticker","target","firm"}. Returns [] on parse error or
    when no explicit target is stated (the prompt enforces no-invention). Mirrors
    run_filter_agent: JSON output, low temperature, no cache.
    """
    if not articles:
        return []
    prompt = build_target_extractor_prompt(articles)
    raw = await generate(
        prompt,
        system_prompt=TARGET_EXTRACTOR_SYSTEM,
        use_cache=False,
        response_mime_type="application/json",
        temperature=GEMINI_TEMPERATURE_FILTER,
    )
    try:
        items = json.loads(raw)
        out = [
            {"ticker": str(it["ticker"]).upper(),
             "target": float(it["target"]),
             "firm": str(it.get("firm", "")).strip()}
            for it in items
            if isinstance(it, dict)
            and it.get("ticker")
            and isinstance(it.get("target"), (int, float))
        ]
        logger.info("Target extractor: %d articles → %d targets", len(articles), len(out))
        return out
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Target extractor parse error (%s) — skipping", exc)
        return []


async def run_analyst_agent(
    articles: list[dict],
    forecasts: list[dict] | None = None,
) -> str:
    """Generate structured plain-text market analysis from high-impact articles."""
    prompt = build_analyst_prompt(articles, forecasts=forecasts)
    return await generate(
        prompt,
        system_prompt=ANALYST_AGENT_SYSTEM,
        use_cache=False,
        temperature=GEMINI_TEMPERATURE_ANALYSIS,
    )


async def run_editor_agent(analysis: str, history: list[dict] | None = None) -> str:
    """Polish raw analysis into final Telegram HTML."""
    prompt = build_editor_prompt(analysis, history=history)
    return await generate(
        prompt,
        system_prompt=build_editor_system(),
        use_cache=True,
        temperature=GEMINI_TEMPERATURE_ANALYSIS,
    )
