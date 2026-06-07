"""Live quote fetching + portfolio P&L enrichment.

Pluggable provider (default: yfinance, no API key). Everything degrades
gracefully: if a quote can't be fetched the holding is returned with price
fields set to None, so /portfolio and the digest still work offline.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from src.config import FINNHUB_API_KEY, PRICE_CACHE_TTL_SECONDS, PRICE_PROVIDER

logger = logging.getLogger(__name__)

# Simple in-memory TTL cache: ticker -> (price, fetched_at_epoch)
_cache: dict[str, tuple[float, float]] = {}


# ---------------------------------------------------------------------------
# Providers — each maps a list of tickers to {ticker: last_price}
# ---------------------------------------------------------------------------

def _fetch_yfinance(tickers: list[str]) -> dict[str, float]:
    """Synchronous yfinance fetch (run off the event loop via asyncio.to_thread).

    Imported lazily so the module loads even when yfinance isn't installed
    (e.g. in tests, which mock this function).
    """
    import yfinance as yf

    quotes: dict[str, float] = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            price = None
            try:
                price = tk.fast_info.get("last_price")
            except Exception:
                price = None
            if price is None:  # fast_info can return empty; fall back to last close
                hist = tk.history(period="1d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            if price is not None:
                quotes[t] = float(price)
            else:
                logger.warning("yfinance: no price for %s", t)
        except Exception as exc:  # one bad ticker must not sink the batch
            logger.warning("yfinance quote failed for %s: %s", t, exc)
    return quotes


async def _fetch_finnhub(tickers: list[str]) -> dict[str, float]:
    """Finnhub /quote fetch using the aiohttp already in the dependency set."""
    if not FINNHUB_API_KEY:
        logger.warning("PRICE_PROVIDER=finnhub but FINNHUB_API_KEY is unset")
        return {}
    import aiohttp

    quotes: dict[str, float] = {}
    async with aiohttp.ClientSession() as session:
        for t in tickers:
            try:
                url = "https://finnhub.io/api/v1/quote"
                params = {"symbol": t, "token": FINNHUB_API_KEY}
                async with session.get(url, params=params,
                                       timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
                price = data.get("c")  # current price; 0 means unknown
                if price:
                    quotes[t] = float(price)
            except Exception as exc:
                logger.warning("finnhub quote failed for %s: %s", t, exc)
    return quotes


async def _fetch(tickers: list[str]) -> dict[str, float]:
    if PRICE_PROVIDER == "finnhub":
        return await _fetch_finnhub(tickers)
    # default
    return await asyncio.to_thread(_fetch_yfinance, tickers)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_quotes(tickers: list[str]) -> dict[str, float]:
    """Return {ticker: last_price} for the given tickers, using a TTL cache.

    Never raises — on provider failure the affected tickers are simply absent
    from the returned dict.
    """
    if not tickers:
        return {}
    tickers = [t.upper() for t in tickers]
    now = time.monotonic()

    fresh = {t: p for t in tickers
             if (entry := _cache.get(t)) and now - entry[1] < PRICE_CACHE_TTL_SECONDS
             for p in (entry[0],)}
    missing = [t for t in tickers if t not in fresh]

    if missing:
        try:
            fetched = await _fetch(missing)
        except Exception as exc:
            logger.warning("Quote fetch failed (%s): %s", PRICE_PROVIDER, exc)
            fetched = {}
        for t, price in fetched.items():
            _cache[t.upper()] = (price, now)
        fresh.update({t.upper(): p for t, p in fetched.items()})

    return fresh


def compute_pnl(holdings: list[dict], quotes: dict[str, float]) -> list[dict]:
    """Enrich holdings with live P&L fields from a quotes dict (pure, testable).

    Adds per holding: current_price, market_value, cost_basis, unrealized_pl,
    unrealized_return, to_target (remaining % move to target), weight
    (share of total portfolio value). Price-derived fields are None when the
    quote is missing; weight falls back to cost basis so weights still sum ~1.
    """
    enriched = []
    for h in holdings:
        e = dict(h)
        shares, cost = h["shares"], h["avg_cost"]
        target = h.get("target_price")
        cost_basis = shares * cost
        price = quotes.get(h["ticker"].upper())

        e["cost_basis"] = cost_basis
        if price is not None:
            mkt = shares * price
            e["current_price"] = price
            e["market_value"] = mkt
            e["unrealized_pl"] = mkt - cost_basis
            e["unrealized_return"] = (price - cost) / cost if cost else None
            e["to_target"] = (target - price) / price if target is not None and price else None
            e["_weight_value"] = mkt
        else:
            e["current_price"] = None
            e["market_value"] = None
            e["unrealized_pl"] = None
            e["unrealized_return"] = None
            e["to_target"] = None
            e["_weight_value"] = cost_basis
        enriched.append(e)

    total = sum(e["_weight_value"] for e in enriched)
    for e in enriched:
        e["weight"] = e.pop("_weight_value") / total if total else None
    return enriched


async def enrich_holdings(holdings: list[dict]) -> list[dict]:
    """Fetch quotes for the holdings and return them enriched with P&L fields."""
    if not holdings:
        return []
    quotes = await get_quotes([h["ticker"] for h in holdings])
    return compute_pnl(holdings, quotes)


# ---------------------------------------------------------------------------
# Forecast comparison (forecast row + current price -> status)
# ---------------------------------------------------------------------------

def compute_forecast_status(forecast: dict, current_price: float | None) -> dict:
    """Compare a logged forecast to the current price (pure, testable).

    Adds, on a copy of the forecast row:
      - gap_to_target: (target - current)/current  [the core answer; needs current]
      - progress:      (current - base)/(target - base)  [only when base_price set]
      - reached:       direction-aware (upside vs downside target)
      - age_days:      days since created_at
    All price-derived fields are None when the inputs needed are missing, so the
    feature degrades gracefully offline. NOTE: 'reached'/'progress' do NOT mean
    'priced in' — they are factual distance metrics only.
    """
    f = dict(forecast)
    target = forecast["target_price"]
    base = forecast.get("base_price")

    # Age
    try:
        created = datetime.fromisoformat(forecast["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        f["age_days"] = (datetime.now(timezone.utc) - created).days
    except (ValueError, KeyError, TypeError):
        f["age_days"] = None

    f["current_price"] = current_price

    if current_price is not None:
        f["gap_to_target"] = (target - current_price) / current_price if current_price else None
    else:
        f["gap_to_target"] = None

    if base is not None and target != base:
        # Direction implied by base→target; if no base we can't infer direction.
        f["progress"] = (
            (current_price - base) / (target - base) if current_price is not None else None
        )
    else:
        f["progress"] = None

    if current_price is None:
        f["reached"] = None
    elif base is not None and target < base:  # downside target (e.g. stop / lower)
        f["reached"] = current_price <= target
    else:  # upside (default when base unknown)
        f["reached"] = current_price >= target

    return f


async def status_for_forecasts(forecasts: list[dict]) -> list[dict]:
    """Fetch quotes for the forecasts' tickers and attach comparison status."""
    if not forecasts:
        return []
    quotes = await get_quotes([f["ticker"] for f in forecasts])
    return [compute_forecast_status(f, quotes.get(f["ticker"].upper())) for f in forecasts]
