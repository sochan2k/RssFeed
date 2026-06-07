import asyncio
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Bot, BotCommand, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from src import strings_th as S
from src.config import (
    ADMIN_CHAT_ID,
    DIGEST_SCHEDULE_TIME,
    DIGEST_TIMEZONE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_IDS,
)

logger = logging.getLogger(__name__)

_MARKDOWN_SPECIAL = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")
_MAX_MSG_LEN = 4096


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def _split(text: str, limit: int = _MAX_MSG_LEN) -> list[str]:
    """Split text into chunks ≤ limit, preferring paragraph breaks."""
    if len(text) <= limit:
        return [text]
    chunks, buf = [], ""
    for para in text.split("\n\n"):
        block = (para + "\n\n")
        if len(buf) + len(block) > limit:
            if buf:
                chunks.append(buf.rstrip())
            buf = block
        else:
            buf += block
    if buf.strip():
        chunks.append(buf.rstrip())
    return chunks or [text[:limit]]


async def send_digest(text: str, chat_id: int | None = None) -> None:
    """Send Gemini-generated HTML-formatted digest to one or all chat IDs."""
    targets = [chat_id] if chat_id else TELEGRAM_CHAT_IDS
    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        for cid in targets:
            for chunk in _split(text):
                try:
                    await bot.send_message(
                        chat_id=cid,
                        text=chunk,
                        parse_mode=ParseMode.HTML,
                    )
                except TelegramError as exc:
                    logger.error("send_digest failed cid=%s: %s", cid, exc)


async def send_message(text: str, chat_id: int | None = None) -> None:
    """Send a plain MarkdownV2-escaped message (for alerts and status replies)."""
    targets = [chat_id] if chat_id else TELEGRAM_CHAT_IDS
    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        for cid in targets:
            try:
                await bot.send_message(
                    chat_id=cid,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except TelegramError as exc:
                logger.error("send_message failed cid=%s: %s", cid, exc)


async def send_alert(text: str) -> None:
    """Send a plain-text error alert to the admin chat only."""
    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        try:
            await bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)
        except TelegramError as exc:
            logger.error("Alert delivery failed: %s", exc)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

