import asyncio
import logging
import re

from telegram import Bot, BotCommand, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from src.config import ADMIN_CHAT_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS

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

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.pipeline import run as pipeline_run
    await update.message.reply_text("Generating digest, please wait…")
    try:
        summary = await pipeline_run(mode="ondemand")
        await update.message.reply_html(summary)
    except Exception as exc:
        await update.message.reply_text(f"Error: {exc}")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args).strip() if context.args else ""
    if not question:
        await update.message.reply_text(
            "Usage: /ask <your question>\n"
            "Example: /ask why did treasury yields jump and kill stocks today?"
        )
        return

    await update.message.reply_text("Researching…")

    try:
        from src.feeds import fetch_articles
        from src.filters import filter_articles
        from src.gemini_client import generate
        from src.prompts import ASK_SYSTEM_PROMPT, build_ask_prompt

        articles = await fetch_articles()
        filtered = filter_articles(articles)
        prompt = build_ask_prompt(question, filtered)
        answer = await generate(prompt, system_prompt=ASK_SYSTEM_PROMPT, use_cache=True)
        await update.message.reply_html(answer)
    except Exception as exc:
        logger.error("cmd_ask error: %s", exc)
        await update.message.reply_text(f"Error: {exc}")


async def cmd_breaking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.pipeline import run as pipeline_run
    await update.message.reply_text("Fetching last 2 hours of news…")
    try:
        summary = await pipeline_run(mode="breaking", hours_back=2)
        await update.message.reply_html(summary)
    except Exception as exc:
        await update.message.reply_text(f"Error: {exc}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src import db
    db.init_db()
    run = db.get_last_run()
    if not run:
        await update.message.reply_text("No runs recorded yet.")
        return
    status = "✓ Success" if run["success"] else "✗ Failed"
    lines = [
        f"Last run: {run['ran_at']} UTC",
        f"Status:   {status}",
        f"Fetched:  {run['articles_fetched']} articles",
        f"Sent:     {run['articles_sent']} to Gemini",
    ]
    if run.get("error_message"):
        lines.append(f"Error:    {run['error_message'][:200]}")
    await update.message.reply_text("\n".join(lines))


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import platform
    from src import db
    db.init_db()
    last = db.get_last_run()
    last_run = last["ran_at"] if last else "never"

    # Real metrics on Pi — stubs on Windows/Mac
    cpu_temp = _read_cpu_temp()
    free_ram = _read_free_ram()
    uptime = _read_uptime()

    lines = [
        f"CPU temp: {cpu_temp}",
        f"Free RAM: {free_ram}",
        f"Last run: {last_run}",
        f"Platform: {platform.system()} {platform.machine()}",
        f"Uptime:   {uptime}",
    ]
    await update.message.reply_text("\n".join(lines))


def _read_cpu_temp() -> str:
    try:
        temp_raw = open("/sys/class/thermal/thermal_zone0/temp").read().strip()
        return f"{int(temp_raw) / 1000:.1f}°C"
    except OSError:
        return "n/a (not on Pi)"


def _read_free_ram() -> str:
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                kb = int(line.split()[1])
                return f"{kb // 1024} MB free"
    except OSError:
        pass
    return "n/a (not on Pi)"


def _read_uptime() -> str:
    try:
        seconds = float(open("/proc/uptime").read().split()[0])
        d, rem = divmod(int(seconds), 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        return f"{d}d {h}h {m}m"
    except OSError:
        return "n/a (not on Pi)"


# ---------------------------------------------------------------------------
# Bot runner
# ---------------------------------------------------------------------------

async def run_bot() -> None:
    """Start the Telegram bot in polling mode (blocks until interrupted)."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("breaking", cmd_breaking))
    app.add_handler(CommandHandler("ask", cmd_ask))

    async with app:
        await app.bot.set_my_commands([
            BotCommand("summary", "On-demand stock digest"),
            BotCommand("breaking", "Last 2 hours of breaking news"),
            BotCommand("ask", "Ask a finance question grounded in today's news"),
            BotCommand("status", "Last run time and result"),
            BotCommand("health", "System metrics"),
        ])
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot polling — press Ctrl+C to stop")
        await asyncio.Event().wait()


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
