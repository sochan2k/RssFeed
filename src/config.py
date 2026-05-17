import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}  (copy .env.example → .env and fill it in)")
    return val


# --- API Keys ---
GEMINI_API_KEY: str = _require("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")

_raw_ids = _require("TELEGRAM_CHAT_IDS")
try:
    TELEGRAM_CHAT_IDS: list[int] = [int(x.strip()) for x in _raw_ids.split(",") if x.strip()]
except ValueError as e:
    raise RuntimeError(f"TELEGRAM_CHAT_IDS must be comma-separated integers, got: {_raw_ids!r}") from e
if not TELEGRAM_CHAT_IDS:
    raise RuntimeError("TELEGRAM_CHAT_IDS is empty — provide at least one chat ID")

ADMIN_CHAT_ID: int = int(os.environ.get("ADMIN_CHAT_ID", TELEGRAM_CHAT_IDS[0]))

# --- Gemini Model Fallback Chain ---
# Tried in order; falls back on ResourceExhausted / ServiceUnavailable
GEMINI_MODELS: list[str] = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemma-4-31b-it",
    "gemini-3.0-flash",
]

# --- Watchlist & Macro Terms ---
DEFAULT_WATCHLIST: dict[str, list[str]] = {
    "ai_tech": ["NVDA", "GOOG", "AAPL", "TSLA"],
    "semiconductor": ["MU", "SNDK", "LITE", "COHR", "AVGO", "INTC", "AMD", "AMAT", "LRCX", "ADI"],
    "space": ["RKLB"],
    "materials": ["LIN"]
}
MACRO_TERMS: list[str] = [
    "CPI", "Fed", "Federal Reserve", "interest rate", "GDP", "inflation",
    "unemployment", "jobs report", "FOMC", "treasury", "yield curve",
    "recession", "tariff", "trade war",
]

# --- Noise Filter ---
BLACKLIST_KEYWORDS: list[str] = [
    "opinion", "zodiac", "sponsored", "rumor", "gossip", "horoscope",
    "celebrity", "entertainment", "sports", "gaming", "crypto",
    "advertisement", "promoted",
]

# --- RSS Feeds ---
RSS_FEEDS: list[str] = [
    "https://finance.yahoo.com/news/rssindex",
    "https://news.google.com/rss/search?q=stock+market&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=US+economy+Fed+interest+rate&hl=en-US&gl=US&ceid=US:en",
    "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
]

# --- Pipeline Settings ---
ARTICLE_MAX_AGE_HOURS: int = 24
BREAKING_NEWS_HOURS: int = 2
HEADLINE_SIMILARITY_THRESHOLD: float = 0.80
AI_RELEVANCE_SCORE_THRESHOLD: int = 7
DB_RETENTION_DAYS: int = 90

# --- Paths ---
BASE_DIR: Path = Path(__file__).parent.parent
DATA_DIR: Path = BASE_DIR / "data"
DB_PATH: Path = DATA_DIR / "seen_articles.db"
