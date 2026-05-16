# Daily US Stock News Summarizer

**Architecture & Implementation Plan**

This document outlines the architecture for building a daily US stock news summarizer using a Raspberry Pi Zero 2 W, the Gemini API, and Telegram. This system mimics modern AI-driven financial digests by extracting signal from noise to deliver high-quality, actionable insights.

## 1. The Architecture
The workflow is a linear pipeline designed to run on a schedule:
1. **Fetch:** A Python script uses an RSS library to download the latest US stock news from targeted feeds.
2. **Filter:** Local heuristics, URL-hash deduplication, and a watchlist pre-filter reduce articles before any AI call.
3. **Process:** The script aggregates the text and sends a prompt to the **Gemini API** asking it to summarize the news, identify key market drivers, and format it nicely.
4. **Deliver:** The script takes the Gemini response and sends it to your phone via a **Telegram Bot**.
5. **Automate:** The Raspberry Pi's `systemd` timer (preferred over raw cron) runs the script automatically on US trading days at a preferred time mapped to Thai time (ICT, UTC+7).

## 2. Hardware & OS Setup (Raspberry Pi Zero 2 W)
The Pi Zero 2 W is perfectly suited for this, as the heavy lifting (AI inference) is handled by Google's servers.
* **OS:** Install **Raspberry Pi OS Lite** (no desktop environment). Using the command line saves memory and CPU.
* **Environment:** Ensure Python 3 is installed. Create a virtual environment (`venv`) to isolate project dependencies.

### SD Card Wear Protection
SD cards fail from repeated writes. Keep logs and scratch files in RAM:
```bash
# Add to /etc/fstab
tmpfs /tmp      tmpfs defaults,noatime,size=64M 0 0
tmpfs /var/log  tmpfs defaults,noatime,size=32M 0 0
```
Install `log2ram` to buffer any persistent logs in RAM and sync to SD periodically, not on every write.

## 3. Software Components & Libraries (Python)

### A. RSS Feed Parsing (`feedparser` + `aiohttp`)
Instead of fragile web scraping, utilize RSS feeds from reliable financial news sources.
* **Sources:** Use a free RSS provider such as Yahoo Finance RSS, Google News RSS, or specific stock ticker feeds.
* **Implementation:** Use `asyncio` + `aiohttp` to fetch all feeds concurrently. Extract the `title`, `summary`, `link`, and `published` for articles within the last 24 hours.

### B. Watchlist Pre-Filter
Before any AI call, filter and prioritize articles by user-defined tickers and macroeconomic terms. This reduces token usage and makes output personally relevant.
```python
WATCHLIST = ["AAPL", "NVDA", "TSMC", "MSFT"]  # user-configurable
MACRO_TERMS = ["CPI", "Fed", "interest rate", "GDP", "inflation"]

def watchlist_score(article: dict) -> int:
    text = f"{article['title']} {article['summary']}".upper()
    score = sum(1 for t in WATCHLIST if t in text)
    score += sum(1 for t in MACRO_TERMS if t.upper() in text)
    return score
```

### C. AI Summarization (`google-genai` / Gemini API)
* **Action:** Combine the filtered headlines and summaries into a single text block and send it to the Gemini API.
* **The Prompt Example:** *"You are an expert financial analyst. Read the following recent US stock market news headlines and summaries. Provide a concise, professional daily briefing. Include: 1. The overall market sentiment (Bullish/Bearish/Mixed). 2. Top 3 macroeconomic drivers today. 3. Key company-specific news (mention tickers). Format this clearly using bullet points and bold text for easy reading on a mobile device."*
* **Model Choice:** Implement a model with fallback as follows:
  # Fallback chain: primary → cheaper/higher-RPM → stable older model
  ```python
  GEMINI_MODELS: list[str] = [
      "gemini-3.1-flash-lite",
      "gemini-2.5-flash",       
      "gemini-2.5-flash-lite",
      "gemma-4-31b-it",  
      "gemini-3.0-flash",       
  ]
  ```
* **Context Caching:** The system prompt is identical on every run. Use Gemini's context caching API to cache it — this significantly cuts token cost for repeated daily calls.

### D. Telegram Delivery (`python-telegram-bot`)
Telegram is ideal because creating a bot is completely free and instantaneous.
* **Setup:** Interact with the `BotFather` on Telegram to create a bot and obtain an API token. Identify your personal Chat ID.
* **Implementation:** Once the Gemini API returns the formatted summary, use `python-telegram-bot` to send MarkdownV2-formatted messages. Support a list of `CHAT_IDS` for multi-recipient delivery.
* **Interactive Commands:**
  * `/summary` — trigger an on-demand digest (uses 1-agent path for speed, see Section 5)
  * `/status` — check last run time and success/failure
  * `/health` — return live Pi metrics:
    ```
    CPU temp: 48°C
    Free RAM: 187MB / 512MB
    Last run: 2026-05-16 20:00 ICT ✓
    Last error: None
    Uptime: 14d 3h
    ```
  * `/breaking` — fetch and summarize only the last 2 hours of news

