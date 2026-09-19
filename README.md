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
- `GET /api/stock/{ticker}/spot-exposures/strike`
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

## Comparing UW against ARGUS (optional)

`compare/` tests whether UW data adds anything over what an existing
trading system already records, using that system's own files read-only
(`--argus-root`, default the sibling `ai-trading-desk-2` checkout):

```bash
python -m compare.run gex                                  # ThetaData-derived SPY GEX regime vs UW net gamma, ~120 days
python -m compare.run darkpool --date 2026-09-18 --top 8   # do UW's prints contain the exchange-'D' >= $200k blocks the other system logged?
python -m compare.run flow --dates 2026-09-16,2026-09-18   # daily options-flow direction, per ticker
```

Output is aggregate statistics only; raw UW responses are never saved.
These measure *agreement*, not profitability -- whether the signals predict
anything is a separate forward-returns test.

## Research: does confluence actually matter?

The scanner's central idea -- a heavy dark-pool level lining up with a GEX
level is a stronger read than either alone -- is a hypothesis. `research/`
tests it as an event study:

```bash
python -m research.run --tickers SPY,QQQ,NVDA,TSLA --days 250
```

For each trading day D it pulls UW's dark-pool price levels and GEX levels,
labels them (`confluence`, `dp_only`, `gex_only`, plus a `placebo` shifted
+/-0.75%), and measures how price reacts when it first touches each level
on D+1: **hold** (rallies/falls 0.5 ATR off the level) vs **break** (goes
0.5 ATR through it first). Design choices that guard against fooling
ourselves:

- Levels come from day D, reaction is measured on D+1 -- no lookahead.
- ATR uses only bars before the touch; the touch bar is excluded from the
  outcome window (its range trivially spans the level).
- The unit of analysis is the ticker-day, not the level -- levels on the
  same day are not independent.
- Placebo levels show whether *any* level attracts reaction.
- On real SPY/QQQ M30 bars with ordinary levels (prior-day high/low) the
  harness returns hold rates of 45-51%, i.e. it does not manufacture an
  edge from nothing.

Expect a small confluence sample (it needs both signals at once), so only
a large effect will be distinguishable from noise; a null result is a
legitimate finding and is reported as one.

## Status

Scaffolded against Unusual Whales' documented API schema before a trial
key existed. **Not yet verified against live data.** Checklist for the
first real call:

- `src/darkpool.py` / `src/flow.py` handle list responses wrapped in
  `{"data": [...]}` or returned bare (the docs didn't show a full example
  for every endpoint) - confirm and simplify.
- `StrikeGamma.net()` assumes put gamma is returned already signed
  negative. The docs don't state the sign convention - if puts come back
  as positive magnitudes, net gamma and the "top strikes" ranking are wrong.
- `spot_gex_by_strike` reads only the first page (500 rows); wide chains
  may need `min_strike`/`max_strike` windowing or `page` pagination.
- `greek_exposure_history`'s `timeframe` values (YTD, 1D-2D, 1W-2W, 1M-2M,
  1Y-2Y) come straight from the docs with no stated semantics -- check which
  one returns Feb-Aug 2026 when the trial starts.
- Dark-pool `premium` semantics are undocumented (the docs call it option
  premium, which makes no sense for a stock print); notional is computed as
  price x size instead, and the test fixtures' `premium` values are arbitrary.
- The confluence and flow-bias heuristics are unvalidated hypotheses, not
  backtested edges.

API terms: Unusual Whales data is personal-use only and may not be
redistributed, so this repo ships only synthetic fixtures - never commit
real API responses.
