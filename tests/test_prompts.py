"""Unit tests for src/prompts.py portfolio injection and cache safety."""
from unittest.mock import patch

from src.prompts import (
    _format_holdings,
    _portfolio_block,
    build_analyst_prompt,
    build_prompt,
    build_system_prompt,
)

_HOLDINGS = [
    {"ticker": "NVDA", "shares": 10, "avg_cost": 120.0, "target_price": 200.0,
     "note": None, "expected_return": (200.0 - 120.0) / 120.0},
]

_ARTICLES = [
    {"title": "NVDA beats earnings", "summary": "Strong guidance", "source": "test",
     "published_utc": None},
]


class TestFormatHoldings:
    def test_renders_expected_return(self):
        out = _format_holdings(_HOLDINGS)
        assert "NVDA" in out
        assert "target $200" in out
        assert "+66.7%" in out


class TestUserPromptInjection:
    def test_analyst_prompt_includes_portfolio(self):
        out = build_analyst_prompt(_ARTICLES, holdings=_HOLDINGS)
        assert "YOUR PORTFOLIO" in out
        assert "NVDA" in out

    def test_analyst_prompt_no_portfolio_when_empty(self):
        assert "YOUR PORTFOLIO" not in build_analyst_prompt(_ARTICLES, holdings=None)
        assert "YOUR PORTFOLIO" not in build_analyst_prompt(_ARTICLES, holdings=[])

    def test_build_prompt_includes_portfolio(self):
        out = build_prompt(_ARTICLES, mode="ondemand", holdings=_HOLDINGS)
        assert "YOUR PORTFOLIO" in out


_FORECASTS = [
    {"ticker": "NVDA", "target_price": 200.0, "base_price": 120.0, "source": "user",
     "note": None, "current_price": 195.0, "progress": 0.94, "gap_to_target": 0.026,
     "age_days": 90, "reached": False},
]


class TestForecastInjection:
    def test_analyst_prompt_includes_forecast_block(self):
        out = build_analyst_prompt(_ARTICLES, forecasts=_FORECASTS)
        assert "FORECAST TRACKING" in out
        assert "NVDA" in out
        assert "94% of the way" in out

    def test_no_forecast_block_when_empty(self):
        assert "FORECAST TRACKING" not in build_analyst_prompt(_ARTICLES, forecasts=None)
        assert "FORECAST TRACKING" not in build_analyst_prompt(_ARTICLES, forecasts=[])


class TestCacheSafety:
    def test_system_prompt_excludes_holdings_data(self):
        """Volatile holdings DATA must never enter the system prompt (cache key).

        The stable directive may *mention* the portfolio section by name; what
        must not appear is the rendered per-position block (tickers, costs,
        expected-return numbers) that changes whenever the user edits holdings.
        """
        with patch("src.prompts._get_watchlist", return_value={"ai_tech": ["NVDA"]}):
            sys_prompt = build_system_prompt()
        rendered = _portfolio_block(_HOLDINGS)
        assert rendered  # sanity: the block is non-empty
        assert rendered not in sys_prompt
        assert "10 shares @ $120" not in sys_prompt
        assert "+66.7%" not in sys_prompt

    def test_system_prompt_excludes_forecast_data(self):
        from src.prompts import _forecast_block
        with patch("src.prompts._get_watchlist", return_value={"ai_tech": ["NVDA"]}):
            sys_prompt = build_system_prompt()
        rendered = _forecast_block(_FORECASTS)
        assert rendered
        assert rendered not in sys_prompt
        assert "94% of the way" not in sys_prompt
