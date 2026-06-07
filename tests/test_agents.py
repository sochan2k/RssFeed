"""Unit tests for src/agents.py run_target_extractor (analyst price-target parsing)."""
from unittest.mock import AsyncMock, patch

import pytest

from src import agents

_ARTICLES = [
    {"title": "Morgan Stanley raises NVDA target to $200", "summary": "PT hike",
     "source": "test", "published_utc": None},
]


@pytest.mark.asyncio
class TestTargetExtractor:
    async def test_parses_targets(self):
        raw = '[{"ticker": "nvda", "target": 200, "firm": "Morgan Stanley"}]'
        with patch("src.agents.generate", AsyncMock(return_value=raw)):
            out = await agents.run_target_extractor(_ARTICLES)
        assert out == [{"ticker": "NVDA", "target": 200.0, "firm": "Morgan Stanley"}]

    async def test_empty_array_when_no_target(self):
        with patch("src.agents.generate", AsyncMock(return_value="[]")):
            assert await agents.run_target_extractor(_ARTICLES) == []

    async def test_parse_error_returns_empty(self):
        with patch("src.agents.generate", AsyncMock(return_value="not json")):
            assert await agents.run_target_extractor(_ARTICLES) == []

    async def test_skips_malformed_items(self):
        raw = '[{"ticker": "NVDA", "target": 200}, {"ticker": "", "target": 5}, {"foo": 1}]'
        with patch("src.agents.generate", AsyncMock(return_value=raw)):
            out = await agents.run_target_extractor(_ARTICLES)
        assert out == [{"ticker": "NVDA", "target": 200.0, "firm": ""}]

    async def test_no_articles_no_call(self):
        gen = AsyncMock()
        with patch("src.agents.generate", gen):
            assert await agents.run_target_extractor([]) == []
        gen.assert_not_awaited()
