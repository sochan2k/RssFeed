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
   basis points.
6. Add ⭐ immediately after the ticker symbol for any watchlist ticker, e.g. NVDA ⭐.
7. If no genuinely market-moving news exists, say so clearly in one sentence.

PROHIBITED: Do not add disclaimers, legal boilerplate, or suggestions to
consult a financial advisor. The user knows investing involves risk.
""".strip()


def build_system_prompt(watchlist: dict[str, list[str]] | None = None) -> str:
    """Build system prompt with the live watchlist injected."""
    if watchlist is None:
        watchlist = _get_watchlist()
    return _SYSTEM_PROMPT_TEMPLATE.format(watchlist_tickers=_flat_tickers(watchlist))


# ---------------------------------------------------------------------------
# User prompt templates (scheduled / ondemand / breaking)
# ---------------------------------------------------------------------------

SCHEDULED_PROMPT_TEMPLATE = """
Today is {date} (ICT, UTC+7). Below are the latest US financial news headlines
and summaries collected in the past 24 hours. Produce a daily market briefing
with the following structure:

<b>📊 Market Sentiment</b>
[🟢/🔴/🟡 Bullish/Bearish/Mixed — one sentence rationale]

<b>🏛 Top Macro Drivers</b>
• [Driver 1 with data point]
• [Driver 2 with data point]
• [Driver 3 with data point]

<b>📈 Key Company News</b>
• [Ticker + event + impact]
• ...

<b>⚠️ Watch Tomorrow</b>
[One sentence: scheduled events — earnings calls, Fed speakers, data releases]

--- NEWS FEED START ---
{articles}
--- NEWS FEED END ---
""".strip()

ONDEMAND_PROMPT_TEMPLATE = """
Today is {date} (ICT, UTC+7). The user requested an on-demand digest {target_text}.
Produce a compact briefing — shorter than the scheduled digest. Limit to 2000 characters.

Structure:
<b>📊 Sentiment:</b> [🟢/🔴/🟡 + one sentence]

<b>📌 Top Items</b>
• [3–5 most important bullet points, lead with the biggest mover]

<b>⚠️ Watch:</b> [one forward-looking sentence]

Use the same Telegram HTML formatting rules from your system instructions.

--- NEWS FEED START ---
{articles}
--- NEWS FEED END ---
""".strip()

BREAKING_PROMPT_TEMPLATE = """
Today is {date} (ICT, UTC+7). The user requested a BREAKING NEWS digest
covering only the past {hours} hours.

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
) -> str:
    now = datetime.now(timezone.utc)
    date = f"{now.strftime('%A, %B')} {now.day}, {now.year}"
    articles_block = _format_articles(articles)

    if mode == "breaking":
        return BREAKING_PROMPT_TEMPLATE.format(
            date=date,
            hours=hours_back or 2,
            articles=articles_block,
        )
    if mode == "ondemand":
        target_text = f"specifically for '{target.upper()}'" if target else "for all watchlist sectors"
        return ONDEMAND_PROMPT_TEMPLATE.format(date=date, target_text=target_text, articles=articles_block)
    return SCHEDULED_PROMPT_TEMPLATE.format(date=date, articles=articles_block)


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

Be concise and data-driven. Include ticker symbols. No disclaimers.
""".strip()


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

Required structure — use exactly these section headers:
<b>📊 Market Sentiment</b>
[emoji + one-sentence rationale]

<b>🏛 Top Macro Drivers</b>
• ...

<b>📈 Company News by Category</b>
[Group under bolded labels, e.g. <b>🤖 AI/Tech:</b>, <b>🛒 Consumer:</b>, <b>🏦 Finance:</b>]
• TICKER ⭐: event — impact

<b>⚠️ Watch Tomorrow</b>
[one sentence]
""".strip()


def build_editor_system(watchlist: dict[str, list[str]] | None = None) -> str:
    if watchlist is None:
        watchlist = _get_watchlist()
    return _EDITOR_AGENT_SYSTEM_TEMPLATE.format(watchlist_tickers=_flat_tickers(watchlist))


FILTER_AGENT_PROMPT_TEMPLATE = """
Score the following {n} articles by market-moving impact. Return a JSON array
with {n} objects: [{{"index": 0, "score": X}}, ...].

--- ARTICLES ---
{articles}
""".strip()

ANALYST_AGENT_PROMPT_TEMPLATE = """
Today is {date} (ICT, UTC+7). Produce a structured market briefing from these
{n} high-impact articles.

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


def build_analyst_prompt(articles: list[dict]) -> str:
    now = datetime.now(timezone.utc)
    date = f"{now.strftime('%A, %B')} {now.day}, {now.year}"
    return ANALYST_AGENT_PROMPT_TEMPLATE.format(
        date=date,
        n=len(articles),
        articles=_format_articles(articles),
    )


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
""".strip()

ASK_PROMPT_TEMPLATE = """
Today is {date} (ICT, UTC+7).

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
    date = f"{now.strftime('%A, %B')} {now.day}, {now.year}"
    articles_block = _format_articles(articles) if articles else "No articles available."
    return ASK_PROMPT_TEMPLATE.format(date=date, question=question, articles=articles_block)
