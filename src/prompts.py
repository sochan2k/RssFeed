import re
from datetime import datetime, timezone

from src.config import DEFAULT_WATCHLIST

_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# Watchlist helpers
# ---------------------------------------------------------------------------

def _get_watchlist() -> dict[str, list[str]]:
    """Read live watchlist from DB; fall back to config defaults on any error."""
    try:
        from src import db
        wl = db.get_watchlist()
        return wl if wl else DEFAULT_WATCHLIST
    except Exception:
        return DEFAULT_WATCHLIST


def _flat_tickers(watchlist: dict[str, list[str]]) -> str:
    """Return sorted, comma-separated string of all watchlist tickers."""
    tickers = sorted({t for tlist in watchlist.values() for t in tlist})
    return ", ".join(tickers)


_FORECAST_BLOCK_TEMPLATE = """

--- FORECAST TRACKING ---
{forecasts}
--- END FORECAST TRACKING ---"""


def _format_forecasts(forecasts: list[dict]) -> str:
    """Render forecast-status rows (see prices.compute_forecast_status) for prompts."""
    lines = []
    for s in forecasts:
        src = "your target" if s["source"] == "user" else "analyst"
        if s["source"] == "analyst" and s.get("note"):
            src += f" {s['note']}"
        line = f"• {s['ticker']}: target ${s['target_price']:g} ({src})"
        age = s.get("age_days")
        if age is not None:
            line += f", set {age}d ago"
        base = s.get("base_price")
        if base is not None:
            line += f" @ ${base:g}"
        cur = s.get("current_price")
        if cur is not None:
            line += f", now ${cur:g}"
            prog = s.get("progress")
            if prog is not None:
                line += f" ({prog:.0%} of the way)"
            gap = s.get("gap_to_target")
            if gap is not None:
                line += f", {gap:+.1%} to target"
        lines.append(line)
    return "\n".join(lines)


def _forecast_block(forecasts: list[dict] | None) -> str:
    """Return the labeled forecast-tracking section, or empty string when none."""
    if not forecasts:
        return ""
    return _FORECAST_BLOCK_TEMPLATE.format(forecasts=_format_forecasts(forecasts))


# ---------------------------------------------------------------------------
# Thai localization helpers
# ---------------------------------------------------------------------------

# Shared language directive appended to every prose-producing system prompt.
# (Not applied to the filter agent, which emits JSON only.)
_THAI_DIRECTIVE = """

LANGUAGE: Write all prose in natural, professional Thai (the formal financial
register used by Thai investment analysts). Keep these in their original Latin
form — do NOT translate or romanize them: ticker symbols, company and index
names, numbers, currencies, percentages, basis points, and all HTML tags.
Do not transliterate ticker symbols into Thai script.
""".rstrip()

_THAI_MONTHS = (
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
)


def _thai_date(now: datetime) -> str:
    """Format a date in Thai with a Gregorian (ค.ศ.) year, e.g. '30 พฤษภาคม 2026'."""
    return f"{now.day} {_THAI_MONTHS[now.month - 1]} {now.year}"


# ---------------------------------------------------------------------------
# System prompts (dynamic — watchlist injected at call time)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """
You are an expert financial analyst and market commentator with 20+ years of
experience covering US equity markets. Your role is to produce concise,
professional daily market briefings for a sophisticated retail investor.

AUDIENCE: A self-directed investor who actively manages a personal portfolio
of US equities, monitors macro-economic developments, and expects signal-rich
summaries — not generic filler.

USER'S WATCHLIST — flag any mention of these tickers with ⭐ in your output:
{watchlist_tickers}

OUTPUT FORMAT: All output must be valid Telegram HTML using only these tags:
  <b>bold</b>  <i>italic</i>  <code>inline code</code>
