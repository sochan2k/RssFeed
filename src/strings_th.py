"""
Thai user-facing strings for the Telegram bot UI (commands, status, errors).

Conventions:
- Keep command names (/summary, /add …), ticker symbols, and HTML tags in Latin.
- HTML-bound strings use &lt; &gt; &amp; entities (sent with ParseMode.HTML).
- Parameterized messages are functions; static ones are constants.
"""
from src.config import DIGEST_SCHEDULE_TIME, DIGEST_TIMEZONE

# --- Help / start (HTML) ---
HELP_TEXT = (
    "<b>📊 รายงานตลาด</b>\n"
    "/summary — สรุปตลาดฉบับเต็ม (ทุก watchlist)\n"
    "/summary &lt;ticker|category&gt; — สรุปแบบกรอง\n"
    "  เช่น <code>/summary NVDA</code> หรือ <code>/summary ai_tech</code>\n"
    "/breaking — ข่าวด่วน (2 ชม. ล่าสุด)\n"
    "/breaking &lt;hours&gt; — เช่น <code>/breaking 6</code>\n"
    "/ask &lt;question&gt; — ถาม-ตอบการเงินจากข่าววันนี้\n"
    "\n"
    "<b>📋 Watchlist</b>\n"
    "/watchlist — ดูทุกหมวดและ ticker\n"
    "/add &lt;category&gt; &lt;ticker&gt; — เช่น <code>/add ai_tech MSFT</code>\n"
    "/remove &lt;ticker&gt; — เช่น <code>/remove MSFT</code>\n"
    "\n"
    "<b>💼 พอร์ต</b>\n"
    "/portfolio — ดูสถานะที่ถือ + ผลตอบแทนคาดหวัง\n"
    "/buy &lt;ticker&gt; &lt;จำนวน&gt; &lt;ต้นทุน&gt; [เป้าหมาย] — เช่น <code>/buy NVDA 10 120 200</code>\n"
    "/sell &lt;ticker&gt; — เช่น <code>/sell NVDA</code>\n"
    "/forecast — เทียบเป้าที่เคยตั้งกับราคาวันนี้\n"
    "/forecast &lt;ticker&gt; [ราคา] — ดูประวัติ/ตั้งเป้า เช่น <code>/forecast NVDA 200</code>\n"
    "\n"
    "<b>ℹ️ ระบบ</b>\n"
    "/history — สรุป 3 ฉบับล่าสุด\n"
    "/history &lt;N&gt; — สรุป N ฉบับล่าสุด เช่น <code>/history 5</code>\n"
    "/help — แสดงข้อความนี้\n"
    "<i>ขั้นสูง (ยังใช้ได้): /run (สรุป 3-agent ฉบับเต็ม) · /status (ประวัติการรัน) · /health (สถานะระบบ)</i>\n"
    "\n"
    f"<i>📅 สรุปประจำวันเวลา {DIGEST_SCHEDULE_TIME} {DIGEST_TIMEZONE}</i>"
)

WELCOME = (
    "ยินดีต้อนรับสู่ <b>StockDigest Bot</b> 📈\n\n"
    "ผมส่งบทสรุปตลาดการเงินสหรัฐฯ ขับเคลื่อนด้วย Gemini AI\n"
    "สรุปตามตารางจะทำงานอัตโนมัติ และคุณสั่งดูรายงานแบบทันทีได้ด้วยคำสั่งต่าง ๆ\n\n"
)

# --- Command wait/usage messages (plain text) ---
RUN_WAIT = "กำลังสร้างสรุปตามตารางฉบับเต็ม (3-agent chain) กรุณารอสักครู่…"
SUMMARY_WAIT = "กำลังสร้างสรุปตลาด กรุณารอสักครู่…"


def summary_wait_target(target: str) -> str:
    return f"กำลังสร้างสรุปสำหรับ '{target.upper()}' กรุณารอสักครู่…"


ASK_USAGE = (
    "วิธีใช้: /ask <คำถามของคุณ>\n"
    "ตัวอย่าง: /ask ทำไมอัตราผลตอบแทนพันธบัตรถึงพุ่งขึ้นวันนี้?"
)
ASK_WORKING = "กำลังค้นหา…"


