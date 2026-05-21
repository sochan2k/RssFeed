import asyncio
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Bot, BotCommand, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

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

_HELP_TEXT = (
    "<b>📊 Market Reports</b>\n"
    "/summary — Full market digest (all watchlist)\n"
    "/summary &lt;ticker|category&gt; — Filtered digest\n"
    "  e.g. <code>/summary NVDA</code> or <code>/summary ai_tech</code>\n"
    "/run — Full scheduled digest (3-agent chain)\n"
    "/breaking — Breaking news (last 2h)\n"
    "/breaking &lt;hours&gt; — e.g. <code>/breaking 6</code>\n"
    "/ask &lt;question&gt; — Finance Q&amp;A grounded in today's news\n"
    "\n"
    "<b>📋 Watchlist</b>\n"
    "/watchlist — View all categories and tickers\n"
    "/add &lt;category&gt; &lt;ticker&gt; — e.g. <code>/add ai_tech MSFT</code>\n"
    "/remove &lt;ticker&gt; — e.g. <code>/remove MSFT</code>\n"
    "\n"
    "<b>ℹ️ System</b>\n"
    "/history — Last 3 digests\n"
    "/history &lt;N&gt; — Last N digests, e.g. <code>/history 5</code>\n"
    "/status — Last pipeline run\n"
    "/status &lt;N&gt; — Last N runs, e.g. <code>/status 5</code>\n"
    f"/health — System metrics + next scheduled digest\n"
    "/help — Show this message\n"
    "\n"
    f"<i>📅 Daily digest runs at {DIGEST_SCHEDULE_TIME} {DIGEST_TIMEZONE}</i>"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(
        "Welcome to <b>StockDigest Bot</b> 📈\n\n"
        "I deliver US financial market briefings powered by Gemini AI.\n"
        "Scheduled digests run automatically; use commands for on-demand reports.\n\n"
        + _HELP_TEXT
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(_HELP_TEXT)


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually trigger a full 3-agent scheduled digest."""
    from src.pipeline import run as pipeline_run
    await update.message.reply_text("Running full scheduled digest (3-agent chain), please wait…")
    try:
        summary = await pipeline_run(mode="scheduled")
        await update.message.reply_html(summary)
    except Exception as exc:
        logger.error("cmd_run error: %s", exc)
        await update.message.reply_text(f"Error: {exc}")


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.pipeline import run as pipeline_run
    target = context.args[0].lower() if context.args else None

    if target:
        await update.message.reply_text(f"Generating digest for '{target.upper()}', please wait…")
    else:
        await update.message.reply_text("Generating market digest, please wait…")

    try:
        summary = await pipeline_run(mode="ondemand", target=target)
        await update.message.reply_html(summary)
    except Exception as exc:
        await update.message.reply_text(f"Error: {exc}")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args).strip() if context.args else ""
    if not question:
        await update.message.reply_text(
            "Usage: /ask <your question>\n"
            "Example: /ask why did treasury yields jump today?"
        )
        return

    await update.message.reply_text("Researching…")

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
        await update.message.reply_text(f"Error: {exc}")


async def cmd_breaking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.config import BREAKING_NEWS_HOURS
    from src.pipeline import run as pipeline_run
    hours = BREAKING_NEWS_HOURS
    if context.args and context.args[0].isdigit():
        requested = int(context.args[0])
        hours = min(max(requested, 1), 24)
        if hours != requested:
            await update.message.reply_text(f"Hours clamped to {hours} (valid range: 1–24).")
    await update.message.reply_text(f"Fetching last {hours}h of news…")
    try:
        summary = await pipeline_run(mode="breaking", hours_back=hours)
        await update.message.reply_html(summary)
    except Exception as exc:
        await update.message.reply_text(f"Error: {exc}")


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src import db
    db.init_db()
    watchlist = db.get_watchlist()
    if not watchlist:
        await update.message.reply_text("Watchlist is empty.\nUse /add <category> <ticker> to add tickers.")
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
        await update.message.reply_html(
            f"No category named '<code>{filter_cat}</code>'.\n"
            f"Available: {cats}"
        )
        return

    cats_hint = ", ".join(f"<code>{c}</code>" for c in sorted(watchlist.keys()))
    lines.append(f"\n<i>Use /summary &lt;category&gt; or /summary &lt;TICKER&gt;</i>")
    lines.append(f"<i>Categories: {cats_hint}</i>")
    await update.message.reply_html("\n".join(lines))


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /add <category> <ticker>\nExample: /add ai_tech MSFT")
        return

    cat, ticker = context.args[0].lower(), context.args[1].upper()
    from src import db
    db.init_db()
    db.add_to_watchlist(cat, ticker)
    label = cat.replace("_", " ").title()
    await update.message.reply_html(f"✅ <b>{ticker}</b> added to <b>{label}</b>.")


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /remove <ticker>\nExample: /remove NVDA")
        return

    ticker = context.args[0].upper()
    from src import db
    db.init_db()
    removed = db.remove_from_watchlist(ticker)
    if removed:
        await update.message.reply_text(f"Removed {ticker} from watchlist.")
    else:
        await update.message.reply_text(f"{ticker} not found in watchlist.")


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src import db
    db.init_db()
    n = 3
    if context.args and context.args[0].isdigit():
        n = min(max(int(context.args[0]), 1), 7)

    entries = db.get_recent_digests(limit=n)
    if not entries:
        await update.message.reply_text(
            "No digest history yet.\nRun /run to generate the first scheduled digest."
        )
        return

    for entry in reversed(entries):  # oldest first
        ts = entry["ran_at"][:16].replace("T", " ") + " UTC"
        header = f"<b>📅 {ts}</b>\n\n"
        await update.message.reply_html(header + entry["digest_text"][:3800])


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src import db
    db.init_db()
    n = 1
    if context.args and context.args[0].isdigit():
        n = min(max(int(context.args[0]), 1), 10)

    runs = db.get_recent_runs(limit=n)
    if not runs:
        await update.message.reply_text("No runs recorded yet.")
        return

    header = f"Last {n} pipeline run(s):\n" if n > 1 else ""
    lines = [header.rstrip()]
    for i, run in enumerate(runs, 1):
        status = "✓" if run["success"] else "✗"
        ts = run["ran_at"][:19].replace("T", " ")
        line = f"{i}. {ts} UTC — {status} {run['articles_fetched']} fetched / {run['articles_sent']} sent"
        if run.get("error_message"):
            line += f"\n   ⚠ {run['error_message'][:120]}"
        lines.append(line)
    await update.message.reply_text("\n".join(lines).strip())


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import platform
    from src import db
    db.init_db()
    last = db.get_last_run()
    last_run = last["ran_at"][:19].replace("T", " ") + " UTC" if last else "never"

    next_t = _next_digest_time()
    next_run = next_t.strftime("%Y-%m-%d %H:%M") + f" {DIGEST_TIMEZONE}"

    lines = [
        f"CPU temp: {_read_cpu_temp()}",
        f"Free RAM: {_read_free_ram()}",
        f"Uptime:   {_read_uptime()}",
        f"Platform: {platform.system()} {platform.machine()}",
        f"Last run: {last_run}",
        f"Next run: {next_run}",
    ]
    await update.message.reply_text("\n".join(lines))


def _read_cpu_temp() -> str:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return f"{int(f.read().strip()) / 1000:.1f}°C"
    except OSError:
        return "n/a (not on Pi)"


def _read_free_ram() -> str:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return f"{int(line.split()[1]) // 1024} MB free"
    except OSError:
        pass
    return "n/a (not on Pi)"


def _read_uptime() -> str:
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.read().split()[0])
        d, rem = divmod(int(seconds), 86400)
        h, rem = divmod(rem, 3600)
        return f"{d}d {h}h {rem // 60}m"
    except OSError:
        return "n/a (not on Pi)"


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
        await send_alert(f"⚠️ Daily digest failed: {exc}")


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
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("health", cmd_health))

    async with app:
        await app.bot.set_my_commands([
            BotCommand("summary", "On-demand digest [category|ticker]"),
            BotCommand("run", "Full scheduled digest (3-agent chain)"),
            BotCommand("breaking", "Breaking news [hours, default 2]"),
            BotCommand("ask", "Finance Q&A grounded in today's news"),
            BotCommand("watchlist", "View watchlist by category"),
            BotCommand("add", "Add ticker: /add <category> <ticker>"),
            BotCommand("remove", "Remove ticker: /remove <ticker>"),
            BotCommand("history", "Recent digests [N, default 3]"),
            BotCommand("status", "Pipeline run history [N, default 1]"),
            BotCommand("health", "System metrics"),
            BotCommand("help", "Show all commands"),
        ])
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
        await send_message(escape_md("Bot is alive ✓ — Phase 1.2 smoke test passed."))
        print("Done. Check your Telegram.")

    asyncio.run(_smoke_test())
