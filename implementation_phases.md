# Implementation Phases — Daily US Stock News Summarizer

## Overview

Four sequential phases, each producing a runnable/testable artifact before the next begins.
All Phase 1–2 work runs on **Windows** (local dev). Phase 3–4 targets the **Raspberry Pi Zero 2 W**.

---

## Phase 1 — Foundation & API Validation (Local, Windows)

**Goal:** Prove all external dependencies work before writing business logic.

### 1.1 Project Scaffold
```
RssFeed/
├── src/
│   ├── __init__.py
│   ├── config.py          # constants, watchlist, model list
│   ├── feeds.py           # RSS fetch & parse
│   ├── filters.py         # heuristics, deduplication, scoring
│   ├── gemini_client.py   # API wrapper + fallback chain
│   └── telegram_bot.py    # delivery + command handlers
├── data/
│   └── seen_articles.db   # SQLite (git-ignored)
├── .env.example
├── .gitignore
├── requirements.txt
└── main.py
```

Tasks:
- [ ] `python -m venv .venv` and `pip install feedparser aiohttp google-genai python-telegram-bot tenacity holidays`
- [ ] Create `.env` with `GEMINI_API_KEY` and `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_IDS`
- [ ] Write `config.py` — `WATCHLIST`, `MACRO_TERMS`, `GEMINI_MODELS` fallback list, `BLACKLIST_KEYWORDS`

### 1.2 Telegram Bot Smoke Test
- [ ] Register bot via BotFather, record token and personal Chat ID
- [ ] Write `telegram_bot.py` — `send_message(text)` helper (MarkdownV2)
- [ ] Script sends "Bot is alive" to verify delivery end-to-end

### 1.3 Gemini API Smoke Test
- [ ] Write `gemini_client.py` — `generate(prompt)` that iterates `GEMINI_MODELS` on `ResourceExhausted`/`ServiceUnavailable`
- [ ] Hardcode a test prompt ("Summarize: Apple stock rose 3%") and print the response
- [ ] Confirm context caching API call works for a static system prompt

**Exit criteria:** Telegram message received on phone. Gemini response printed to console.

---

## Phase 2 — Core Pipeline (Local, Windows)

**Goal:** Full end-to-end pipeline running locally, no Pi required.

### 2.1 RSS Feed Fetcher (`feeds.py`)
- [ ] Async fetch of 3–4 feeds with `aiohttp` + `feedparser`:
  - Yahoo Finance: `https://finance.yahoo.com/news/rssindex`
  - Google News (markets): `https://news.google.com/rss/search?q=stock+market&hl=en-US&gl=US&ceid=US:en`
  - Reuters Business: `https://feeds.reuters.com/reuters/businessNews`
  - MarketWatch: `https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines`
- [ ] Return list of `{"title", "summary", "link", "published_utc"}` dicts
- [ ] Discard articles older than 24 hours (use `published_utc` comparison)

### 2.2 Filter Pipeline (`filters.py`)
- [ ] **Layer 1 — Heuristics:** drop articles matching `BLACKLIST_KEYWORDS`; score remaining with `watchlist_score()`; drop score == 0
- [ ] **Layer 2 — Deduplication:**
  - SQLite table `seen_articles(url_hash TEXT PRIMARY KEY, seen_at TEXT)`
  - SHA-256 URL hash check (O(1) skip)
  - `SequenceMatcher` headline similarity ≥ 0.80 check on survivors
  - Insert new hashes after passing both checks
- [ ] Retention job: delete rows older than 90 days on each run

### 2.3 Gemini Summarization (`gemini_client.py`)
- [ ] Build prompt block from filtered articles (title + summary, max ~4000 tokens input)
- [ ] Cache system prompt using Gemini context caching API
- [ ] Call `generate()` with fallback chain; return formatted summary string

### 2.4 Prompt Engineering
- [ ] Scheduled digest prompt (full quality):
  - Overall market sentiment (Bullish / Bearish / Mixed)
  - Top 3 macro drivers
  - Key company-specific news with tickers
  - MarkdownV2 formatting for Telegram mobile readability
- [ ] On-demand `/summary` prompt (single call, condensed instructions)

### 2.5 Telegram Bot Commands
- [ ] `/summary` — trigger on-demand single-call digest
- [ ] `/status` — last run time + success/failure from SQLite log table
- [ ] `/health` — CPU temp, free RAM, uptime (stubs on Windows; real values on Pi)
- [ ] `/breaking` — fetch + summarize last 2 hours only

### 2.6 `main.py` — Orchestrator
- [ ] `is_trading_day()` guard using `holidays` library
- [ ] Parse `--mode` flag: `scheduled` (full 3-agent path) vs `ondemand` (single call)
- [ ] Wire: fetch → filter → gemini → telegram

**Exit criteria:** Run `python main.py --mode scheduled` on a trading day → formatted digest arrives in Telegram.

