# Pre-registration: do prior-day UW levels filter ARGUS's M30i PUTS signals?

Written 2026-09-20, committed BEFORE any UW data is fetched for this study and before any outcome is joined to any level.
Anything not fixed here is not allowed to change after results; changes go in the Addenda log at the bottom, dated, before the
results they affect are seen.

## Why this study exists
The goal is a profitable auto-trader. Two earlier UW studies were null, but both used generic levels/flow events, not ARGUS's own
signal populations (README, Findings 1-2 and the flow-conviction study). If UW data adds edge for ARGUS, the likeliest place is as a
FILTER on a setup that already has an edge. This is the one UW test directly tied to that goal. If it is null, UW work stops
(hackathon submission aside).

## Population (fixed)
- **Primary: M30i PUTS.** Loud M30 liquidity-sweep signals (rvol_20 >= RVOL_20_LOUD_THRESHOLD, currently 1.01), deduped earliest,
  mirrored to puts, built by the SAME functions the ARGUS backtests use (`find_signals_with_all_factors`, `dedup_earliest`,
  `atr_series`, `load_cached_m30`). Stop = mirrored stop, target = 3R below entry (TARGET_R_MULTIPLE), HOLD_BARS = 13, outcome
  simulated by `trade_simulator.simulate_trade` exactly as in the existing put backtests. Outcome = R (stock-level).
