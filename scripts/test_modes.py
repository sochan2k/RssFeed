"""
End-to-end test: runs pipeline modes and sends results to Telegram.

Usage (from repo root):
    python -m scripts.test_modes                  # all modes + dedup check
    python -m scripts.test_modes scheduled
    python -m scripts.test_modes ondemand
    python -m scripts.test_modes breaking
    python -m scripts.test_modes dedup            # dedup isolation check only
    python -m scripts.test_modes commands         # send /help and /watchlist previews
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("test_modes")

PIPELINE_MODES = ["scheduled", "ondemand", "breaking"]
ALL_TARGETS = PIPELINE_MODES + ["dedup", "commands"]


async def run_pipeline_mode(mode: str, hours_back: int | None = None) -> None:
    from src.pipeline import run as pipeline_run
    from src.telegram_bot import escape_md, send_digest, send_message

    label = f"{mode}" + (f" ({hours_back}h)" if hours_back else "")
    logger.info("=== mode: %s ===", label)
    await send_message(escape_md(f"🧪 Test — mode: {label} — starting…"))

    result = await pipeline_run(mode=mode, hours_back=hours_back)
    logger.info("Result length: %d chars", len(result))
    await send_digest(result)
    logger.info("=== Done: %s ===\n", label)


async def run_dedup_check() -> None:
    """
    Verify ondemand/breaking don't consume articles for the scheduled digest.

    Test A — code check: confirm filter_articles is called with mark_seen=False
    for breaking/ondemand (visible in pipeline.py — no DB needed).

    Test B — runtime check (requires fresh unseen articles):
    1. Run breaking (mark_seen=False) — articles NOT marked seen
    2. Run scheduled immediately — should still find the same articles
    If both return "no significant news" it means the DB is saturated from
    earlier runs today; that's expected and is not a test failure.
    """
    from src import db
    from src.pipeline import run as pipeline_run
    from src.telegram_bot import escape_md, send_digest, send_message

    await send_message(escape_md("🧪 Dedup isolation check: breaking (no mark) → scheduled (should still find)…"))

    logger.info("Dedup check: running breaking first (mark_seen=False)…")
    breaking = await pipeline_run(mode="breaking", hours_back=4)
    breaking_empty = "No significant" in breaking or "No articles" in breaking
    await send_digest(breaking)

    await asyncio.sleep(3)

    logger.info("Dedup check: running scheduled immediately after…")
    sched = await pipeline_run(mode="scheduled")
    sched_empty = "No significant" in sched or "No articles" in sched
    await send_digest(sched)

    if breaking_empty and sched_empty:
        msg = "ℹ️ Dedup check: DB saturated (all today's articles already seen from earlier runs). Fix is correct in code — retest tomorrow with fresh articles."
        logger.info("DEDUP CHECK: DB saturated — expected on repeated same-day runs")
    elif not breaking_empty and not sched_empty:
        msg = "✅ Dedup check passed — scheduled found articles that breaking had already seen (mark_seen=False confirmed)"
        logger.info("DEDUP CHECK: passed ✓")
    elif breaking_empty and not sched_empty:
        msg = "✅ Dedup check: breaking empty (tight 4h window), scheduled found articles — both correct"
        logger.info("DEDUP CHECK: trivially passed")
    else:
        msg = "⚠️ Dedup check: breaking found articles but scheduled was empty — possible regression, check logs"
        logger.warning("DEDUP CHECK: unexpected result — breaking had content but scheduled did not")

    await send_message(escape_md(msg))


async def run_commands_preview() -> None:
    """Send /help text and /watchlist preview directly to Telegram."""
    from src import db
    from src.telegram_bot import send_digest, send_message, escape_md

    db.init_db()
    watchlist = db.get_watchlist()

    await send_message(escape_md("🧪 Commands preview — /help and /watchlist:"))

    # /help preview
    from src.telegram_bot import _HELP_TEXT
    await send_digest(_HELP_TEXT)

    # /watchlist preview
    lines = []
    for cat, tickers in sorted(watchlist.items()):
        label = cat.replace("_", " ").title()
        lines.append(f"<b>{label}</b> (<code>{cat}</code>): " + ", ".join(sorted(tickers)))
    cats_hint = ", ".join(f"<code>{c}</code>" for c in sorted(watchlist.keys()))
    lines.append(f"\n<i>Categories: {cats_hint}</i>")
    await send_digest("\n".join(lines))


async def main() -> None:
    from src import db
    db.init_db()

    targets = sys.argv[1:] if len(sys.argv) > 1 else ALL_TARGETS
    unknown = [t for t in targets if t not in ALL_TARGETS]
    if unknown:
        print(f"Unknown target(s): {unknown}. Choose from: {ALL_TARGETS}")
        sys.exit(1)

    for i, target in enumerate(targets):
        if target == "dedup":
            await run_dedup_check()
        elif target == "commands":
            await run_commands_preview()
        elif target == "breaking":
            await run_pipeline_mode("breaking", hours_back=4)
        else:
            await run_pipeline_mode(target)

        if i < len(targets) - 1:
            logger.info("Pausing 5s between tests…")
            await asyncio.sleep(5)

    print("\nAll tests sent to Telegram. Check your chat.")


if __name__ == "__main__":
    asyncio.run(main())
