# Daily US Stock News Summarizer

**Architecture & Implementation Plan**

This document outlines the architecture for building a daily US stock news summarizer using a Raspberry Pi Zero 2 W, the Gemini API, and Telegram. This system mimics modern AI-driven financial digests by extracting signal from noise to deliver high-quality, actionable insights.

## 1. The Architecture
The workflow is a linear pipeline designed to run on a schedule:
1. **Fetch:** A Python script uses an RSS library to download the latest US stock news from targeted feeds.
2. **Process:** The script aggregates the text and sends a prompt to the **Gemini API** asking it to summarize the news, identify key market drivers, and format it nicely.
3. **Deliver:** The script takes the Gemini response and sends it to your phone via a **Telegram Bot**.
4. **Automate:** The Raspberry Pi's built-in `cron` scheduler runs the script automatically at a preferred time (e.g., 7:00 AM EST).

## 2. Hardware & OS Setup (Raspberry Pi Zero 2 W)
The Pi Zero 2 W is perfectly suited for this, as the heavy lifting (AI inference) is handled by Google's servers.
* **OS:** Install **Raspberry Pi OS Lite** (no desktop environment). Using the command line saves memory and CPU.
* **Environment:** Ensure Python 3 is installed. Create a virtual environment (`venv`) to isolate project dependencies.

## 3. Software Components & Libraries (Python)

### A. RSS Feed Parsing (`feedparser`)
Instead of fragile web scraping, utilize RSS feeds from reliable financial news sources.
* **Sources:** Use a free RSS provider such as Yahoo Finance RSS, Google News RSS, or specific stock ticker feeds.
* **Implementation:** Use the `feedparser` Python library to extract the `title`, `summary`, and `link` for articles published within the last 24 hours.

### B. AI Summarization (`google-genai` / Gemini API)
* **Action:** Combine the scraped headlines and summaries into a single text block and send it to the Gemini API.
* **The Prompt Example:** *"You are an expert financial analyst. Read the following recent US stock market news headlines and summaries. Provide a concise, professional daily briefing. Include: 1. The overall market sentiment (Bullish/Bearish/Mixed). 2. Top 3 macroeconomic drivers today. 3. Key company-specific news (mention tickers). Format this clearly using bullet points and bold text for easy reading on a mobile device."*
* **Model Choice:** Implement a model with fallback as follows:
  # Fallback chain: primary → cheaper/higher-RPM → stable older model
  ```python
  GEMINI_MODELS: list[str] = [
      "gemini-3.1-flash-lite-preview",
      "gemini-2.5-flash",       
      "gemini-2.5-flash-lite",
      "gemma-4-31b-it",  
      "gemini-3.0-flash",       
  ]
  ```

### C. Telegram Delivery (`requests` or `python-telegram-bot`)
Telegram is ideal because creating a bot is completely free and instantaneous.
* **Setup:** Interact with the `BotFather` on Telegram to create a bot and obtain an API token. Identify your personal Chat ID.
* **Implementation:** Once the Gemini API returns the formatted summary, use the Python `requests` library to execute an HTTP POST to the Telegram API, sending the message directly to your device.

## 4. Implementation Steps Roadmap

1. **Test the APIs Locally (Windows):** Write the initial Python script locally. Set up the Telegram Bot and ensure the Gemini API key is functioning.
2. **Build the RSS Scraper:** Write a function to ingest 3-4 reliable financial RSS feeds, filtering out articles older than 24 hours.
3. **Integrate Gemini:** Develop the prompt logic and pass the parsed RSS data to Gemini. Fine-tune the prompt to ensure the output matches the desired format.
4. **Push to Raspberry Pi:** Transfer the tested Python script to the Pi Zero 2 W via SSH.
5. **Schedule with Cron:** Configure the `crontab` on the Pi to execute the script every weekday (e.g., at 8:00 AM Eastern Time, prior to market open).

## 5. Advanced Ideas (The "Beta Concept" Polish)
To elevate the tool into a premium experience:
* **Watchlist Filtering:** Program the script to fetch RSS feeds specific to the stocks you hold (e.g., AAPL, TSLA) and instruct Gemini to include a dedicated "Watchlist Impact" section.
* **Markdown Formatting:** Utilize Telegram's Markdown support. Instruct Gemini to use emojis (📈, 📉) and bold text to enhance readability on mobile devices.
* **Error Handling:** Implement `try/except` blocks to manage edge cases (e.g., Wi-Fi loss, RSS feed downtime). Have the system send a brief "Data fetch failed today" Telegram message instead of failing silently.
