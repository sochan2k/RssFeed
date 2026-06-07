"""Unit tests for src/prompts.py forecast injection and cache safety."""
from unittest.mock import patch

from src.prompts import (
    build_analyst_prompt,
    build_prompt,
    build_system_prompt,
)

_ARTICLES = [
    {"title": "NVDA beats earnings", "summary": "Strong guidance", "source": "test",
     "published_utc": None},
]

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

    def test_build_prompt_includes_forecast(self):
        out = build_prompt(_ARTICLES, mode="ondemand", forecasts=_FORECASTS)
        assert "FORECAST TRACKING" in out


class TestCacheSafety:
    def test_system_prompt_excludes_forecast_data(self):
        """Forecast data must never enter the system prompt (cache key)."""
        from src.prompts import _forecast_block
        with patch("src.prompts._get_watchlist", return_value={"ai_tech": ["NVDA"]}):
            sys_prompt = build_system_prompt()
        rendered = _forecast_block(_FORECASTS)
        assert rendered
        assert rendered not in sys_prompt
        assert "94% of the way" not in sys_prompt
