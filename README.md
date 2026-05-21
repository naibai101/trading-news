# Market News Dashboard

A pre/post-market news aggregator for swing traders. Pulls from credible, editorially-diverse sources and surfaces catalyst-driven stories tied to stocks with unusual volume activity.

## Sources

| Source | Category | Lean |
|---|---|---|
| Reuters Business | Macro & Policy | Center |
| AP Markets | Macro & Policy | Center |
| WSJ Markets | Macro & Policy | Center-Right |
| Financial Times | Macro & Policy | Center |
| Bloomberg Economics | Macro & Policy | Center |
| Calculated Risk | Macro & Policy | Center |
| Federal Reserve Speeches | Macro & Policy | Official |
| SEC Press Releases | Macro & Policy | Official |
| MarketWatch | Markets | Center |
| Barron's | Markets | Center |
| Investor's Business Daily | Markets | Center-Right |
| CNBC Top News | Sectors | Center-Left |
| The Verge | Sectors/Tech | Center-Left |
| Seeking Alpha | Earnings | Varies |
| Motley Fool | Earnings | Center |

## Features

- **Sidebar navigation** — filter by category (Macro & Policy, Markets, Earnings, Sectors) or view Movers only
- **Volume surge ranking** — movers sorted by `volume / 3-month avg volume`, not raw volume; a stock at 5x its average beats a large-cap at 1.1x
- **Catalyst detection** — articles tagged when they contain price-moving language (earnings beats, FDA approvals, M&A, analyst upgrades/downgrades, etc.)
- **Ticker search** — type any ticker symbol (e.g. `NVDA`) to find all recent articles mentioning that stock by symbol or company name, even if it is not a top mover
- **Today's movers strip** — live price, % change, dollar change, volume vs average, day high/low for top movers from Yahoo Finance
- **AI Market Brief** — session-aware brief powered by Gemini 2.5 Flash Lite
  - Morning Brief (pre-market), Midday Brief (market open), Evening Brief (after-hours), Market Brief (closed)
  - Generates fresh on every click — no stale cache
  - Last brief persists in `localStorage` and restores on page refresh
  - API key stored in browser `localStorage` — never sent to or stored on the server
- **48-hour recency filter** — articles older than 48 hours are dropped
- **Auto-refresh** every 5 minutes
- **Session indicator** — Pre-Market / Market Open / After-Hours / Closed (ET)

## Running locally

```bash
pip install -r requirements.txt
uvicorn main:app --port 8000 --reload
```

Or double-click `start.bat`.

Open [http://localhost:8000](http://localhost:8000).

## Deployment

Deployed on Render (free tier). Auto-deploys on push to `main`.

Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

To use the AI brief on Render, set the `GEMINI_API_KEY` environment variable in the Render dashboard, or enter the key directly in the dashboard via the 🔑 button.

## API Key

The Gemini API key can be provided two ways:

1. **In the dashboard** — click the 🔑 button in the Market Brief panel and paste your key. It is saved to browser `localStorage` and sent as a request header; the server never stores it.
2. **Environment variable** — set `GEMINI_API_KEY` on the server (e.g. Render environment variables). The server uses this as a fallback if no key is sent from the browser.

Get a free Gemini API key at [aistudio.google.com](https://aistudio.google.com).
