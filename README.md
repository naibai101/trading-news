# Trading News Dashboard

A pre/post-market news aggregator for swing traders. Pulls from credible, editorially-diverse sources to provide a balanced view of market-moving events.

## Sources

| Source | Category | Lean |
|---|---|---|
| Reuters Business | Macro | Center |
| AP Markets | Macro | Center |
| WSJ Markets | Macro | Center-Right |
| Financial Times | Macro | Center |
| Bloomberg Economics | Macro | Center |
| Calculated Risk | Macro | Center |
| MarketWatch | Markets | Center |
| Barron's | Markets | Center |
| Investor's Business Daily | Markets | Center-Right |
| CNBC Top News | Sector | Center-Left |
| The Verge | Sector/Tech | Center-Left |
| Seeking Alpha | Earnings | Varies |
| Motley Fool | Earnings | Center |
| Federal Reserve Speeches | Fed/Rates | Official |
| SEC Press Releases | Regulatory | Official |

## Running locally

```bash
pip install -r requirements.txt
uvicorn main:app --port 8000 --reload
```

Or just double-click `start.bat`.

Open [http://localhost:8000](http://localhost:8000).

## Features

- Auto-refreshes every 5 minutes
- Pre-market / Market Open / After-Hours / Closed session indicator (ET)
- Filter by category: Macro, Markets, Earnings, Sectors, Fed/Rates, Regulatory
- Full-text search across headlines and summaries
- Source bias label on every card for editorial transparency