- **Window:** signals dated within the last 12 months of cached data (matches the flow study's window; UW history is dense there).
- **Replication only: ORB UP.** Its signal population and outcome must be pinned (module + function + parameters written into
  Addendum 0) BEFORE any UW data is fetched for it. Until then it is not part of the study.

## Levels (fixed; lookahead-safe)
For a signal on session D, levels come ONLY from UW data of the prior trading session D-1 (never D). Definitions reuse
`research/levels.py`: the top-5 dark-pool price levels by volume, plus the GEX fields call_wall, put_wall, gamma_flip,
gamma_magnet from the by-strike GEX snapshot of D-1. A signal with missing D-1 dark-pool OR GEX data is excluded and counted.
A test must assert every fetch date is strictly earlier than the signal date.

## Hypotheses (two primary, fixed direction, both tested two-sided)
- **H1 obstacle:** M30i PUTS signals with >= 1 D-1 level strictly inside the path from entry down to the 3R target
  (target <= level < entry) have LOWER mean R than signals with none. (A put's path to target crossing support is an obstacle.)
- **H2 regime:** signals whose entry price is BELOW D-1 gamma_flip (negative-gamma zone) have HIGHER mean R than signals above it.
  (Theory: negative gamma amplifies moves; the earlier VIX1D result pointed the same way.)

Multiplicity: exactly these two; Holm correction at alpha = 0.05. Everything else below is exploratory and gets no verdict.

## Statistics (fixed)
- Effect = mean R(group A) - mean R(group B), with a DAY-CLUSTERED bootstrap (2,000 resamples of signal days, seed 20260921) for
  the 95% CI and p. Naive t is reported but never used for the verdict (sweeps cluster by day; see the flip study).
- Halves: split signals by date at the median; report the effect in each half.
- **Placebo (mandatory):** repeat H1 with every level shifted by a seeded random amount U(0.5%, 1.5%) in a random direction.
  The placebo effect must be smaller than half of the real effect.
- Base rates: report the share of signals in each group and the unconditional mean R, so the effect is interpretable.

## Verdict rules (fixed now)
A hypothesis is **SUPPORTED** only if ALL hold: Holm-adjusted p < 0.05; the same sign in both halves; placebo passes;
|effect| >= 0.05R. Otherwise it is **NOT SUPPORTED**. An underpowered result is reported as such, not as a null.
- Power statement: with n ~ 2,000 and per-trade SD ~ 1.2R, only an effect of roughly 0.15R or more is detectable after day
  clustering. A null therefore means "no large effect", not "zero".
- **Minimum sample:** if fewer than 1,500 signals have complete data, the verdict is "underpowered -- no verdict".

## What happens next (fixed now)
- Either hypothesis SUPPORTED -> a second stage on data not used here (later dates, or the forward log) with the same rules,
  BEFORE any ARGUS wiring. M30i PUTS stays frozen until 25 reps regardless.
- Neither supported -> stop UW-as-a-filter work; do not renew UW past the credit; record in memory.
- No re-running with new definitions to "rescue" a result.

## Data plan and quota (fixed)
- Unique (ticker, D-1) pairs are put in a seeded random order (seed 20260921) and fetched until the budget is spent:
  at most 39,850 requests per UW quota day (`x-uw-daily-req-count`), at most 3 quota days (resets 8 PM ET). Because the order is
  random, the completed set is a random sample; analysis uses whatever completed. The fetch script must not read outcomes.
- Analysis runs ONCE, after the fetch stops. No interim looks at outcomes.
- Raw UW data stays in the gitignored `.cache/` (UW terms: personal use, no redistribution). Only aggregate tables are committed.

## Known limits (stated up front)
Stock-level R only: no option premiums, no spreads, no premium stops (the live setup exits mostly on premium stops -- see the
COHR/SWKS/HPE spread findings). A stock-level edge is necessary, not sufficient. D-1 levels are a day stale by construction.
One year of data, one setup as primary.

## Implementation checklist (before fetching)
1. Export the signal table (ticker, date, entry, stop, target, R) from the ARGUS repo to `.cache/` (not committed).
2. Fetch script using the caching, quota-aware client; no access to outcomes.
3. Analysis script implementing exactly the above; tests for the D-1 rule, the in-path rule, Holm, the placebo shift, and the
   verdict logic (mutation-check the verdict rule).
4. Pin the ORB UP population in Addendum 0.

## Addenda log

### Addendum 0 -- 2026-09-22 (ORB UP replication population, pinned)
Written BEFORE any UW data is fetched for ORB UP and before any ORB UP outcome is joined to any level. It pins the population
and outcome as the document requires; nothing above is changed. It mirrors the live ARGUS admission path wherever that path
can be computed at stock level.
- **Signals:** `backtest/test_orb_premarket_confluence_gap_and_go_only.detect_gap_and_go_signals(ticker, bars)` on the cached
  M15 bars (`backtest/test_orb.load_cached`). That means: gap_pct >= GAP_AND_GO_CALLS_THRESHOLD_PCT (0.5); the first close above
  the first bar's high; breakout bar index >= 3 (MIN_BREAKOUT_BAR_INDEX); at most one signal per ticker-day. Entry = the breakout
  bar's close; stop = the first bar's low.
- **Pre-market gate (live, hard-coded `PREMARKET_CONFLUENCE_ENABLED = True` in `detection/orb_engine.py`):** keep only
  signals where `tag_confluence` (`backtest/test_orb_premarket_confluence_real.py`) marks `_confluence = True`, meaning the
  breakout close is above that day's real Alpaca pre-market high. Signals with no pre-market data are excluded and counted.
- **Outcome:** R from `backtest.trade_simulator.simulate_trade(bars, ts_list, idx, "up", entry, stop, 2.5,
  max_bars_forward=26)`. idx = the breakout bar's index, found with bisect_right(ts_list, signal_ts) - 1, as in
  `backtest/test_m30i_puts_orb_up_confluence.simulate_orb`. 2.5R is the live automated TP; 26 is the M15 hold used there.
- **Universe / window:** ARGUS `config.WATCHLIST`. Signal dates fall within 365 calendar days back from the newest cached M15
  session (same convention as Addendum 1, item 1).
- **Not replicated (option-level or discretionary; stated, not modelled):** the DTE gate, the option-spread gate, the late-day
  cutoff, cross-setup mutes, the grade card.
- **Tests:** the same H1 and H2 with the same statistics, verdict rules, Holm pair and Addendum 1 gap-fills, read for a call.
  H1 path = entry < level <= target (a level between entry and the 2.5R target is resistance for a call), hypothesised LOWER
  mean R. H2 = entry below D-1 gamma_flip, hypothesised HIGHER mean R (breakouts are the setup GEX theory expects to benefit
  from negative gamma; ORB UP's VIX1D result points the same way). ORB UP is replication only: it cannot rescue or override the
  M30i PUTS verdict.

### Addendum 1 -- 2026-09-22 (implementation gap-fills)
Written after the step 1-3 code (51c1e60) and BEFORE any UW data was fetched for this study; no outcome (R) has been joined to any
level or examined. Nothing above is changed; these fill points the document left open, exactly as already coded in
`research/argus_filter/protocol.py` and `stats.py`.
1. **Window:** "last 12 months of cached data" = 365 calendar days back from the newest cached session, applied to the signal
   date D (ARGUS's LOOKBACK_CALENDAR_DAYS convention).
2. **GEX source:** the four GEX fields come from UW's gex-levels endpoint with source "oi", the same source the earlier confluence
   study used.
3. **Placebo scope:** the placebo is defined only for H1 ("repeat H1 with every level shifted"), so "placebo passes" is a verdict
   condition for H1 only. An H2 placebo (shifting gamma_flip) is computed and reported for information only: a ~1% flip shift
   barely changes which side of the flip an entry is on, so a genuine regime effect would fail it by construction (shown on
   synthetic data before any fetch).
4. **Placebo test and draw:** "smaller than half of the real effect" is judged by magnitude (|placebo| < 0.5 x |real|). One
   placebo draw, seeded with the study seed 20260921.
5. **Direction:** SUPPORTED additionally requires the full-sample effect to have the hypothesised sign (H1 negative, H2 positive);
   an effect with the opposite sign is NOT SUPPORTED even if significant.

Informational (not a change): the step 1 export produced 9,452 M30i PUTS signals across 111 tickers (window 2025-09-15..2026-09-15),
about 4.7x the "n ~ 2,000" estimate in the power statement. The fixed rules above apply unchanged.
