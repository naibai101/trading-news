import asyncio
import feedparser
import httpx
import os
import time
import google.generativeai as genai
from fastapi import FastAPI, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateparser
from typing import Optional
import re

app = FastAPI(title="Swing Trader News Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Credible, diverse sources — financial press, wire services, regulators
FEEDS = [
    # Wire services (neutral)
    {"name": "Reuters Business", "url": "https://feeds.reuters.com/reuters/businessNews", "category": "macro", "bias": "center"},
    {"name": "AP Markets", "url": "https://rsshub.app/apnews/topics/financial-markets", "category": "macro", "bias": "center"},
    # Financial press
    {"name": "MarketWatch", "url": "https://feeds.marketwatch.com/marketwatch/marketpulse/", "category": "markets", "bias": "center"},
    {"name": "Barron's", "url": "https://www.barrons.com/xml/rss/3_7014.xml", "category": "markets", "bias": "center"},
    {"name": "Investor's Business Daily", "url": "https://www.investors.com/feed/", "category": "markets", "bias": "center-right"},
    # Macro / economy
    {"name": "Calculated Risk", "url": "https://www.calculatedriskblog.com/feeds/posts/default", "category": "macro", "bias": "center"},
    {"name": "WSJ Markets", "url": "https://feeds.wsj.com/xml/rss/3_7031.xml", "category": "macro", "bias": "center-right"},
    # Earnings & corporate
    {"name": "SeekingAlpha", "url": "https://seekingalpha.com/market_currents.xml", "category": "earnings", "bias": "varies"},
    {"name": "Motley Fool", "url": "https://www.fool.com/feeds/index.aspx", "category": "earnings", "bias": "center"},
    # Sector / tech
    {"name": "CNBC Top News", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "category": "sector", "bias": "center-left"},
    {"name": "The Verge Tech", "url": "https://www.theverge.com/rss/index.xml", "category": "sector", "bias": "center-left"},
    # Rates / Fed / regulators
    {"name": "Fed Reserve Speeches", "url": "https://www.federalreserve.gov/feeds/speeches.xml", "category": "fed", "bias": "official"},
    {"name": "SEC Press Releases", "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=&dateb=&owner=include&count=10&search_text=&output=atom", "category": "regulatory", "bias": "official"},
    # Commodities / global macro
    {"name": "FT Markets", "url": "https://www.ft.com/markets?format=rss", "category": "macro", "bias": "center"},
    {"name": "Bloomberg Economics", "url": "https://feeds.bloomberg.com/economics/news.rss", "category": "macro", "bias": "center"},
]

TRADING_KEYWORDS = [
    "stock", "market", "shares", "nasdaq", "s&p", "dow", "earnings", "fed", "rate",
    "inflation", "gdp", "jobs", "employment", "treasury", "yield", "rally", "sell",
    "bull", "bear", "ipo", "merger", "acquisition", "quarterly", "revenue", "profit",
    "loss", "guidance", "forecast", "outlook", "sector", "commodity", "oil", "gold",
    "dollar", "currency", "trade", "tariff", "interest", "recession", "growth",
    "bank", "financial", "dividend", "buyback", "short", "options", "futures",
]

# High-signal catalyst phrases — price-moving corporate events
CATALYST_PHRASES = [
    # Earnings
    "beats estimates", "misses estimates", "beats expectations", "misses expectations",
    "earnings beat", "earnings miss", "earnings surprise", "blowout quarter",
    "raises guidance", "cuts guidance", "raises outlook", "lowers outlook",
    "guidance raised", "guidance cut", "guidance withdrawn",
    "revenue beat", "revenue miss", "eps beat", "eps miss",
    # M&A
    "merger", "acquisition", "acquires", "acquired", "to acquire",
    "buyout", "takeover", "going private", "deal to buy", "agrees to buy",
    "merger agreement", "definitive agreement",
    # FDA / biotech
    "fda approval", "fda approved", "fda approves", "fda clears", "fda rejects",
    "fda rejection", "fda grants", "breakthrough therapy", "accelerated approval",
    "phase 3", "clinical trial results", "nda submission", "bla submission",
    # Corporate events
    "bankruptcy", "chapter 11", "chapter 7", "files for bankruptcy",
    "stock split", "reverse split", "share buyback", "buyback program",
    "special dividend", "dividend cut", "dividend suspended", "dividend increase",
    "going public", "prices ipo", "ipo priced",
    # Analyst / ratings
    "upgrade", "downgrade", "initiates coverage", "raises price target",
    "cuts price target", "price target raised", "price target cut",
    "outperform", "underperform", "buy rating", "sell rating",
    # Legal / regulatory
    "sec investigation", "sec charges", "doj investigation", "class action",
    "settlement", "fine", "penalty", "indicted", "subpoena",
    # Management
    "ceo resigns", "ceo fired", "ceo steps down", "cfo resigns",
    "management change", "leadership change",
    # Other catalysts
    "short squeeze", "halted", "trading halted", "data breach",
    "major contract", "contract awarded", "partnership agreement",
    "product recall", "recall", "plant shutdown", "layoffs announced",
    "restructuring", "spinoff", "spin-off", "divestiture",
]

# Yahoo Finance screener IDs for real-time movers
YAHOO_SCREENERS = ["day_gainers", "day_losers", "most_actives"]

_mover_tickers: set[str] = set()
_mover_data: dict = {}  # ticker -> {pct_change, volume, price}
_mover_tickers_fetched_at: float = 0.0


async def fetch_mover_tickers(client: httpx.AsyncClient) -> tuple[set[str], dict]:
    global _mover_tickers, _mover_data, _mover_tickers_fetched_at
    import time

    # Cache for 10 minutes
    if time.time() - _mover_tickers_fetched_at < 600 and _mover_tickers:
        return _mover_tickers, _mover_data

    ticker_data: dict = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    for screener in YAHOO_SCREENERS:
        url = (
            f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
            f"?scrIds={screener}&count=30&region=US&lang=en-US"
        )
        try:
            resp = await client.get(url, headers=headers, timeout=6.0)
            data = resp.json()
            quotes = (
                data.get("finance", {})
                    .get("result", [{}])[0]
                    .get("quotes", [])
            )
            for q in quotes:
                sym = q.get("symbol", "").upper().strip()
                if sym and re.match(r"^[A-Z]{1,5}$", sym):
                    ticker_data[sym] = {
                        "pct_change": round(q.get("regularMarketChangePercent", 0), 2),
                        "volume": q.get("regularMarketVolume", 0),
                        "price": round(q.get("regularMarketPrice", 0), 2),
                    }
        except Exception:
            pass

    if ticker_data:
        _mover_tickers = set(ticker_data.keys())
        _mover_data = ticker_data
        _mover_tickers_fetched_at = time.time()

    return _mover_tickers, _mover_data


def is_catalyst(text: str) -> bool:
    t = text.lower()
    return any(phrase in t for phrase in CATALYST_PHRASES)


# Words that look like tickers but aren't — common in financial headlines
TICKER_BLOCKLIST = {
    # Articles / pronouns / conjunctions
    "A","I","AM","AN","AS","AT","BE","BY","DO","GO","HE","IF","IN","IS","IT",
    "ME","MY","NO","OF","OK","ON","OR","SO","TO","UP","US","WE",
    "AND","ARE","BUT","CAN","DID","FOR","GET","GOT","HAS","HAD","HIM","HIS",
    "HOW","ITS","LET","MAY","NOT","NOW","OFF","OLD","ONE","OUR","OUT","OWN",
    "PUT","SAY","SHE","THE","TOO","TWO","USE","WAS","WAY","WHO","WHY",
    "WILL","WITH","ALSO","BEEN","FROM","HAVE","JUST","MORE","MOST","OVER",
    "SAID","SUCH","THAN","THAT","THEM","THEN","THEY","THIS","VERY","WANT",
    "WERE","WHAT","WHEN","YOUR","AMID","AFTER","ABOVE","BELOW","SINCE",
    "UNTIL","WHILE","ABOUT","COULD","WOULD","SHOULD",
    # Common verb forms used as uppercase in headlines
    "ADDS","CUTS","GETS","PUTS","ROSE","FELL","HITS","SETS","SEES","EYES",
    "WINS","ENDS","TOPS","SAYS","MAKES","TAKES","LEADS","BEATS","LOSES",
    "PLANS","SHOWS","FACES","HOLDS","WARNS","BACKS","NEEDS","KEEPS","RISES",
    "FALLS","DROPS","GAINS","SURGES","JUMPS","SLIDES","SINKS","SOARS",
    # Financial/market acronyms that aren't tickers
    "CEO","CFO","COO","CTO","IPO","SEC","FED","GDP","CPI","PPI","EPS","ETF",
    "AUM","ROI","YOY","QOQ","YTD","ATH","ATL","RSI","SMA","EMA","MACD",
    "NYSE","CBOE","FOMC","OPEC","NATO","IMF","WTO","ECB","BOJ","RBI",
    # Misc headline words
    "LIVE","NEWS","HIGH","LOWS","RATE","BANK","CORP","LAST","NEXT","FULL",
    "HALF","AMID","INTO","ONTO","UPON","EVEN","EACH","BOTH","MANY","MUCH",
    "ONLY","SOME","THEY","THEM","BEEN","DOES","DONE","GAVE","GIVE","GONE",
    "GROW","GREW","KNOW","KNEW","SHOW","SHOWN","TAKE","TOOK","COME","CAME",
    "HOLD","HELD","SELL","SOLD","FIND","FOUND","HEAR","HEARD","KEEP","KEPT",
    "SEND","SENT","SPAN","SIGN","DEAL","RISK","LACK","LOSS","GAIN","COST",
    "RISE","FALL","YEAR","WEEK","DAYS","TIME","DATA","FIRM","FUND","BOND",
    "DEBT","CASH","LOAN","SALE","UNIT","SITE","TEAM","ROLE","TYPE","FORM",
    "AI","IT","UK","EU","US",
}


def mentions_ticker(text: str, tickers: set[str]) -> bool:
    """Match tickers that appear already-uppercase in original text."""
    words = set(re.findall(r"\b[A-Z]{2,5}\b", text))  # no .upper() — match original case
    return bool((words - TICKER_BLOCKLIST) & tickers)


def is_trading_relevant(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in TRADING_KEYWORDS)


def market_session() -> dict:
    now = datetime.now(timezone.utc)
    # ET offset: UTC-5 (EST) / UTC-4 (EDT) — approximate with UTC-4 for summer
    et_hour = (now.hour - 4) % 24
    et_minute = now.minute

    total_minutes = et_hour * 60 + et_minute

    pre_start = 4 * 60      # 4:00 AM ET
    open_start = 9 * 60 + 30  # 9:30 AM ET
    close_end = 16 * 60     # 4:00 PM ET
    post_end = 20 * 60      # 8:00 PM ET

    if pre_start <= total_minutes < open_start:
        session = "pre"
        label = "Pre-Market"
        color = "#a78bfa"
    elif open_start <= total_minutes < close_end:
        session = "open"
        label = "Market Open"
        color = "#34d399"
    elif close_end <= total_minutes < post_end:
        session = "post"
        label = "After-Hours"
        color = "#f59e0b"
    else:
        session = "closed"
        label = "Market Closed"
        color = "#94a3b8"

    return {"session": session, "label": label, "color": color, "et_time": f"{et_hour:02d}:{et_minute:02d} ET"}


async def fetch_feed(client: httpx.AsyncClient, feed_meta: dict) -> list:
    items = []
    try:
        resp = await client.get(feed_meta["url"], timeout=8.0, follow_redirects=True)
        parsed = feedparser.parse(resp.text)
        for entry in parsed.entries[:8]:
            title = entry.get("title", "").strip()
            summary = re.sub(r"<[^>]+>", "", entry.get("summary", entry.get("description", ""))).strip()[:300]
            link = entry.get("link", "")
            pub = entry.get("published", entry.get("updated", ""))

            try:
                pub_dt = dateparser.parse(pub)
                pub_iso = pub_dt.isoformat() if pub_dt else ""
            except Exception:
                pub_iso = ""

            if not title or not link:
                continue
            if not is_trading_relevant(title + " " + summary):
                continue

            items.append({
                "title": title,
                "summary": summary,
                "link": link,
                "published": pub_iso,
                "source": feed_meta["name"],
                "category": feed_meta["category"],
                "bias": feed_meta["bias"],
            })
    except Exception:
        pass
    return items


@app.get("/api/news")
async def get_news():
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 SwingTraderDashboard/1.0"}) as client:
        feed_tasks = [fetch_feed(client, feed) for feed in FEEDS]
        feed_results, (mover_tickers, mover_data) = await asyncio.gather(
            asyncio.gather(*feed_tasks),
            fetch_mover_tickers(client),
        )

    all_items = []
    for batch in feed_results:
        all_items.extend(batch)

    # Deduplicate by title similarity
    seen_titles = set()
    deduped = []
    for item in all_items:
        key = re.sub(r"\W+", "", item["title"].lower())[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            deduped.append(item)

    # Drop articles older than 48 hours — keep undated ones (likely fresh from feed)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    fresh = []
    for item in deduped:
        if not item["published"]:
            fresh.append(item)
            continue
        try:
            pub_dt = dateparser.parse(item["published"])
            if pub_dt:
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt >= cutoff:
                    fresh.append(item)
        except Exception:
            fresh.append(item)
    deduped = fresh

    # Tag each item with catalyst flag + matched mover ticker data
    for item in deduped:
        full_text = item["title"] + " " + (item["summary"] or "")
        item["is_catalyst"] = is_catalyst(full_text)

        words = set(re.findall(r"\b[A-Z]{2,5}\b", full_text))  # match original case only
        mentioned = (words - TICKER_BLOCKLIST) & mover_tickers
        if mentioned:
            best = max(mentioned, key=lambda t: mover_data.get(t, {}).get("volume", 0))
            item["ticker"]        = best
            item["ticker_volume"] = mover_data[best]["volume"]
            item["ticker_pct"]    = mover_data[best]["pct_change"]
            item["ticker_price"]  = mover_data[best]["price"]
            item["mentions_mover"] = True
        else:
            item["ticker"]        = None
            item["ticker_volume"] = 0
            item["ticker_pct"]    = None
            item["ticker_price"]  = None
            item["mentions_mover"] = False

        item["is_mover_news"] = item["is_catalyst"] or item["mentions_mover"]

    # Sort by volume of the mentioned ticker (high-volume stocks bubble up)
    deduped.sort(key=lambda x: x.get("ticker_volume", 0), reverse=True)

    # Build mover list sorted by volume for the UI strip
    mover_list = sorted(
        [{"ticker": t, **d} for t, d in mover_data.items()],
        key=lambda x: x["volume"],
        reverse=True,
    )

    return JSONResponse({
        "items": deduped,
        "mover_list": mover_list,
        "session": market_session(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total": len(deduped),
    })


@app.get("/api/session")
async def get_session():
    return JSONResponse(market_session())


_brief_cache: dict = {}
_brief_cache_key: str = ""
_brief_cached_at: float = 0.0

BRIEF_CONFIGS = {
    "pre": {
        "label": "Morning Brief",
        "icon": "🌅",
        "focus": (
            "The market opens soon. Focus on overnight futures moves, pre-market movers, "
            "key economic data releases scheduled for today, and the top catalysts to watch "
            "when the bell rings. Help the trader decide what to monitor at open."
        ),
    },
    "open": {
        "label": "Midday Brief",
        "icon": "📊",
        "focus": (
            "The market is live. Focus on what is actively moving and why, "
            "any intraday catalysts or sector rotations, and what to watch into the close."
        ),
    },
    "post": {
        "label": "Evening Brief",
        "icon": "🌙",
        "focus": (
            "The market has closed. Recap today's biggest movers and the reasons behind them. "
            "Highlight any after-hours earnings or news. Help the trader decide what to "
            "research tonight and what setups to watch at tomorrow's open."
        ),
    },
    "closed": {
        "label": "Market Brief",
        "icon": "📋",
        "focus": (
            "The market is closed. Summarise the most important developments from the latest "
            "headlines and flag what to watch for the next trading session."
        ),
    },
}


@app.post("/api/brief")
async def generate_brief(x_api_key: Optional[str] = Header(default=None)):
    global _brief_cache, _brief_cache_key, _brief_cached_at

    api_key = x_api_key or os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "no_key"}, status_code=200)

    session = market_session()
    cfg = BRIEF_CONFIGS[session["session"]]

    # Cache per key + session for 30 minutes
    cache_key = api_key[-8:] + session["session"]
    if (
        _brief_cache
        and _brief_cache_key == cache_key
        and time.time() - _brief_cached_at < 1800
    ):
        return JSONResponse(_brief_cache)

    # Fetch latest news
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 SwingTraderDashboard/1.0"}) as client:
        feed_tasks = [fetch_feed(client, feed) for feed in FEEDS]
        feed_results, (mover_tickers, mover_data) = await asyncio.gather(
            asyncio.gather(*feed_tasks),
            fetch_mover_tickers(client),
        )

    all_items: list = []
    for batch in feed_results:
        all_items.extend(batch)

    seen: set = set()
    deduped: list = []
    for item in all_items:
        k = re.sub(r"\W+", "", item["title"].lower())[:60]
        if k not in seen:
            seen.add(k)
            deduped.append(item)

    def _sort(i):
        try:
            return dateparser.parse(i["published"]) if i["published"] else datetime.min.replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    deduped.sort(key=_sort, reverse=True)

    mover_lines = []
    for sym, d in sorted(mover_data.items(), key=lambda x: x[1]["volume"], reverse=True)[:10]:
        sign = "+" if d["pct_change"] >= 0 else ""
        mover_lines.append(f"  {sym}: {sign}{d['pct_change']:.2f}% | Vol {d['volume']:,}")

    headline_lines = []
    for item in deduped[:50]:
        ticker_note = f" [{item['ticker']}]" if item.get("ticker") else ""
        headline_lines.append(f"- [{item['category'].upper()}]{ticker_note} {item['title']}")

    prompt = f"""You are a concise market analyst writing a {cfg['label']} for a swing trader.

{cfg['focus']}

Today's top movers by volume:
{chr(10).join(mover_lines) if mover_lines else "  (no live data — market closed)"}

Current headlines ({len(headline_lines)} stories):
{chr(10).join(headline_lines)}

Write the brief in exactly this structure. One tight sentence per bullet, zero filler:

**Market Mood**
[One sentence: overall tone, risk-on or risk-off, what is driving it]

**Top Movers**
[3–5 bullets. Format: TICKER — what happened and the likely cause]

**Macro & Rates**
[2–3 bullets: Fed, yields, inflation, GDP, or global macro themes worth tracking]

**What to Watch**
[2–3 bullets: upcoming catalysts, earnings, or setups that could create swing opportunities]"""

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction="You are a concise swing trading market analyst. Write tight, specific, actionable briefs with zero fluff.",
        )
        response = model.generate_content(prompt)
        brief_text = response.text
    except Exception as e:
        err = str(e)
        if "API_KEY_INVALID" in err or "API key" in err.lower():
            return JSONResponse({"error": "bad_key"}, status_code=200)
        return JSONResponse({"error": err}, status_code=200)

    result = {
        "brief": brief_text,
        "brief_label": cfg["label"],
        "brief_icon": cfg["icon"],
        "session": session["session"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "story_count": len(deduped),
    }
    _brief_cache = result
    _brief_cache_key = cache_key
    _brief_cached_at = time.time()
    return JSONResponse(result)


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


app.mount("/static", StaticFiles(directory="static"), name="static")
