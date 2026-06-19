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

_MARKET = {
    "MSFT": {
        "ticker": "MSFT", "price": 410.0, "chg_1d": -0.042, "chg_5d": -0.07,
        "chg_1mo": 0.03, "rel_volume": 1.9, "market_cap": 3.05e12,
        "pe_trailing": 34.0, "pe_forward": 31.0, "wk52_high": 470.0,
        "wk52_low": 360.0, "earnings_in_days": 3,
    },
}


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


class TestMarketInjection:
    def test_analyst_prompt_includes_market_block(self):
        out = build_analyst_prompt(_ARTICLES, market=_MARKET)
        assert "MARKET DATA" in out
        assert "MSFT" in out
        assert "-4.2% 1d" in out
        assert "1.9× avg" in out
        assert "P/E 34x fwd 31x" in out
        assert "earnings in 3d" in out

    def test_no_market_block_when_empty(self):
        assert "MARKET DATA" not in build_analyst_prompt(_ARTICLES, market=None)
        assert "MARKET DATA" not in build_analyst_prompt(_ARTICLES, market={})

    def test_build_prompt_includes_market_all_modes(self):
        for mode in ("scheduled", "ondemand", "breaking"):
            out = build_prompt(_ARTICLES, mode=mode, market=_MARKET)
            assert "MARKET DATA" in out, mode

    def test_article_body_rendered_when_present(self):
        arts = [{"title": "MSFT slips", "summary": "shares fall", "source": "t",
                 "published_utc": None, "body": "Azure grew 31%, below the 33% expected."}]
        out = build_analyst_prompt(arts)
        assert "FULL TEXT:" in out
        assert "Azure grew 31%" in out


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

    def test_system_prompt_excludes_market_data(self):
        """Live market data must never enter the system prompt (cache key)."""
        from src.prompts import _market_block
        with patch("src.prompts._get_watchlist", return_value={"ai_tech": ["MSFT"]}):
            sys_prompt = build_system_prompt()
        rendered = _market_block(_MARKET)
        assert rendered
        assert rendered not in sys_prompt
        assert "-4.2% 1d" not in sys_prompt