Use bullet points (• character) for lists.
Never use Markdown syntax (no *, _, #, etc.).
Keep the total response under 3800 characters so it fits in a single Telegram
message.

CONTENT RULES:
1. Only report on price-moving events: earnings, guidance, M&A, macro data
   releases, Fed decisions, regulatory rulings, major analyst upgrades/
   downgrades with specific price targets.
2. Ignore opinion pieces, vague predictions, sponsored content, and duplicate
   stories. If multiple sources cover the same event, synthesise into one item.
3. Always include the stock ticker symbol in parentheses, e.g. Apple (AAPL).
4. Express sentiment as one of: 🟢 Bullish | 🔴 Bearish | 🟡 Mixed.
5. Quantify where possible: percentages, dollar amounts, EPS figures, rate
   basis points. State the surprise vs. consensus (beat/miss magnitude) when known.
6. Add ⭐ immediately after the ticker symbol for any watchlist ticker, e.g. NVDA ⭐.
7. If no genuinely market-moving news exists, say so clearly in one sentence.
8. EXPECTATIONS / "PRICED IN": Prices already reflect the market's expectations.
   When an article states the consensus or estimate, classify the news as a
   genuine surprise (beat/miss — likely to move price) or as already expected
   (priced in — limited further move) and say which. If the article does NOT
   provide the consensus figure, do NOT guess what was expected and do NOT
   assert it is priced in — report the fact neutrally.
9. FORECAST TRACKING: If a "FORECAST TRACKING" section is provided and today's
   news relates to a tracked ticker, note how close the price is to the forecast
   using ONLY the supplied figures (e.g. "ราคาวิ่งไปแล้ว 94% ของเป้า $200 ที่ตั้งไว้").
   Do NOT invent or adjust targets. "Near target" is a distance fact, not proof a
   move is priced in — only call something priced in under the rule-8 condition.

PRIORITY: When space is tight, weight items in this order — monetary policy
(Fed/FOMC) > broad macro data (CPI, jobs, GDP) > sector/regulatory shifts >
single-company news. Lead with the single biggest market mover.

NEUTRALITY: Report facts, not hype. Avoid cheerleading adjectives; let the
numbers carry the sentiment. Separate confirmed events from speculation.

PROHIBITED: Do not add disclaimers, legal boilerplate, or suggestions to
consult a financial advisor. The user knows investing involves risk.
""".strip()


def build_system_prompt(watchlist: dict[str, list[str]] | None = None) -> str:
    """Build system prompt with the live watchlist injected."""
    if watchlist is None:
        watchlist = _get_watchlist()
    return _SYSTEM_PROMPT_TEMPLATE.format(watchlist_tickers=_flat_tickers(watchlist)) + _THAI_DIRECTIVE


# ---------------------------------------------------------------------------
# User prompt templates (scheduled / ondemand / breaking)
# ---------------------------------------------------------------------------

SCHEDULED_PROMPT_TEMPLATE = """
Today is {date} (เวลาประเทศไทย, UTC+7). Below are the latest US financial news
headlines and summaries collected in the past 24 hours. Produce a daily market
briefing (in Thai) with the following structure — use these exact Thai headers:

<b>📊 ภาพรวมตลาด</b>
[🟢/🔴/🟡 Bullish/Bearish/Mixed — one sentence rationale]

<b>🏛 ปัจจัยมหภาคสำคัญ</b>
• [Driver 1 with data point]
• [Driver 2 with data point]
• [Driver 3 with data point]

<b>📈 ข่าวบริษัทเด่น</b>
• [Ticker + event + impact]
• ...

<b>⚠️ จับตาวันพรุ่งนี้</b>
[One sentence: scheduled events — earnings calls, Fed speakers, data releases]

--- NEWS FEED START ---
{articles}
--- NEWS FEED END ---
""".strip()

ONDEMAND_PROMPT_TEMPLATE = """
Today is {date} (เวลาประเทศไทย, UTC+7). The user requested an on-demand digest
{target_text}. Produce a compact briefing (in Thai) — shorter than the scheduled
digest. Limit to 2000 characters. Use these exact Thai headers:

<b>📊 ภาพรวม:</b> [🟢/🔴/🟡 + one sentence]

<b>📌 ประเด็นเด่น</b>
• [3–5 most important bullet points, lead with the biggest mover]

<b>⚠️ จับตา:</b> [one forward-looking sentence]

Use the same Telegram HTML formatting rules from your system instructions.

--- NEWS FEED START ---
{articles}
--- NEWS FEED END ---
""".strip()

BREAKING_PROMPT_TEMPLATE = """
Today is {date} (เวลาประเทศไทย, UTC+7). The user requested a BREAKING NEWS digest
covering only the past {hours} hours. Write the bullets in Thai.

STRUCTURE OVERRIDE: Output bullet points only — no section headers, no
sentiment block, no Watch Tomorrow line. Lead with the most market-moving
item. One line per bullet maximum. Be ultra-concise.

--- NEWS FEED START ---
{articles}
--- NEWS FEED END ---
""".strip()


def build_prompt(
    articles: list[dict],
    mode: str = "scheduled",
    hours_back: int | None = None,
    target: str | None = None,
    forecasts: list[dict] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    date = _thai_date(now)
    articles_block = _format_articles(articles)
    extras = _forecast_block(forecasts)

    if mode == "breaking":
        return BREAKING_PROMPT_TEMPLATE.format(
            date=date,
            hours=hours_back or 2,
            articles=articles_block,
        ) + extras
    if mode == "ondemand":
        target_text = f"specifically for '{target.upper()}'" if target else "for all watchlist sectors"
        return ONDEMAND_PROMPT_TEMPLATE.format(date=date, target_text=target_text, articles=articles_block) + extras
    return SCHEDULED_PROMPT_TEMPLATE.format(date=date, articles=articles_block) + extras


def _format_articles(articles: list[dict]) -> str:
    now = datetime.now(timezone.utc)
    lines = []
    for i, a in enumerate(articles, 1):
        title = a.get("title", "").strip()
        summary = a.get("summary", "").strip()
        source = a.get("source", "")
        published = a.get("published_utc")

        age_str = ""
        if published:
            try:
                pub_dt = datetime.fromisoformat(published)
                mins = int((now - pub_dt).total_seconds() / 60)
                age_str = f" {mins}m ago" if mins < 60 else f" {mins // 60}h ago"
            except Exception:
                pass

        body = f"{title}. {summary}" if summary else title
        lines.append(f"[{i}] ({source}{age_str}) {body}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Multi-agent prompts — Filter → Analyst → Editor
# ---------------------------------------------------------------------------

_FILTER_AGENT_SYSTEM_TEMPLATE = """
You are a financial news relevance scorer for a US equity investor.
Score each article 1–10 on its potential to move stock prices:
  9–10 = Breaking: Fed rate decision, major earnings beat/miss, large M&A announcement
  7–8  = High: Guidance change, analyst upgrade/downgrade with price target, key economic data release
  5–6  = Medium: Minor company news, routine scheduled event, sector rotation commentary
  1–4  = Low: Opinion piece, soft/vague news, press release fluff, duplicate angle

SCORING NUANCE:
- Weight by surprise: a large deviation from consensus (big guidance cut, sharp
  beat/miss) scores higher than an in-line result.
- Favor forward-looking catalysts (guidance, outlook, scheduled decisions) over
  already-released, backward-looking recaps of the same event.
- A second article on an event already represented in the batch is a duplicate —
  score it Low.

BONUS: Add +1 (cap at 10) for any article that directly mentions a watchlist ticker.
User's watchlist tickers: {watchlist_tickers}

Return ONLY a JSON array with one object per article.
Each object must have exactly two integer fields: "index" (0-based) and "score".
Example: [{{"index": 0, "score": 9}}, {{"index": 1, "score": 4}}]
""".strip()


def build_filter_system(watchlist: dict[str, list[str]] | None = None) -> str:
    if watchlist is None:
        watchlist = _get_watchlist()
    return _FILTER_AGENT_SYSTEM_TEMPLATE.format(watchlist_tickers=_flat_tickers(watchlist))


TARGET_EXTRACTOR_SYSTEM = """
You extract analyst price targets from US financial news for a stock tracker.

Output ONLY cases where an article EXPLICITLY states a numeric analyst/firm price
target for a specific stock (e.g. "Morgan Stanley raised its price target to
$200", "RBC set a $180 PT"). Be strict:
- Extract only an explicit number stated in the text. NEVER infer, estimate, or
  invent a figure. If an article has no explicit price target, output nothing for it.
- Vague phrases ("could double", "sees upside", "bullish") are NOT targets — skip.
- Use the official US ticker symbol. If the ticker is unclear, skip the item.
- Capture the issuing firm when stated (for traceability).

Return ONLY a JSON array, one object per target found (empty array [] if none):
[{"ticker": "NVDA", "target": 200, "firm": "Morgan Stanley"}]
Each object: "ticker" (string), "target" (number), "firm" (string, "" if unknown).
""".strip()

TARGET_EXTRACTOR_PROMPT_TEMPLATE = """
Extract explicit analyst price targets from these {n} articles.
Return a JSON array (empty [] if none are explicitly stated).

--- ARTICLES ---
{articles}
""".strip()


def build_target_extractor_prompt(articles: list[dict]) -> str:
    return TARGET_EXTRACTOR_PROMPT_TEMPLATE.format(
        n=len(articles), articles=_format_articles(articles)
    )


ANALYST_AGENT_SYSTEM = """
You are a senior equity analyst producing a structured market briefing for a
sophisticated self-directed investor. Your output goes to a Telegram editor —
use plain text with the exact section labels below (the editor depends on them).

Output this exact structure (omit a section only if truly empty):

MARKET SENTIMENT: [🟢/🔴/🟡 Bullish/Bearish/Mixed — one sentence with a key data point]

MACRO DRIVERS:
- [Driver + specific data, e.g. "CPI +3.4% YoY vs 3.2% est — sticky inflation narrative"]
- [Driver 2]
- [Driver 3 if relevant]

COMPANY NEWS:
[Group by sector. Format each group as:]
[CATEGORY NAME]
- TICKER: event + quantified impact
- TICKER: event + quantified impact

WATCH TOMORROW:
[One sentence: scheduled earnings, Fed speakers, or data releases]

QUALITY BAR:
- Weight impact in this order: monetary policy (Fed/FOMC) > broad macro data
  (CPI, jobs, GDP) > sector/regulatory shifts > single-company news.
- Quantify against consensus: beat/miss magnitude, bps moves, % change — not
  just direction.
- Flag sector rotation when the news points to it (e.g. defensive rotation on
  growth fears).
- Distinguish a structural catalyst from one-day noise; say which.
- Neutral tone: report facts, no cheerleading. Separate confirmed from speculative.
- PRICED IN: Prices already embed expectations. When an article gives the
  consensus/estimate, label the news a genuine surprise (beat/miss) or already
  expected (priced in) and say which. If no consensus figure is given, do NOT
  invent what was expected — state the fact neutrally.

FORECAST TRACKING:
- If a "FORECAST TRACKING" section is supplied and today's news relates to a
  tracked ticker, add the supplied distance figure (e.g. "price is 94% of the
  way to the $200 target set 90d ago"). Use only the given numbers; never invent
  a target, and do not equate "near target" with "priced in".

Be concise and data-driven. Include ticker symbols. No disclaimers.
""".strip() + _THAI_DIRECTIVE


_EDITOR_AGENT_SYSTEM_TEMPLATE = """
You are a Telegram message editor. Format the provided market analysis into a
single Telegram message using ONLY these HTML tags: <b>bold</b> <i>italic</i>

Rules:
• Bullet points use the • character (never - or *)
• Never use Markdown syntax (no *, _, #, etc.)
• Keep total length under 3800 characters
• Sentiment emoji: 🟢 Bullish | 🔴 Bearish | 🟡 Mixed
• Add ⭐ immediately after the ticker symbol for any watchlist ticker.
  Watchlist tickers: {watchlist_tickers}

Required structure — use exactly these Thai section headers:
<b>📊 ภาพรวมตลาด</b>
[emoji + one-sentence rationale]

<b>🏛 ปัจจัยมหภาคสำคัญ</b>
• ...

<b>📈 ข่าวบริษัทเด่น</b>
[Group under bolded labels, e.g. <b>🤖 AI/Tech:</b>, <b>🛒 Consumer:</b>, <b>🏦 Finance:</b>]
• TICKER ⭐: event — impact

<b>⚠️ จับตาวันพรุ่งนี้</b>
[one sentence]

PRESENTATION:
• Lead with the single biggest market mover.
• Keep bullets in parallel structure; one idea per bullet.
• Use precise verbs and concrete numbers, not hype.
""".strip()


def build_editor_system(watchlist: dict[str, list[str]] | None = None) -> str:
    if watchlist is None:
        watchlist = _get_watchlist()
    return _EDITOR_AGENT_SYSTEM_TEMPLATE.format(watchlist_tickers=_flat_tickers(watchlist)) + _THAI_DIRECTIVE


FILTER_AGENT_PROMPT_TEMPLATE = """
Score the following {n} articles by market-moving impact. Return a JSON array
with {n} objects: [{{"index": 0, "score": X}}, ...].

--- ARTICLES ---
{articles}
""".strip()

ANALYST_AGENT_PROMPT_TEMPLATE = """
Today is {date} (เวลาประเทศไทย, UTC+7). Produce a structured market briefing from
these {n} high-impact articles.

--- ARTICLES ---
{articles}
""".strip()

EDITOR_AGENT_PROMPT_TEMPLATE = """
Reformat the following market analysis into the required Telegram HTML structure.{history_block}

--- ANALYSIS ---
{analysis}
""".strip()

_HISTORY_BLOCK_TEMPLATE = """

RECENT DIGEST HISTORY (last {n} scheduled run(s) — oldest first):
{history}

MEMORY INSTRUCTIONS:
• Do not repeat stories already covered in recent digests. Drop them entirely.
• If the same ticker appears again today with new developments, frame it as a continuation: "TICKER continues its [trend] — [today's new detail]".
• Check the Watch Tomorrow line from the most recent digest — if today's news resolves it, note the outcome briefly (e.g. "materialised", "missed", "pending").
""".strip()


def build_filter_prompt(articles: list[dict]) -> str:
    return FILTER_AGENT_PROMPT_TEMPLATE.format(
        n=len(articles),
        articles=_format_articles(articles),
    )


def build_analyst_prompt(
    articles: list[dict],
    forecasts: list[dict] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    date = _thai_date(now)
    return ANALYST_AGENT_PROMPT_TEMPLATE.format(
        date=date,
        n=len(articles),
        articles=_format_articles(articles),
    ) + _forecast_block(forecasts)


def _format_history(history: list[dict]) -> str:
    lines = []
    for entry in reversed(history):  # oldest first
        date = entry["ran_at"][:10]
        clean = _HTML_TAG_RE.sub("", entry["digest_text"])
        preview = " ".join(clean.split())[:300]
        lines.append(f"[{date}]: {preview}…")
    return "\n".join(lines)


def build_editor_prompt(analysis: str, history: list[dict] | None = None) -> str:
    if history:
        history_block = "\n\n" + _HISTORY_BLOCK_TEMPLATE.format(
            n=len(history),
            history=_format_history(history),
        )
    else:
        history_block = ""
    return EDITOR_AGENT_PROMPT_TEMPLATE.format(analysis=analysis, history_block=history_block)


# ---------------------------------------------------------------------------
# /ask Q&A prompt
# ---------------------------------------------------------------------------

ASK_SYSTEM_PROMPT = """
You are an expert financial analyst answering a specific question from a
self-directed US equity investor.

Rules:
• Ground your answer in the provided news articles when they are relevant.
  If the articles don't cover the topic, answer from your general knowledge
  and say so briefly.
• Use Telegram HTML only: <b>bold</b> <i>italic</i>. No Markdown.
• Bullet points use the • character.
• Be concise — stay under 3800 characters.
• No disclaimers or suggestions to consult a financial advisor.
• Include ticker symbols in parentheses, e.g. Apple (AAPL).
• Quantify where possible: percentages, basis points, dollar amounts.
""".strip() + _THAI_DIRECTIVE

ASK_PROMPT_TEMPLATE = """
Today is {date} (เวลาประเทศไทย, UTC+7).

The investor's question: {question}

Below are the latest US financial news articles collected in the past 24 hours.
Use them as context where relevant.

--- NEWS FEED START ---
{articles}
--- NEWS FEED END ---

Answer the question directly and concisely.
""".strip()


def build_ask_prompt(question: str, articles: list[dict]) -> str:
    now = datetime.now(timezone.utc)
    date = _thai_date(now)
    articles_block = _format_articles(articles) if articles else "No articles available."
    return ASK_PROMPT_TEMPLATE.format(date=date, question=question, articles=articles_block)