# Kept as a module-level name for backward compatibility (e.g. scripts/test_modes.py).
_HELP_TEXT = S.HELP_TEXT


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(S.WELCOME + _HELP_TEXT)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(_HELP_TEXT)


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually trigger a full 3-agent scheduled digest."""
    from src.pipeline import run as pipeline_run
    await update.message.reply_text(S.RUN_WAIT)
    try:
        summary = await pipeline_run(mode="scheduled")
        await update.message.reply_html(summary)
    except Exception as exc:
        logger.error("cmd_run error: %s", exc)
        await update.message.reply_text(S.error(exc))


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.pipeline import run as pipeline_run
    target = context.args[0].lower() if context.args else None

    if target:
        await update.message.reply_text(S.summary_wait_target(target))
    else:
        await update.message.reply_text(S.SUMMARY_WAIT)

    try:
        summary = await pipeline_run(mode="ondemand", target=target)
        await update.message.reply_html(summary)
    except Exception as exc:
        await update.message.reply_text(S.error(exc))


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args).strip() if context.args else ""
    if not question:
        await update.message.reply_text(S.ASK_USAGE)
        return

    await update.message.reply_text(S.ASK_WORKING)

    try:
        from src.feeds import fetch_articles
        from src.filters import filter_articles
        from src.gemini_client import generate
        from src.prompts import ASK_SYSTEM_PROMPT, build_ask_prompt

        articles = await fetch_articles()
        filtered = filter_articles(articles, mark_seen=False)
        prompt = build_ask_prompt(question, filtered)
        answer = await generate(prompt, system_prompt=ASK_SYSTEM_PROMPT, use_cache=True)
        await update.message.reply_html(answer)
    except Exception as exc:
        logger.error("cmd_ask error: %s", exc)
        await update.message.reply_text(S.error(exc))


async def cmd_breaking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.config import BREAKING_NEWS_HOURS
    from src.pipeline import run as pipeline_run
    hours = BREAKING_NEWS_HOURS
    if context.args and context.args[0].isdigit():
        requested = int(context.args[0])
        hours = min(max(requested, 1), 24)
        if hours != requested:
            await update.message.reply_text(S.breaking_clamp(hours))
    await update.message.reply_text(S.breaking_fetch(hours))
    try:
        summary = await pipeline_run(mode="breaking", hours_back=hours)
        await update.message.reply_html(summary)
    except Exception as exc:
        await update.message.reply_text(S.error(exc))


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src import db
    db.init_db()
    watchlist = db.get_watchlist()
    if not watchlist:
        await update.message.reply_text(S.WATCHLIST_EMPTY)
        return

    filter_cat = context.args[0].lower() if context.args else None
    lines = []

    for cat, tickers in sorted(watchlist.items()):
        if filter_cat and cat != filter_cat:
            continue
        label = cat.replace("_", " ").title()
        lines.append(f"<b>{label}</b> (<code>{cat}</code>): " + ", ".join(sorted(tickers)))

    if not lines:
        cats = ", ".join(f"<code>{c}</code>" for c in sorted(watchlist.keys()))
        await update.message.reply_html(S.watchlist_no_category(filter_cat, cats))
        return

    cats_hint = ", ".join(f"<code>{c}</code>" for c in sorted(watchlist.keys()))
    lines.append(S.WATCHLIST_FOOTER_HINT)
    lines.append(S.watchlist_categories(cats_hint))
    await update.message.reply_html("\n".join(lines))


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.message.reply_text(S.ADD_USAGE)
        return

    cat, ticker = context.args[0].lower(), context.args[1].upper()
    from src import db
    db.init_db()
    db.add_to_watchlist(cat, ticker)
    label = cat.replace("_", " ").title()
    await update.message.reply_html(S.add_success(ticker, label))


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await update.message.reply_text(S.REMOVE_USAGE)
        return

    ticker = context.args[0].upper()
    from src import db
    db.init_db()
    removed = db.remove_from_watchlist(ticker)
    if removed:
        await update.message.reply_text(S.remove_success(ticker))
    else:
        await update.message.reply_text(S.remove_not_found(ticker))


async def cmd_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Track price forecasts vs. today's price.

    /forecast                  → overview: latest forecast per ticker vs today
    /forecast NVDA             → full target history for NVDA vs today
    /forecast NVDA 200         → log a new user target of $200 (base = today's price)
    """
    from src import db
    from src.prices import compute_forecast_status, get_quotes, status_for_forecasts
    db.init_db()
    args = context.args or []

    # --- set form: /forecast TICKER PRICE ---
    if len(args) >= 2:
        ticker = args[0].upper()
        try:
            target = float(args[1])
        except ValueError:
            await update.message.reply_html(S.FORECAST_USAGE)
            return
        base = (await get_quotes([ticker])).get(ticker)
        inserted = db.add_forecast(ticker, target, base_price=base, source="user")
        await update.message.reply_html(S.forecast_set_success(ticker, target, base, inserted))
        return

    # --- timeline for one ticker: /forecast TICKER ---
    if len(args) == 1:
        ticker = args[0].upper()
        rows = db.get_forecasts(ticker=ticker)
        if not rows:
            await update.message.reply_html(S.forecast_empty_ticker(ticker))
            return
        statuses = await status_for_forecasts(rows)
        lines = [S.forecast_ticker_header(ticker)]
        lines.extend("• " + S.forecast_line(s) for s in statuses)
        await update.message.reply_html("\n".join(lines))
        return

    # --- overview: latest forecast per ticker ---
    rows = db.get_forecasts()
    if not rows:
        await update.message.reply_html(S.FORECAST_EMPTY)
        return
    latest_by_ticker: dict[str, dict] = {}
    for r in rows:  # rows are newest-first; first seen per ticker is the latest
        latest_by_ticker.setdefault(r["ticker"], r)
    statuses = await status_for_forecasts(list(latest_by_ticker.values()))
    lines = [S.FORECAST_OVERVIEW_HEADER]
    lines.extend(f"<b>{s['ticker']}</b> — " + S.forecast_line(s) for s in statuses)
    await update.message.reply_html("\n".join(lines))


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src import db
    db.init_db()
    n = 3
    if context.args and context.args[0].isdigit():
        n = min(max(int(context.args[0]), 1), 7)

    entries = db.get_recent_digests(limit=n)
    if not entries:
        await update.message.reply_text(S.HISTORY_EMPTY)
        return

    for entry in reversed(entries):  # oldest first
        ts = entry["ran_at"][:16].replace("T", " ") + " UTC"
        await update.message.reply_html(S.history_header(ts) + entry["digest_text"][:3800])


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src import db
    db.init_db()
    n = 1
    if context.args and context.args[0].isdigit():
        n = min(max(int(context.args[0]), 1), 10)

    runs = db.get_recent_runs(limit=n)
    if not runs:
        await update.message.reply_text(S.STATUS_NO_RUNS)
        return

    lines = [S.status_header(n).rstrip()]
    for i, run in enumerate(runs, 1):
        status = "✓" if run["success"] else "✗"
        ts = run["ran_at"][:19].replace("T", " ")
        line = S.status_run_line(i, ts, status, run["articles_fetched"], run["articles_sent"])
        if run.get("error_message"):
            line += S.status_error_line(run["error_message"])
        lines.append(line)
    await update.message.reply_text("\n".join(lines).strip())


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import platform
    from src import db
    db.init_db()
    last = db.get_last_run()
    last_run = last["ran_at"][:19].replace("T", " ") + " UTC" if last else S.HEALTH_NEVER

    next_t = _next_digest_time()
    next_run = next_t.strftime("%Y-%m-%d %H:%M") + f" {DIGEST_TIMEZONE}"

    lines = S.health_lines(
        cpu=_read_cpu_temp(),
        ram=_read_free_ram(),
        uptime=_read_uptime(),
        platform=f"{platform.system()} {platform.machine()}",
        last_run=last_run,
        next_run=next_run,
    )
    await update.message.reply_text("\n".join(lines))


