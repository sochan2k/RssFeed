# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest

# Run a single test file
pytest tests/test_feeds.py

# Run a specific test
pytest tests/test_filters.py::test_name

# Smoke-test the Telegram bot (sends a live message)
python -m src.telegram_bot

# Smoke-test the Gemini client (makes real API calls)
python -m src.gemini_client
```

## Environment Setup

Copy `.env.example` to `.env` and fill in the four variables:
- `GEMINI_API_KEY` — Google Gemini API key
- `TELEGRAM_BOT_TOKEN` — BotFather token
- `TELEGRAM_CHAT_IDS` — comma-separated list of recipient chat IDs
- `ADMIN_CHAT_ID` — optional; defaults to the first chat ID in the list

The SQLite database is auto-created at `data/seen_articles.db` on first run.

## Architecture

This is an async Python pipeline that fetches US financial RSS feeds, filters articles with a 3-layer heuristic + dedup system, sends them to Gemini for analysis, and delivers a formatted digest to Telegram.

### Pipeline flow

```
fetch_articles (src/feeds.py)
    ↓  async concurrent fetch of RSS_FEEDS via aiohttp + feedparser
filter_articles (src/filters.py)
    ↓  Layer 1: blacklist drop + watchlist score
    ↓  Layer 2a: URL hash dedup against SQLite
    ↓  Layer 2b: headline similarity dedup within batch
[mode == "scheduled"]
    run_filter_agent → run_analyst_agent → run_editor_agent  (src/agents.py)
[mode == "ondemand" | "breaking"]
    single generate() call with mode-specific prompt  (src/pipeline.py)
    ↓
send_digest (src/telegram_bot.py)  — caller's responsibility
```

### Key design decisions

**Three pipeline modes** (`src/pipeline.py:run`):
- `scheduled` — 3-agent chain (Filter → Analyst → Editor) for maximum quality
- `ondemand` — single Gemini call, compact digest (triggered by `/summary` bot command)
- `breaking` — single Gemini call, last 2 hours only (triggered by `/breaking`)

**Gemini model fallback** (`src/config.py:GEMINI_MODELS`, `src/gemini_client.py`): Models are tried in order; on `429`/`500`/`503` the next model in the list is used. The context cache is cleared between model attempts since caches are model-specific.

**Context caching** (`src/gemini_client.py:generate`): When `use_cache=True`, the system prompt is cached in Gemini's context cache on first call and reused. The cache key is a SHA-256 prefix of the system prompt. The filter agent explicitly sets `use_cache=False` because it expects structured JSON output and the model may differ per call.

**Dedup persistence** (`src/db.py`): Two SQLite tables — `seen_articles` (URL hashes, 90-day retention) and `run_log` (pipeline run history). `db.init_db()` and `db.cleanup_old()` are called at the start of every pipeline run.

**Telegram delivery** (`src/telegram_bot.py`): Digests use `ParseMode.HTML`; status/alert messages use `ParseMode.MARKDOWN_V2` (with `escape_md()`). Messages exceeding 4096 characters are split on paragraph boundaries by `_split()`. System metrics (`/health`) read from Linux `/proc` and `/sys` paths — returns `n/a` on non-Linux.

### Module responsibilities

| Module | Responsibility |
|--------|---------------|
| `src/config.py` | All tuneable constants: watchlist tickers, RSS URLs, thresholds, model list |
| `src/feeds.py` | Async RSS fetch with retry (tenacity), HTML stripping, age filtering |
| `src/filters.py` | 3-layer article filtering (heuristics + dedup) |
| `src/db.py` | SQLite: seen-article dedup and run logging |
| `src/gemini_client.py` | Gemini API calls with model fallback and context caching |
| `src/prompts.py` | All prompt templates and builder functions for all modes and agents |
| `src/agents.py` | 3-agent orchestration: Filter → Analyst → Editor |
| `src/pipeline.py` | Top-level `run()` function wiring all stages together |
| `src/telegram_bot.py` | Bot command handlers, `send_digest`, `send_message`, `send_alert` |

### Adding a new Telegram command

1. Write an `async def cmd_<name>(update, context)` handler in `src/telegram_bot.py`
2. Register it with `app.add_handler(CommandHandler("<name>", cmd_<name>))` in `run_bot()`
3. Add a `BotCommand` entry in the `set_my_commands` call

### Modifying article filtering

- Keyword lists (`WATCHLIST`, `MACRO_TERMS`, `BLACKLIST_KEYWORDS`) live in `src/config.py`
- The heuristic score threshold is `AI_RELEVANCE_SCORE_THRESHOLD` (default 7/10)
- Headline similarity threshold is `HEADLINE_SIMILARITY_THRESHOLD` (default 0.80)