def breaking_clamp(hours: int) -> str:
    return f"ปรับจำนวนชั่วโมงเป็น {hours} (ช่วงที่ใช้ได้: 1–24)"


def breaking_fetch(hours: int) -> str:
    return f"กำลังดึงข่าว {hours} ชม. ล่าสุด…"


# --- Watchlist (HTML) ---
WATCHLIST_EMPTY = "Watchlist ว่างเปล่า\nใช้ /add <category> <ticker> เพื่อเพิ่ม ticker"
WATCHLIST_FOOTER_HINT = "\n<i>ใช้ /summary &lt;category&gt; หรือ /summary &lt;TICKER&gt;</i>"


def watchlist_no_category(filter_cat: str, cats: str) -> str:
    return (
        f"ไม่มีหมวดชื่อ '<code>{filter_cat}</code>'\n"
        f"หมวดที่มี: {cats}"
    )


def watchlist_categories(cats_hint: str) -> str:
    return f"<i>หมวด: {cats_hint}</i>"


# --- Add / remove ---
ADD_USAGE = "วิธีใช้: /add <category> <ticker>\nตัวอย่าง: /add ai_tech MSFT"
REMOVE_USAGE = "วิธีใช้: /remove <ticker>\nตัวอย่าง: /remove NVDA"


def add_success(ticker: str, label: str) -> str:
    return f"✅ เพิ่ม <b>{ticker}</b> เข้าหมวด <b>{label}</b> แล้ว"


def remove_success(ticker: str) -> str:
    return f"ลบ {ticker} ออกจาก watchlist แล้ว"


def remove_not_found(ticker: str) -> str:
    return f"ไม่พบ {ticker} ใน watchlist"


# --- Portfolio / holdings (HTML) ---
BUY_USAGE = (
    "วิธีใช้: /buy &lt;ticker&gt; &lt;จำนวนหุ้น&gt; &lt;ต้นทุนต่อหุ้น&gt; [ราคาเป้าหมาย]\n"
    "ตัวอย่าง: <code>/buy NVDA 10 120 200</code>"
)
SELL_USAGE = "วิธีใช้: /sell &lt;ticker&gt;\nตัวอย่าง: <code>/sell NVDA</code>"
PORTFOLIO_EMPTY = "พอร์ตว่างเปล่า\nใช้ /buy &lt;ticker&gt; &lt;จำนวนหุ้น&gt; &lt;ต้นทุน&gt; [เป้าหมาย] เพื่อเพิ่มสถานะ"
PORTFOLIO_HEADER = "<b>💼 พอร์ตของคุณ</b>"


def buy_success(ticker: str, shares: float, cost: float, target: float | None, exp_return: float | None) -> str:
    msg = f"✅ บันทึก <b>{ticker}</b>: {shares:g} หุ้น @ ${cost:g}"
    if target is not None:
        msg += f" → เป้าหมาย ${target:g}"
        if exp_return is not None:
            msg += f" (ผลตอบแทนคาดหวัง {exp_return:+.1%})"
    return msg


def portfolio_line(h: dict) -> str:
    """Render one enriched holding (see prices.compute_pnl) as a portfolio bullet."""
    line = f"• <b>{h['ticker']}</b>: {h['shares']:g} หุ้น @ ${h['avg_cost']:,.2f}"
    price = h.get("current_price")
    if price is not None:
        line += f" → <b>${price:,.2f}</b>"
        ur = h.get("unrealized_return")
        pl = h.get("unrealized_pl")
        if ur is not None:
            line += f" | กำไร/ขาดทุน <b>{ur:+.1%}</b>"
        if pl is not None:
            line += f" ({pl:+,.0f}$)"
    target = h.get("target_price")
    if target is not None:
        line += f" | เป้า ${target:,.2f}"
        tt = h.get("to_target")
        if tt is not None:
            line += f" (เหลืออีก {tt:+.1%})"
        elif h.get("expected_return") is not None:
            line += f" (คาดหวัง {h['expected_return']:+.1%})"
    else:
        line += " | <i>ยังไม่ตั้งเป้า</i>"
    w = h.get("weight")
    if w is not None:
        line += f" | น้ำหนัก {w:.0%}"
    if price is None:
        line += " <i>(ไม่มีราคาล่าสุด)</i>"
    return line


