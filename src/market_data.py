"""Rich per-ticker market snapshots for the analysis prompt.

Pulls price action (1d/5d/1mo change), relative volume, market cap, P/E, the
52-week range and the next earnings date so the model can explain *why* a stock
moved — not just paraphrase the headline.

Mirrors prices.py: yfinance via asyncio.to_thread, an in-memory TTL cache, and
graceful degradation. Nothing here raises — a ticker (or any single field) that
can't be fetched is simply absent, so the digest is never blocked by data gaps.
"""
import asyncio
import logging
import time
from datetime import date, datetime

from src.config import MARKET_DATA_MAX_TICKERS, MARKET_SNAPSHOT_CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)

# ticker -> (snapshot_dict, fetched_at_epoch)
_cache: dict[str, tuple[dict, float]] = {}


def _pct(now: float, then: float) -> float | None:
    """Percentage change from `then` to `now`, or None if not computable."""
    if then is None or now is None or then == 0:
        return None
    return (now - then) / then


def _earnings_in_days(cal) -> int | None:
    """Days until the next earnings date from a yfinance .calendar, or None.

    .calendar may be a dict (newer yfinance) with an 'Earnings Date' list, or a
    DataFrame (older). Be defensive — this is the flakiest field.
    """
    try:
        ed = None
        if isinstance(cal, dict):
            vals = cal.get("Earnings Date")
            if isinstance(vals, (list, tuple)) and vals:
                ed = vals[0]
            elif vals is not None:
                ed = vals
        else:  # DataFrame-like
            ed = cal.loc["Earnings Date"][0]
        if ed is None:
            return None
        if isinstance(ed, datetime):
            ed = ed.date()
        elif not isinstance(ed, date):
            ed = datetime.fromisoformat(str(ed)).date()
        return (ed - date.today()).days
    except Exception:
        return None


def _snapshot_one(ticker: str) -> dict:
    """Build one ticker's snapshot. Cheap price fields first; slow/flaky
    fundamentals (.info, .calendar) are wrapped separately so their failure
    doesn't drop the price action."""
    import yfinance as yf

    snap: dict = {"ticker": ticker.upper()}
    tk = yf.Ticker(ticker)

    # --- Price action + volume from 1mo history (one network call) ---
    try:
        hist = tk.history(period="1mo")
        if not hist.empty:
            closes = hist["Close"].dropna()
            vols = hist["Volume"].dropna()
            if len(closes):
                last = float(closes.iloc[-1])
                snap["price"] = last
                if len(closes) >= 2:
                    snap["chg_1d"] = _pct(last, float(closes.iloc[-2]))
                if len(closes) >= 6:
                    snap["chg_5d"] = _pct(last, float(closes.iloc[-6]))
                snap["chg_1mo"] = _pct(last, float(closes.iloc[0]))
            if len(vols):
                last_vol = float(vols.iloc[-1])
                avg_vol = float(vols.mean()) if vols.mean() else None
                snap["volume"] = last_vol
                if avg_vol:
                    snap["rel_volume"] = last_vol / avg_vol
    except Exception as exc:
        logger.warning("market_data: history failed for %s: %s", ticker, exc)

    # Fall back to fast_info for last price if history gave nothing.
    if "price" not in snap:
        try:
            p = tk.fast_info.get("last_price")
            if p is not None:
                snap["price"] = float(p)
        except Exception:
            pass

    # --- Fundamentals (.info is the slow, scrape-y call) ---
    try:
        info = tk.info or {}
        for key, field in (
            ("marketCap", "market_cap"),
            ("trailingPE", "pe_trailing"),
            ("forwardPE", "pe_forward"),
            ("fiftyTwoWeekHigh", "wk52_high"),
            ("fiftyTwoWeekLow", "wk52_low"),
        ):
            val = info.get(key)
            if isinstance(val, (int, float)):
                snap[field] = float(val)
    except Exception as exc:
        logger.warning("market_data: info failed for %s: %s", ticker, exc)

    # --- Next earnings date ---
    try:
        days = _earnings_in_days(tk.calendar)
        if days is not None:
            snap["earnings_in_days"] = days
    except Exception:
        pass

    return snap


def _fetch_snapshots(tickers: list[str]) -> dict[str, dict]:
    """Synchronous batch fetch (run off the event loop). One bad ticker must
    not sink the batch."""
    out: dict[str, dict] = {}
    for t in tickers:
        try:
            snap = _snapshot_one(t)
            # Only keep a snapshot that has at least a price — otherwise it's noise.
            if "price" in snap:
                out[t.upper()] = snap
            else:
                logger.warning("market_data: no usable data for %s", t)
        except Exception as exc:
            logger.warning("market_data: snapshot failed for %s: %s", t, exc)
    return out


async def get_market_snapshot(tickers: list[str]) -> dict[str, dict]:
    """Return {TICKER: snapshot} for the given tickers, using a TTL cache.

    Never raises — tickers whose data can't be fetched are simply absent.
    Input is de-duplicated, upper-cased and capped at MARKET_DATA_MAX_TICKERS.
    """
    if not tickers:
        return {}
    # De-dupe preserving order, upper-case, cap.
    seen: set[str] = set()
    ordered: list[str] = []
    for t in tickers:
        u = t.upper()
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    ordered = ordered[:MARKET_DATA_MAX_TICKERS]

    now = time.monotonic()
    fresh = {
        t: entry[0]
        for t in ordered
        if (entry := _cache.get(t)) and now - entry[1] < MARKET_SNAPSHOT_CACHE_TTL_SECONDS
    }
    missing = [t for t in ordered if t not in fresh]

    if missing:
        try:
            fetched = await asyncio.to_thread(_fetch_snapshots, missing)
        except Exception as exc:
            logger.warning("market_data: batch fetch failed: %s", exc)
            fetched = {}
        for t, snap in fetched.items():
            _cache[t.upper()] = (snap, now)
        fresh.update(fetched)

    return fresh