def _read_cpu_temp() -> str:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return f"{int(f.read().strip()) / 1000:.1f}°C"
    except OSError:
        return S.HEALTH_NA


def _read_free_ram() -> str:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return f"{int(line.split()[1]) // 1024} MB free"
    except OSError:
        pass
    return S.HEALTH_NA


def _read_uptime() -> str:
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.read().split()[0])
        d, rem = divmod(int(seconds), 86400)
        h, rem = divmod(rem, 3600)
        return f"{d}d {h}h {rem // 60}m"
    except OSError:
        return S.HEALTH_NA


# ---------------------------------------------------------------------------
# Scheduler — daily digest
# ---------------------------------------------------------------------------

def _next_digest_time() -> datetime:
    """Return the next scheduled digest datetime in the configured timezone."""
    tz = ZoneInfo(DIGEST_TIMEZONE)
    h, m = map(int, DIGEST_SCHEDULE_TIME.split(":"))
    now = datetime.now(tz=tz)
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target


async def _run_scheduled_digest() -> None:
    """Execute the full 3-agent pipeline and deliver to all chat IDs."""
    from src.pipeline import run as pipeline_run
    logger.info("Scheduler: starting daily digest")
    try:
        summary = await pipeline_run(mode="scheduled")
        await send_digest(summary)
        logger.info("Scheduler: digest delivered")
    except Exception as exc:
        logger.error("Scheduler: digest failed: %s", exc)
        await send_alert(S.scheduler_alert(exc))


async def _scheduler_loop() -> None:
    """Sleep until the next configured time, fire the digest, repeat forever."""
    while True:
        target = _next_digest_time()
        wait_secs = (target - datetime.now(tz=ZoneInfo(DIGEST_TIMEZONE))).total_seconds()
        logger.info(
            "Scheduler: next digest at %s %s (in %dh %dm)",
            target.strftime("%Y-%m-%d %H:%M"),
            DIGEST_TIMEZONE,
            int(wait_secs // 3600),
            int((wait_secs % 3600) // 60),
        )
        await asyncio.sleep(wait_secs)
        await _run_scheduled_digest()


# ---------------------------------------------------------------------------
# Bot runner
# ---------------------------------------------------------------------------

async def run_bot() -> None:
    """Start the Telegram bot in polling mode (blocks until interrupted)."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("breaking", cmd_breaking))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("forecast", cmd_forecast))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("health", cmd_health))

    async with app:
        await app.bot.set_my_commands(
            [BotCommand(name, desc) for name, desc in S.BOT_COMMANDS]
        )
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        scheduler = asyncio.create_task(_scheduler_loop())
        next_t = _next_digest_time()
        logger.info(
            "Bot polling — next digest at %s %s — press Ctrl+C to stop",
            next_t.strftime("%Y-%m-%d %H:%M"),
            DIGEST_TIMEZONE,
        )
        try:
            await asyncio.Event().wait()
        finally:
            scheduler.cancel()


# ---------------------------------------------------------------------------
# Phase 1.2 smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def _smoke_test() -> None:
        print("Sending smoke-test message to all configured chat IDs...")
        await send_message(escape_md(S.SMOKE_TEST))
        print("Done. Check your Telegram.")

    asyncio.run(_smoke_test())
