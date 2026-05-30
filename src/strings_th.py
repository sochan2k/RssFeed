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
    "/run — สรุปตามตารางฉบับเต็ม (3-agent chain)\n"
    "/breaking — ข่าวด่วน (2 ชม. ล่าสุด)\n"
    "/breaking &lt;hours&gt; — เช่น <code>/breaking 6</code>\n"
    "/ask &lt;question&gt; — ถาม-ตอบการเงินจากข่าววันนี้\n"
    "\n"
    "<b>📋 Watchlist</b>\n"
    "/watchlist — ดูทุกหมวดและ ticker\n"
    "/add &lt;category&gt; &lt;ticker&gt; — เช่น <code>/add ai_tech MSFT</code>\n"
    "/remove &lt;ticker&gt; — เช่น <code>/remove MSFT</code>\n"
    "\n"
    "<b>ℹ️ ระบบ</b>\n"
    "/history — สรุป 3 ฉบับล่าสุด\n"
    "/history &lt;N&gt; — สรุป N ฉบับล่าสุด เช่น <code>/history 5</code>\n"
    "/status — การรันล่าสุด\n"
    "/status &lt;N&gt; — การรัน N ครั้งล่าสุด เช่น <code>/status 5</code>\n"
    "/health — สถานะระบบ + เวลาสรุปรอบถัดไป\n"
    "/help — แสดงข้อความนี้\n"
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
BOT_COMMANDS: list[tuple[str, str]] = [
    ("summary", "สรุปตลาดแบบทันที [category|ticker]"),
    ("run", "สรุปตามตารางฉบับเต็ม (3-agent chain)"),
    ("breaking", "ข่าวด่วน [ชั่วโมง, ค่าเริ่มต้น 2]"),
    ("ask", "ถาม-ตอบการเงินจากข่าววันนี้"),
    ("watchlist", "ดู watchlist ตามหมวด"),
    ("add", "เพิ่ม ticker: /add <category> <ticker>"),
    ("remove", "ลบ ticker: /remove <ticker>"),
    ("history", "สรุปล่าสุด [N, ค่าเริ่มต้น 3]"),
    ("status", "ประวัติการรัน [N, ค่าเริ่มต้น 1]"),
    ("health", "สถานะระบบ"),
    ("help", "แสดงคำสั่งทั้งหมด"),
]

# --- Smoke test ---
SMOKE_TEST = "บอททำงานปกติ ✓ — ผ่านการทดสอบ Phase 1.2 แล้ว"
