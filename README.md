# Black Lantern

**Where big money traded, where dealers have to hedge, and what price did about it -- on one chart.**

Built on the [Unusual Whales public API](https://api.unusualwhales.com/docs) for **UW Hackathon #1**.

Black Lantern pulls a ticker's dark-pool prints and dark-pool price levels, its dealer gamma (GEX) structure and its
intraday candles from Unusual Whales, and draws them together: the heaviest dark-pool levels and the call wall / put wall
/ gamma flip / gamma magnet as lines on the price chart, block prints as circles sized by dollar value, and the places where
a heavy dark-pool level sits right on a GEX level highlighted. By default the levels come from the **prior** session, so the
chart shows what was actually known going into the day, not a hindsight overlay.

It is also honest about what this data can and cannot do. Every claim below was tested, most of them pre-registered, and the
results -- including the ones that came back null -- are reported as they came out.

![Black Lantern chart (synthetic demo data)](docs/demo_chart.svg)

*The image above is the built-in demo, generated from synthetic data -- no real market data is committed to this repo
(Unusual Whales data is personal-use only).*

## 60-second quickstart

```bash
pip install -r requirements.txt
python main.py demo --open                      # full report from synthetic data, no API key needed
```

With an Unusual Whales key (trial keys work -- https://unusualwhales.com/public-api#pricing):

```bash
cp .env.example .env                            # put your UNUSUAL_WHALES_API_KEY in .env
python main.py scan SPY --html reports/spy.html --open
python main.py scan SPY --date 2026-09-22 --block-floor 5000000 --html reports/spy.html --open
python main.py recent --min-premium 1000000     # market-wide recent dark-pool blocks
```

`scan` prints a text summary and, with `--html`, writes a self-contained report (no external assets, works offline, light
and dark mode). Useful flags: `--candle-size 1m|5m|15m|30m|1h`, `--block-floor` (dollar floor for a "block"; raise it for
very liquid tickers like SPY), `--max-pages` (how far back to page dark-pool prints), `--same-day-levels` (draw the
session's own end-of-day levels instead -- labelled as hindsight on the chart).

## Reading the chart

| on the chart | what it is | from |
|---|---|---|
| candles | the session's regular-hours price | `ohlc/{candle_size}` |
| blue bands | the 5 heaviest dark-pool price levels of the prior session; thicker = more dark-pool volume | `darkpool/{ticker}/price-levels` |
| purple bands, marked `*` | a heavy dark-pool level within 0.1% of a GEX level (confluence) | both of the above |
| dashed lines | call wall, put wall, gamma magnet; dotted = gamma flip | `stock/{ticker}/gex-levels` |
| circles | dark-pool block prints at their time and price; area = dollar notional | `darkpool/{ticker}` |

Levels more than one session-range away from the day's high/low are listed under the chart instead of squashing it. Below
the chart the report adds the full dark-pool ladder, the top net-gamma strikes, the confluence table, the block-print list
and the options-flow premium tilt.

## Endpoints used

All from `https://api.unusualwhales.com` (Bearer auth):
`/api/stock/{ticker}/ohlc/{candle_size}`, `/api/darkpool/{ticker}`, `/api/darkpool/{ticker}/price-levels`,
`/api/darkpool/recent`, `/api/stock/{ticker}/gex-levels`, `/api/stock/{ticker}/spot-exposures/strike`,
`/api/stock/{ticker}/greek-exposure`, `/api/option-trades/flow-alerts`, `/api/option-contract/{id}/historic`.

## What we verified about the data

Unusual Whales data was checked against independent sources before anything was built on it.

- **Dark-pool coverage: 95-97%.** An independent detector logging every off-exchange (SIP exchange `D`) print of $200k+ from
  Alpaca's live tape: 95-97% of its blocks appear in UW's feed (same size, price within 2 cents, time within 5 s, median lag
  0.5 s), and it captured 93.6% of UW's $200k+ prints on a healthy day. The comparison also found a real bug in that
  detector (fixed).
- **GEX regime agreement: 77.5%.** Over 120 days, UW's SPY net gamma and an independently computed GEX (ThetaData Greeks
  and open interest) agree on the sign of the regime 77.5% of the time (z = 6.0 vs a coin flip). Related, not identical:
  magnitudes correlate weakly (r = 0.15) because the two cover different expiries and strikes.
- **API behaviour the docs leave open**, all fixed and pinned by tests (`python -m scripts.first_call_check` re-verifies
  them live): every endpoint wraps its payload in `{"data": ...}`; dark-pool `premium` is price x size; put gamma is
  signed negative; the per-strike endpoint's default page is the 50 *lowest* strikes (`limit=500` needed);
  `greek-exposure` timeframes are single tokens (`1M`, not `1M-2M`, which returns 422); GEX snapshots are end-of-day
  (~16:14 ET); OHLC rows come newest-first and include pre/post-market; and once `older_than` is set, the dark-pool
  endpoint stops honouring `date` and walks into earlier days -- the pager filters to the requested day and stops at the
  boundary.

## What we tested -- and what held up

The chart is a way to *see* the data. Whether any of it *predicts* price is a separate question, so it was tested --
pre-registered wherever possible (the rules were committed before any outcome was looked at, and the git history is the
record).

| question | result |
|---|---|
| Does price react more at dark-pool x GEX confluence levels than at ordinary ones? | **No detectable effect.** Confluence held 53.8% vs 49.7-51.3% for controls and a shifted placebo; t = 0.8-1.0; same small sign across a 10-row robustness grid, none reaching t = 2. |
| Does a flow trader's "conviction" (big premium, volume >> OI, ask-side, single-leg...) predict results? | **No** (pre-registered, 58,386 contract-days). Higher conviction did not earn better results; buying the same contract lost on average. |
| Do UW flow alerts and an independent aggressor-flow measure agree on direction? | **No agreement** (44.4% of 90 ticker-days). They measure different things. |
| Do prior-day UW levels improve a live auto-trader's signals (6,947 trades)? | **Not supported** (pre-registered, Holm-corrected). A level in the trade's path: +0.028R, wrong sign, p 0.65. Entry below the gamma flip: +0.054R, right sign in both halves but Holm p 0.51. |

Reading these plainly: the data is accurate and well covered, and it is a genuinely good map of where size traded and where
dealer hedging is concentrated. In these tests it did not, on its own, tell you which way price goes next. "No detectable
effect" is not proof of none -- every study states the effect size it could have detected -- but it is the honest answer
from this sample.

<details>
<summary><b>Study 1 -- confluence reaction (event study)</b></summary>

```bash
python -m research.run --tickers SPY,QQQ,NVDA,TSLA --days 250
python -m research.sensitivity
```

For each trading day D it pulls UW's dark-pool price levels and GEX levels, labels them (`confluence`, `dp_only`,
`gex_only`, plus a `placebo` shifted +/-0.75%), and measures how price reacts when it first touches each level on D+1:
**hold** (moves 0.5 ATR off the level) vs **break** (goes 0.5 ATR through it first). Guards: levels from D, reaction on D+1
(no lookahead); ATR from bars before the touch only; the touch bar is excluded from the outcome window; the unit of
analysis is the ticker-day; placebo levels show whether *any* level attracts reaction; on real SPY/QQQ bars with ordinary
levels (prior-day high/low) the harness returns 45-51% hold rates, i.e. it does not manufacture an edge.

250 sessions x SPY, QQQ, NVDA, TSLA, primary configuration fixed before any outcome:

| level type | events | hold rate |
|---|---|---|
| dark-pool x GEX confluence | 605 | 53.8% |
| dark-pool only | 1,992 | 49.7% |
| GEX only | 683 | 51.1% |
| placebo (shifted) | 841 | 51.3% |

Only an effect of roughly 8 points or more was detectable at this sample size. An early draft used a 0.5% proximity, which
made 61-70% of SPY/QQQ heavy levels "confluence" -- no distinct group -- so the primary definition is 0.1%, chosen from
level structure alone before any outcome was computed.
</details>

<details>
<summary><b>Study 2 -- flow conviction (pre-registered)</b></summary>

A human flow trader's judgment, turned into something testable. `research/flow/` codifies the criteria visible in a real
trade call as a graded 0-9 **conviction score** on a contract's end-of-day stats (premium, volume vs open interest,
ask-side share, floor share, single-leg, days to expiry, moderate OTM), then asks: do higher scores earn better results?
Score, outcomes, statistics (winsorized means, day-clustered bootstrap, within-month permutation, half split) and pull
parameters were committed before any outcome was examined.

