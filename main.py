import argparse
import asyncio
import datetime
import logging
import sys
import traceback

import holidays

from src.pipeline import run as pipeline_run
from src.telegram_bot import send_alert, send_digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_US_HOLIDAYS = holidays.US()


def is_trading_day() -> bool:
    today = datetime.date.today()
    return today.weekday() < 5 and today not in _US_HOLIDAYS


async def _main(mode: str, force: bool) -> None:
    if not force and not is_trading_day():
        logger.info("Not a US trading day — skipping. Use --force to override.")
        return

    logger.info("Starting pipeline mode=%s", mode)
    try:
        summary = await pipeline_run(mode=mode)
        await send_digest(summary)
        logger.info("Pipeline complete.")
    except Exception:
        error_text = traceback.format_exc()
        logger.error("Pipeline failed:\n%s", error_text)
        await send_alert(f"[Stock Digest] Pipeline error:\n{error_text[-1000:]}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily US Stock News Summarizer")
    parser.add_argument(
        "--mode",
        choices=["scheduled", "ondemand", "breaking"],
        default="scheduled",
        help="scheduled: full digest | ondemand: compact | breaking: last 2h",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even on weekends/holidays",
    )
    parser.add_argument(
        "--bot",
        action="store_true",
        help="Start Telegram bot in polling mode (blocks until interrupted)",
    )
    args = parser.parse_args()

    if args.bot:
        from src.telegram_bot import run_bot
        asyncio.run(run_bot())
    else:
        asyncio.run(_main(args.mode, args.force))


if __name__ == "__main__":
    main()
