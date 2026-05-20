import asyncio
import feedparser
import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
from dateutil import parser as dateparser
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
_mover_tickers_fetched_at: float = 0.0


async def fetch_mover_tickers(client: httpx.AsyncClient) -> set[str]:
    global _mover_tickers, _mover_tickers_fetched_at
    import time

    # Cache for 10 minutes
    if time.time() - _mover_tickers_fetched_at < 600 and _mover_tickers:
        return _mover_tickers

    tickers: set[str] = set()
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
                    tickers.add(sym)
        except Exception:
            pass

    if tickers:
        _mover_tickers = tickers
        _mover_tickers_fetched_at = time.time()

    return _mover_tickers


def is_catalyst(text: str) -> bool:
    t = text.lower()
    return any(phrase in t for phrase in CATALYST_PHRASES)


def mentions_ticker(text: str, tickers: set[str]) -> bool:
    """Check if text contains any mover ticker as a standalone word."""
    words = re.findall(r"\b[A-Z]{1,5}\b", text.upper())
    return bool(set(words) & tickers)


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
        feed_results, mover_tickers = await asyncio.gather(
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

    # Tag each item: is it a catalyst / mover story?
    for item in deduped:
        full_text = item["title"] + " " + (item["summary"] or "")
        item["is_catalyst"] = is_catalyst(full_text)
        item["mentions_mover"] = mentions_ticker(full_text, mover_tickers)
        item["is_mover_news"] = item["is_catalyst"] or item["mentions_mover"]

    # Sort by published date descending
    def sort_key(item):
        try:
            return dateparser.parse(item["published"]) if item["published"] else datetime.min.replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    deduped.sort(key=sort_key, reverse=True)

    return JSONResponse({
        "items": deduped,
        "mover_tickers": sorted(mover_tickers),
        "session": market_session(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total": len(deduped),
    })


@app.get("/api/session")
async def get_session():
    return JSONResponse(market_session())


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


app.mount("/static", StaticFiles(directory="static"), name="static")
