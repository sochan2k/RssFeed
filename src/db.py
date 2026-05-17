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
    conn = sqlite3.connect(DB_PATH)
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