```bash
python -m research.flow.collect discover
python -m research.flow.collect enrich --wait-for-reset
python -m research.flow.analyze
python -m research.flow.card GOOGL261002C00355000 2026-09-10 --equity 100000
```

| conviction | events | underlying, 5-day excess return vs SPY (direction-signed) | buy the contract, gross | net of half-spread |
|---|---|---|---|---|
| low (0-3) | 17,506 | +0.07% | -4.5% | -12.0% |
| mid (4-6) | 38,639 | +0.02% | -4.2% | -11.6% |
| high (7-9) | 2,241 | -0.23% | -3.1% | -13.2% |

High minus low: -0.28% (95% CI -0.72% to +0.12%, permutation p = 0.16) on the underlying; -1.0% (CI -7.4% to +6.1%) gross;
-2.9% (CI -8.9% to +3.8%) net. The hit rate of direction-signed underlying returns is about 50% in every bucket. Caveats:
attrition differs by bucket; the net figure uses D's closing NBBO and is probably pessimistic; one horizon (5 days) and one
year. The trader's edge, if any, may live in what a score cannot see: catalysts, ticker selection, exits and sizing.
</details>

<details>
<summary><b>Study 3 -- does UW data filter a live auto-trader's signals? (pre-registered, optional)</b></summary>