---

## Phase 3 — Multi-Agent Pipeline & Hardening (Local, Windows)

**Goal:** Production-quality reliability before touching the Pi.

### 3.1 Multi-Agent Scheduled Path
Three sequential Gemini calls to improve quality (only for scheduled digest):
1. **Filter Agent** — score each article 1–10 on market-moving impact; discard < 7
2. **Analyst Agent** — generate structured analysis from survivors
3. **Editor Agent** — reformat and polish for Telegram MarkdownV2

Each agent call goes through the same `gemini_client.py` fallback chain.

### 3.2 Resilience
- [ ] Wrap all outbound HTTP (RSS + Gemini + Telegram) with `tenacity` exponential backoff (max 3 retries, base 2s)
- [ ] Log every run result (timestamp, articles fetched, articles sent to Gemini, success/fail) to SQLite `run_log` table
- [ ] Graceful degradation: if Gemini fails all models, send Telegram alert "Digest unavailable — API error"

### 3.3 Error Alerting
- [ ] On unhandled exception, send Telegram message with truncated traceback to `ADMIN_CHAT_ID`

### 3.4 Unit Tests
- [ ] `tests/test_filters.py` — heuristic blacklist, watchlist scoring, dedup logic
- [ ] `tests/test_feeds.py` — mock `aiohttp` responses, verify age filtering
- [ ] `tests/test_gemini_client.py` — verify fallback chain triggers on `ResourceExhausted`

**Exit criteria:** `pytest` passes. Intentionally kill primary Gemini model → confirm fallback succeeds. Force exception → confirm Telegram alert received.

---

## Phase 4 — Raspberry Pi Deployment & Automation

**Goal:** Hands-off daily operation on the Pi.

### 4.1 Pi OS Hardening
- [ ] Flash Raspberry Pi OS Lite (64-bit), enable SSH, connect to WiFi
- [ ] Add `tmpfs` entries to `/etc/fstab` for `/tmp` and `/var/log`
- [ ] Install and configure `log2ram`
- [ ] Enable `zram` swap

### 4.2 Transfer & Environment
```bash
rsync -avz --exclude '.venv' --exclude 'data/' \
  ./RssFeed/ pi@raspberrypi.local:~/stock-digest/
```
- [ ] `ssh pi@raspberrypi.local`
- [ ] `python3 -m venv .venv && pip install -r requirements.txt`
- [ ] Create `/etc/credentials/gemini` and `/etc/credentials/telegram` (chmod 600, root-owned)

### 4.3 systemd Service
`/etc/systemd/system/stock-digest.service`:
```ini
[Unit]
Description=Daily Stock News Digest
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=pi
WorkingDirectory=/home/pi/stock-digest
ExecStart=/home/pi/stock-digest/.venv/bin/python main.py --mode scheduled
LoadCredential=gemini_key:/etc/credentials/gemini
LoadCredential=telegram_key:/etc/credentials/telegram
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
```

### 4.4 systemd Timer (ICT = UTC+7)
`/etc/systemd/system/stock-digest.timer`:
```ini
[Unit]
Description=Stock Digest Timer

[Timer]
# Pre-market: 8:00 PM ICT = 13:00 UTC
OnCalendar=Mon-Fri 13:00:00 UTC
# Post-market: 5:00 AM ICT = 22:00 UTC (previous calendar day maps correctly)
OnCalendar=Mon-Fri 22:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```
- [ ] `systemctl enable --now stock-digest.timer`
- [ ] `systemctl list-timers stock-digest.timer` — verify next trigger times

### 4.5 `/health` Command — Real Pi Metrics
- [ ] Read CPU temp from `/sys/class/thermal/thermal_zone0/temp`
- [ ] Read free RAM from `/proc/meminfo`
- [ ] Read uptime from `/proc/uptime`

### 4.6 Smoke Test on Pi
- [ ] `systemctl start stock-digest.service` — manual trigger
- [ ] Check `journalctl -u stock-digest.service -f` for errors
- [ ] Confirm Telegram digest arrives

**Exit criteria:** Two consecutive scheduled digests (pre-market + post-market) delivered automatically without SSH intervention.

---

## Dependency Map

```
Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4
  APIs         Pipeline    Hardening   Pi Deploy
  work         works       + tests     automated
```

## File Checklist Summary

| File | Created in Phase |
|---|---|
| `config.py` | 1.1 |
| `.env` / `.env.example` | 1.1 |
| `requirements.txt` | 1.1 |
| `telegram_bot.py` | 1.2 |
| `gemini_client.py` | 1.3 → 2.3 |
| `feeds.py` | 2.1 |
| `filters.py` | 2.2 |
| `main.py` | 2.6 |
| `tests/` | 3.4 |
| `stock-digest.service` | 4.3 |
| `stock-digest.timer` | 4.4 |
