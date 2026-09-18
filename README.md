# Dark Pool + GEX Scanner

Built for **Unusual Whales Hackathon #1** (deadline 2026-10-23, 11:59pm ET).

A CLI tool that pulls a ticker's real dark pool prints, dark-pool price
levels, dealer gamma exposure (GEX) structure, and options flow alerts
from the [Unusual Whales public API](https://api.unusualwhales.com/docs),
then surfaces three things raw data doesn't show on its own:

1. **Block prints** — real dark-pool trades at or above a $ notional
   floor (default $200k), largest first.
2. **Price-level / GEX confluence** — dark-pool price levels that sit
   within a tight % of a GEX structural level (call wall, put wall,
   gamma flip, gamma magnet). A heavy dark-pool level lining up with a
   dealer-gamma structural level is a stronger read than either alone.
3. **Flow bias** — aggregate bullish/bearish premium tilt across recent
   flow alerts (ask-side call buying and bid-side put selling both read
   bullish; the reverse reads bearish).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in UNUSUAL_WHALES_API_KEY (trial keys work)
```

Get a trial key at https://unusualwhales.com/public-api#pricing.

## Usage

```bash
python main.py scan SPY
python main.py scan SPY --date 2026-09-17 --block-floor 500000
python main.py recent --min-premium 100000
```

## Endpoints used

All from `https://api.unusualwhales.com` (Bearer auth):
- `GET /api/darkpool/recent`
- `GET /api/darkpool/{ticker}`
- `GET /api/darkpool/{ticker}/price-levels`
- `GET /api/stock/{ticker}/gex-levels`
- `GET /api/option-trades/flow-alerts`

## Project layout

- `src/uw_client.py` — thin Bearer-auth REST client, one retry on 429.
- `src/models.py` — parsed dataclasses for each endpoint family.
- `src/darkpool.py`, `src/gex.py`, `src/flow.py` — one function per
  endpoint, returning parsed models.
- `src/analysis.py` — the block-print / confluence / flow-bias logic
  above. Pure functions, no network calls, fully unit-tested.
- `tests/` — parsing + analysis logic verified against fixtures built
  from the real documented API response shape (no live key required to
  run `pytest`).
- `main.py` — CLI (`scan <ticker>`, `recent`).

## Status

Scaffolded against Unusual Whales' documented API schema before a trial
key existed. `src/darkpool.py`'s handling of whether list responses are
wrapped in `{"data": [...]}` or returned bare is defensive (checks both)
since the docs' operation pages didn't show a full example response —
confirm against a real response once a key lands and simplify if needed.
Not yet verified against live data.