`research/argus_filter/` tests whether the **prior** session's UW levels change the outcomes of ARGUS's M30i PUTS signals
(a loud 30-minute liquidity-sweep fade; 9,452 signals over 12 months, 6,947 with complete UW data). Two hypotheses, fixed
direction, Holm-corrected, day-clustered bootstrap, a shifted-level placebo, half split, minimum 1,500 signals and 0.05R.
The full protocol is in [`research/argus_filter/PREREGISTRATION.md`](research/argus_filter/PREREGISTRATION.md) and the
result in [`research/argus_filter/RESULTS.md`](research/argus_filter/RESULTS.md).

- H1 -- a dark-pool or GEX level in the path from entry to target lowers R: **+0.028R (wrong sign), p 0.65 -- not supported.**
  83% of signals have a level in a 3R path, so the levels barely discriminate.
- H2 -- entry below the gamma flip raises R: **+0.054R, same sign in both halves, Holm p 0.51 -- not supported.**

2,505 signals had no GEX snapshot (UW returns an empty one for thinly covered names), so the sample leans toward names UW
computes GEX for. This part reads another system's files by path and ships none of its data; it is optional.
</details>

<details>
<summary><b>Comparing UW against an independent system (optional)</b></summary>

`compare/` measures agreement between UW and the files an existing trading system already records (read-only, by path;
`--argus-root`, default the sibling `ai-trading-desk-2` checkout). Output is aggregate statistics only.

```bash
python -m compare.run gex                                  # SPY GEX regime vs UW net gamma, ~120 days
python -m compare.run darkpool --date 2026-09-18 --top 8   # UW dark-pool coverage of independently logged blocks
python -m compare.run flow --dates 2026-09-16,2026-09-18   # daily options-flow direction, per ticker
```
</details>

## Project layout

- `main.py` -- CLI: `demo`, `scan`, `recent`.
- `src/uw_client.py` -- thin Bearer-auth REST client (one retry on 429, and on a dropped connection / timeout / 5xx).
- `src/darkpool.py`, `src/gex.py`, `src/flow.py`, `src/ohlc.py` -- one function per endpoint family, returning parsed
  models (`src/models.py`); `darkpool.prints_for_day` pages a whole session.
- `src/analysis.py` -- block prints, confluence, flow tilt, top gamma strikes (pure functions).
- `src/chart.py` -- the chart: `build_chart` (data) and an inline-SVG renderer; `src/report.py` -- the HTML report.
- `src/demo.py` -- the seeded synthetic session behind `python main.py demo`.
- `research/`, `compare/` -- the studies above.
- `tests/` -- 195 tests against synthetic fixtures in the real response shapes; no API key needed (`pytest`).

## Data terms

Unusual Whales data is personal-use only and may not be redistributed. This repo ships only code and synthetic fixtures;
generated reports go to the git-ignored `reports/` folder and the research caches to `.cache/`.