def portfolio_totals(holdings: list[dict]) -> str:
    """Render the portfolio total / P&L footer from enriched holdings."""
    cost_all = sum(h["cost_basis"] for h in holdings)
    priced = [h for h in holdings if h.get("market_value") is not None]
    if not priced:
        return f"<b>รวมต้นทุน:</b> ${cost_all:,.0f} <i>(ไม่มีราคาล่าสุด)</i>"
    mv = sum(h["market_value"] for h in priced)
    cost_priced = sum(h["cost_basis"] for h in priced)
    pl = mv - cost_priced
    pct = pl / cost_priced if cost_priced else 0
    line = f"<b>รวม:</b> มูลค่า ${mv:,.0f} | ต้นทุน ${cost_priced:,.0f} | P/L <b>{pl:+,.0f}$</b> ({pct:+.1%})"
    if len(priced) < len(holdings):
        line += f" <i>(จาก {len(priced)}/{len(holdings)} สถานะที่มีราคา)</i>"
    return line


def sell_success(ticker: str) -> str:
    return f"ลบ {ticker} ออกจากพอร์ตแล้ว"


def sell_not_found(ticker: str) -> str:
    return f"ไม่พบ {ticker} ในพอร์ต"


# --- Forecast tracking (HTML) ---
FORECAST_USAGE = (
    "วิธีใช้:\n"
    "/forecast — ดูการคาดการณ์ทั้งหมดเทียบราคาวันนี้\n"
    "/forecast &lt;ticker&gt; — ดูประวัติเป้าของตัวนั้น\n"
    "/forecast &lt;ticker&gt; &lt;ราคา&gt; — ตั้งเป้าใหม่ เช่น <code>/forecast NVDA 200</code>"
)
FORECAST_EMPTY = (
    "ยังไม่มีการคาดการณ์ที่บันทึกไว้\n"
    "ตั้งเป้าด้วย /forecast &lt;ticker&gt; &lt;ราคา&gt; เช่น <code>/forecast NVDA 200</code>"
)
FORECAST_OVERVIEW_HEADER = "<b>🎯 การคาดการณ์ที่ติดตามอยู่</b>"


def forecast_ticker_header(ticker: str) -> str:
    return f"<b>🎯 ประวัติเป้าราคา {ticker}</b>"


def forecast_empty_ticker(ticker: str) -> str:
    return f"ไม่มีเป้าราคาที่บันทึกไว้สำหรับ {ticker}"


def forecast_set_success(ticker: str, target: float, base: float | None, inserted: bool) -> str:
    if not inserted:
        return f"เป้า {ticker} ที่ ${target:g} มีบันทึกอยู่แล้ว (ไม่บันทึกซ้ำ)"
    msg = f"✅ บันทึกเป้า <b>{ticker}</b> ที่ <b>${target:g}</b>"
    if base is not None:
        gap = (target - base) / base if base else None
        msg += f" (ราคาฐานวันนี้ ${base:,.2f}"
        if gap is not None:
            msg += f", upside {gap:+.1%}"
        msg += ")"
    else:
        msg += " <i>(ไม่มีราคาฐาน — ดึงราคาไม่ได้)</i>"
    return msg


def _forecast_status_phrase(s: dict) -> str:
    if s.get("current_price") is None:
        return "<i>ไม่มีราคาล่าสุด</i>"
    if s.get("reached"):
        return "ถึงเป้าแล้ว ✓"
    prog = s.get("progress")
    gap = s.get("gap_to_target")
    if prog is not None and prog >= 0.9:
        return f"ใกล้เป้า (เหลือ {gap:+.1%})" if gap is not None else "ใกล้เป้า"
    if gap is not None:
        return f"เหลืออีก {gap:+.1%}"
    return ""