## 4. Secrets Handling
Never store API keys in source code. Use `systemd`'s `LoadCredential=` directive:
```ini
# In your .service file
LoadCredential=gemini_key:/etc/credentials/gemini
LoadCredential=telegram_key:/etc/credentials/telegram
```
Access in Python via `$CREDENTIALS_DIRECTORY/gemini_key`. At minimum, load from a `.env` file excluded from version control via `.gitignore`.

## 5. Implementation Steps Roadmap

1. **Test the APIs Locally (Windows):** Write the initial Python script locally. Set up the Telegram Bot and ensure the Gemini API key is functioning.
2. **Build the RSS Scraper:** Write an async function to ingest 3-4 reliable financial RSS feeds, filtering out articles older than 24 hours.
3. **Integrate Gemini:** Develop the prompt logic, set up context caching for the system prompt, and pass filtered RSS data to Gemini. Fine-tune the prompt for the desired output format.
4. **Push to Raspberry Pi:** Transfer the tested Python script to the Pi Zero 2 W via SSH.
5. **Configure systemd:** Create a `.service` + `.timer` unit (preferred over raw crontab) to execute the script every US trading weekday at the correct ICT times.

## 6. Scheduling — Thai Time (ICT, UTC+7)

US markets are **closed on weekends and US federal holidays**. Add a guard at script startup:
```python
import datetime, holidays

US_HOLIDAYS = holidays.US()

def is_trading_day() -> bool:
    today = datetime.date.today()
    return today.weekday() < 5 and today not in US_HOLIDAYS
```

**systemd timer schedule (ICT = UTC+7):**
| Run | ICT Time | Purpose |
|---|---|---|
| Pre-market digest | ~8:00 PM ICT | Before US market open |
| Post-market wrap | ~5:00 AM ICT | After US market close |

## 7. Advanced Ideas & System Upgrades

* **Asyncio Feed Fetching:** `asyncio` + `aiohttp` fetch multiple RSS feeds concurrently.
* **SQLite Historical Database:** Store processed article IDs and past summaries locally.
  * *Retention Policy:* Keep the last 90 days, auto-delete older entries to stay under ~10MB.
  * *Sentiment Trend Tracking:* Store daily sentiment (Bullish/Bearish/Mixed) in SQLite to chart market mood over time.
* **Robust Reliability:** Wrap the script in a `systemd` service with a `Restart=on-failure` watchdog. Use `tenacity` for per-request exponential backoff on all outbound HTTP calls — the Pi Zero 2 W's 2.4GHz-only WiFi is congestion-prone.
* **OS Optimizations:** Enable `zram` (compressed RAM swap) to prevent OOM errors on the 512MB device.
* **"Vanilla" Multi-Agent Pipeline:** Implement without heavy frameworks (no LangChain/CrewAI) to save RAM. Two execution paths:
  * *Scheduled digest (full quality):* Filter Agent → Analyst Agent → Editor Agent (3 sequential Gemini calls)
  * *On-demand `/summary` (fast):* Combined single Gemini call with all instructions in one prompt (1 API call, 3× faster)

## 8. Strict Noise Reduction Strategy
Financial news feeds are notoriously noisy. The pipeline implements a **3-Layer Filter**:

1. **Layer 1: Local Heuristics (Pre-processing)**
   * *Blacklist:* Drop articles containing keywords like "opinion", "zodiac", "sponsored", "rumor", or "gossip".
   * *Whitelist:* Prioritize articles containing known stock tickers or macroeconomic terms.

2. **Layer 2: Two-Step Deduplication**
   * *Step 1 — URL hash (O(1)):* Store seen article URLs as SHA-256 hashes in SQLite. Skip any article whose URL hash already exists. This catches exact reposts instantly.
   * *Step 2 — Headline similarity (O(n) on remainder):* Only run `SequenceMatcher` on articles that passed Step 1. If two headlines are 80%+ similar, discard the duplicate. This avoids the O(n²) cost of comparing every headline against every other.

3. **Layer 3: AI Filter Agent (The Bouncer)**
   * Instruct the Gemini Filter Agent: *"Score this news item from 1-10 on its direct market-moving impact. If the score is below 7, return 'DISCARD'. Do not process opinions or vague predictions."*
