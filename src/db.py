import hashlib
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from src.config import DATA_DIR, DB_PATH, DB_RETENTION_DAYS

logger = logging.getLogger(__name__)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_articles (
                url_hash TEXT PRIMARY KEY,
                seen_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_log (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                ran_at            TEXT NOT NULL,
                success           INTEGER NOT NULL,
                articles_fetched  INTEGER,
                articles_sent     INTEGER,
                error_message     TEXT
            );
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker            TEXT PRIMARY KEY,
                category          TEXT NOT NULL,
                added_at          TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS digest_history (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                ran_at            TEXT NOT NULL,
                mode              TEXT NOT NULL,
                digest_text       TEXT NOT NULL,
                tickers_mentioned TEXT
            );
            CREATE TABLE IF NOT EXISTS forecast_history (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker        TEXT NOT NULL,
                target_price  REAL NOT NULL,
                base_price    REAL,
                source        TEXT NOT NULL,
                note          TEXT,
                created_at    TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_forecast_ticker
                ON forecast_history(ticker, created_at);
        """)
        
        # Seed watchlist if empty
        if conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 0:
            from src.config import DEFAULT_WATCHLIST
            now = datetime.now(timezone.utc).isoformat()
            for cat, tickers in DEFAULT_WATCHLIST.items():
                for t in tickers:
                    conn.execute(
                        "INSERT INTO watchlist (ticker, category, added_at) VALUES (?, ?, ?)",
                        (t.upper(), cat.lower(), now)
                    )


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_watchlist() -> dict[str, list[str]]:
    wl = {}
    with _conn() as conn:
        rows = conn.execute("SELECT ticker, category FROM watchlist ORDER BY category, ticker").fetchall()
        for row in rows:
            cat = row["category"]
            if cat not in wl:
                wl[cat] = []
            wl[cat].append(row["ticker"])
    return wl


def add_to_watchlist(category: str, ticker: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO watchlist (ticker, category, added_at) VALUES (?, ?, ?)",
            (ticker.upper(), category.lower(), now)
        )


def remove_from_watchlist(ticker: str) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Forecast history (time-stamped price targets — user-set via /forecast + analyst from news)
# ---------------------------------------------------------------------------

def add_forecast(
    ticker: str,
    target_price: float,
    base_price: float | None = None,
    source: str = "user",
    note: str | None = None,
    dedup_days: int = 7,
) -> bool:
    """Log a price forecast. Returns True if inserted, False if deduped.

    Dedup: an identical (ticker, source, target_price) logged within the last
    `dedup_days` is skipped, so repeated news coverage doesn't spam the history.
    A genuinely revised target (different number) always inserts.
    """
    ticker = ticker.upper()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=dedup_days)).isoformat()
    with _conn() as conn:
        dup = conn.execute(
            """SELECT 1 FROM forecast_history
               WHERE ticker = ? AND source = ? AND target_price = ? AND created_at >= ?
               LIMIT 1""",
            (ticker, source, target_price, cutoff),
        ).fetchone()
        if dup:
            return False
        conn.execute(
            """INSERT INTO forecast_history
               (ticker, target_price, base_price, source, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ticker, target_price, base_price, source, note, now.isoformat()),
        )
    return True


def get_forecasts(ticker: str | None = None, limit: int | None = None) -> list[dict]:
    """Return forecasts (newest first), optionally filtered to one ticker."""
    sql = "SELECT * FROM forecast_history"
    params: list = []
    if ticker:
        sql += " WHERE ticker = ?"
        params.append(ticker.upper())
    sql += " ORDER BY created_at DESC, id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    with _conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_latest_forecast(ticker: str, source: str | None = None) -> dict | None:
    """Return the most recent forecast for a ticker (optionally by source)."""
    sql = "SELECT * FROM forecast_history WHERE ticker = ?"
    params: list = [ticker.upper()]
    if source:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY created_at DESC, id DESC LIMIT 1"
    with _conn() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def is_seen(url: str) -> bool:
    h = url_hash(url)
    with _conn() as conn:
        return conn.execute(
            "SELECT 1 FROM seen_articles WHERE url_hash = ?", (h,)
        ).fetchone() is not None


def mark_seen(url: str) -> None:
    h = url_hash(url)
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_articles (url_hash, seen_at) VALUES (?, ?)",
            (h, now),
        )


def cleanup_old() -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DB_RETENTION_DAYS)).isoformat()
    with _conn() as conn:
        cur = conn.execute("DELETE FROM seen_articles WHERE seen_at < ?", (cutoff,))
        deleted = cur.rowcount
    if deleted:
        logger.info("Cleaned up %d old article hashes", deleted)
    return deleted


def log_run(
    success: bool,
    articles_fetched: int = 0,
    articles_sent: int = 0,
    error: str | None = None,
) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO run_log
               (ran_at, success, articles_fetched, articles_sent, error_message)
               VALUES (?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(), int(success),
             articles_fetched, articles_sent, error),
        )


def save_digest(mode: str, digest_text: str, tickers: list[str] | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    tickers_str = ",".join(t.upper() for t in tickers) if tickers else ""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO digest_history (ran_at, mode, digest_text, tickers_mentioned) VALUES (?, ?, ?, ?)",
            (now, mode, digest_text, tickers_str),
        )


def get_recent_digests(limit: int = 5) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM digest_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_last_run() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM run_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_recent_runs(limit: int = 5) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM run_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