def forecast_line(s: dict) -> str:
    """Render one forecast-status row (see prices.compute_forecast_status).

    No leading bullet — callers add structure (timeline vs overview).
    """
    src = "เป้าผม" if s["source"] == "user" else "นักวิเคราะห์"
    if s["source"] == "analyst" and s.get("note"):
        src += f" {s['note']}"
    line = f"${s['target_price']:g} <i>({src})</i>"
    age = s.get("age_days")
    if age is not None:
        line += f" ตั้งเมื่อ {age} วันก่อน"
    base = s.get("base_price")
    if base is not None:
        line += f" @ ${base:,.2f}"
    cur = s.get("current_price")
    if cur is not None:
        line += f" → วันนี้ ${cur:,.2f}"
        prog = s.get("progress")
        if prog is not None:
            line += f" | วิ่งไป {prog:.0%}"
    phrase = _forecast_status_phrase(s)
    if phrase:
        line += f" | {phrase}"
    return line


# --- History / status ---
HISTORY_EMPTY = "ยังไม่มีประวัติสรุป\nใช้ /run เพื่อสร้างสรุปตามตารางฉบับแรก"
STATUS_NO_RUNS = "ยังไม่มีการรันที่บันทึกไว้"


def history_header(ts: str) -> str:
    return f"<b>📅 {ts}</b>\n\n"


def status_header(n: int) -> str:
    return f"การรันล่าสุด {n} ครั้ง:\n" if n > 1 else ""


def status_run_line(i: int, ts: str, status: str, fetched: int, sent: int) -> str:
    return f"{i}. {ts} UTC — {status} ดึง {fetched} / ส่ง {sent}"


def status_error_line(message: str) -> str:
    return f"\n   ⚠ {message[:120]}"


# --- Health (plain text) ---
HEALTH_NA = "ไม่มีข้อมูล (ไม่ได้รันบน Pi)"
HEALTH_NEVER = "ยังไม่เคยรัน"


def health_lines(cpu: str, ram: str, uptime: str, platform: str, last_run: str, next_run: str) -> list[str]:
    return [
        f"อุณหภูมิ CPU: {cpu}",
        f"RAM ว่าง:    {ram}",
        f"เวลาทำงาน:   {uptime}",
        f"แพลตฟอร์ม:   {platform}",
        f"รันล่าสุด:    {last_run}",
        f"รันถัดไป:     {next_run}",
    ]


# --- Errors / alerts ---
def error(exc: object) -> str:
    return f"เกิดข้อผิดพลาด: {exc}"


def scheduler_alert(exc: object) -> str:
    return f"⚠️ การสรุปประจำวันล้มเหลว: {exc}"


# --- BotFather command menu descriptions ---
# Note: /run, /status, /health are intentionally omitted from this menu to keep
# the / autocomplete list focused. Their handlers stay registered in
# telegram_bot.py, so power users can still type them (listed under "ขั้นสูง" in /help).
BOT_COMMANDS: list[tuple[str, str]] = [
    ("summary", "สรุปตลาดแบบทันที [category|ticker]"),
    ("breaking", "ข่าวด่วน [ชั่วโมง, ค่าเริ่มต้น 2]"),
    ("ask", "ถาม-ตอบการเงินจากข่าววันนี้"),
    ("watchlist", "ดู watchlist ตามหมวด"),
    ("add", "เพิ่ม ticker: /add <category> <ticker>"),
    ("remove", "ลบ ticker: /remove <ticker>"),
    ("portfolio", "ดูพอร์ต + ผลตอบแทนคาดหวัง"),
    ("buy", "เพิ่มสถานะ: /buy <ticker> <จำนวน> <ต้นทุน> [เป้าหมาย]"),
    ("sell", "ลบสถานะ: /sell <ticker>"),
    ("forecast", "เทียบเป้าที่ตั้งไว้กับราคาวันนี้ [ticker] [ราคา]"),
    ("history", "สรุปล่าสุด [N, ค่าเริ่มต้น 3]"),
    ("help", "แสดงคำสั่งทั้งหมด"),
]

# --- Smoke test ---
SMOKE_TEST = "บอททำงานปกติ ✓ — ผ่านการทดสอบ Phase 1.2 แล้ว"
