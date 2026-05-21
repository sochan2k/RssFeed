import json
import logging

from src.config import AI_RELEVANCE_SCORE_THRESHOLD
from src.gemini_client import generate
from src.prompts import (
    ANALYST_AGENT_SYSTEM,
    build_analyst_prompt,
    build_editor_prompt,
    build_editor_system,
    build_filter_prompt,
    build_filter_system,
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


async def run_analyst_agent(articles: list[dict]) -> str:
    """Generate structured plain-text market analysis from high-impact articles."""
    prompt = build_analyst_prompt(articles)
    return await generate(prompt, system_prompt=ANALYST_AGENT_SYSTEM, use_cache=False)


async def run_editor_agent(analysis: str, history: list[dict] | None = None) -> str:
    """Polish raw analysis into final Telegram HTML."""
    prompt = build_editor_prompt(analysis, history=history)
    return await generate(prompt, system_prompt=build_editor_system(), use_cache=True)
