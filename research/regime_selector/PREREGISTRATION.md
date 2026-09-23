# Pre-registration: does UW's prior-day gamma regime pick the right ARGUS setup?

Written 2026-09-23 and committed ALONE, before this study's code exists, before any UW data is fetched for it and before any
outcome is split by regime. Anything not fixed here may not change after results; changes go in the Addenda log at the
bottom, dated, before the results they affect are seen.

## Why
Every earlier UW test asked about DIRECTION at a level (confluence reaction, the ARGUS filter study's H1, market memory) and
came back null. None tested what dealer-gamma theory actually predicts: the volatility REGIME. With dealers net long gamma
(positive) their hedging dampens moves, so fades should work better; net short gamma (negative) amplifies moves, so
breakouts should. ARGUS's own VIX1D study (`backtest/test_vix1d_regime_confluence.py`) found that split with a volatility
proxy, and the filter study's one near-miss (entries below the gamma flip, +0.054R, Holm p 0.51) points the same way. This
study asks one narrow question: **does UW's prior-day SPY net-gamma sign tell you which ARGUS setup to run today?** It is a
setup selector, not a direction signal.

## Regime (fixed)
- Source: UW `GET /api/stock/SPY/greek-exposure?timeframe=2Y` via `src/gex.greek_exposure_history` -- daily rows.
- Net gamma = call_gamma + put_gamma (put gamma is signed negative, verified live 2026-09-18).
- Day D's regime = the sign of net gamma on the PRIOR trading session D-1 (the last row dated strictly before D). UW's GEX
  snapshots are end-of-day, so D-1's value is known before D opens. **NEG** = net gamma < 0 (amplifying). **POS** = net gamma
  >= 0 (dampening). A signal day with no prior row is excluded and counted.

## Populations (fixed) -- reused unchanged from ARGUS `backtest/test_vix1d_regime_confluence.py`
So the result compares directly with the VIX1D study:
- **M30i PUTS:** `m30i_puts_signals` -- loud M30 sweeps (rvol_20 >= RVOL_20_LOUD_THRESHOLD), `dedup_earliest`, mirrored to a
  put, 3R target, 13 M30 bars.
- **ORB UP:** `orb_up_signals` -- `detect_orb_signals_with_levels`, direction up only, 2R target, 26 M15 bars.
- Stated: this ORB population is the VIX1D study's, NOT the live gap-and-go + pre-market ORB UP.
- Universe (frozen): the 95 tickers frozen in ARGUS `backtest/PREREG_m30_bidirectional.md` Addendum 1 (today's WATCHLIST
  with cached bars), passed as the generators' `watchlist` argument. `config.WATCHLIST` is live-loaded and drifts, so it is
  not used.
- Window: every signal whose date is covered by the UW history. The ARGUS caches bound it too (M30 through 2026-09-02; M15
  2025-07-08..2026-08-14). The script records the exact first and last date used per setup.
- Outcome: the generators' own stock-level R. The signal date is the generator's own `day` (the UTC date of the signal, the
  same as the ET date in regular hours).

## Hypotheses (fixed direction; two-sided tests; Holm correction over the pair)
- **H1 fade:** M30i PUTS mean R on POS days minus mean R on NEG days > 0.
- **H2 breakout:** ORB UP mean R on NEG days minus mean R on POS days > 0.

## Statistics (fixed)
- The regime is one label per day and persists across days, and signals on the same day are not independent, so the
  bootstrap resamples **ISO weeks** (week of the signal date): 2,000 resamples, seed 20260924, recomputing both group means on
  each resample; 95% percentile CI; two-sided p = 2 x min(share <= 0, share >= 0), capped at 1.
- Halves: signals split at the median signal date (first = date < median, second = date >= median); the effect in each half.
- **Placebo (mandatory):** the whole regime series shifted forward by 21 trading days (D gets the regime of the session 21
  sessions before D-1), keeping its base rate and persistence but breaking the alignment. Must satisfy
  |placebo effect| < 0.5 x |real effect|.
- Effective sample: report the number of regime episodes (maximal runs of consecutive sessions with the same sign) of each
  sign within each setup's window.

## Verdict per hypothesis (fixed)
- **UNDERPOWERED -- no verdict** if either regime has fewer than 20 episodes within that setup's window.
- Otherwise **SUPPORTED** only if ALL hold: Holm-adjusted p < 0.05; the effect has the hypothesised sign; |effect| >= 0.05R;
  the same sign in both halves; the placebo passes. Else **NOT SUPPORTED**. No reruns with new definitions.

## Sanity gate (before any regime split is read)
All-days M30i PUTS mean R on the population must be within +/-0.03R of +0.105R (the VIX1D study's all-days number). If not,
stop and find the cause; nothing else is computed.

## Secondary (reported, no verdict)
- A selector rule (M30i PUTS only on POS days, ORB UP only on NEG days) vs running both every day: total R, R per trading day,
  and trades per day.
- UW regime vs the VIX1D bucket (as defined in the VIX1D study): share of days that agree.
- Whether each split survives WITHIN each VIX1D bucket, i.e. whether UW adds anything beyond VIX1D, which ARGUS already reads.
- Base rates: share of days POS/NEG, signals per regime, unconditional mean R per setup.

## Not looked at before registration
The old 120-day ThetaData GEX regime backtest (`backtest/test_gex_regime_confluence.py`) printed a result that was never
recorded; it has not been looked at and will not be until this study has run.

## What happens next (fixed now)
- Either hypothesis SUPPORTED -> forward shadow logging of the UW regime next to both setups' live outcomes before any ARGUS
  change. ARGUS already reads VIX1D, so UW earns a place only if the within-VIX1D secondary shows it adds something.
- Neither SUPPORTED (or UNDERPOWERED) -> UW research ends; the hackathon submission stands as it is.

## Addenda log

### Addendum 1 -- 2026-09-23 (user decision: use the LIVE ORB UP)
Written before this study's code exists, before any UW data is fetched for it and before any outcome is split by regime. The
ORB UP population above is REPLACED by the live ORB UP, exactly as pinned in `research/argus_filter/PREREGISTRATION.md`
Addendum 0:
- Signals: ARGUS `backtest/test_orb_premarket_confluence_gap_and_go_only.detect_gap_and_go_signals(ticker, bars)` on the cached
  M15 bars (`backtest/test_orb.load_cached`): gap_pct >= GAP_AND_GO_CALLS_THRESHOLD_PCT (0.5), the first close above the
  first bar's high at breakout bar index >= 3, at most one signal per ticker-day; entry = the breakout close, stop = the first
  bar's low.
- Live pre-market gate (`PREMARKET_CONFLUENCE_ENABLED = True` in `detection/orb_engine.py`): keep only signals that ARGUS's
  own `tag_confluence` (`backtest/test_orb_premarket_confluence_real.py`) marks `_confluence = True` -- the breakout close is
  above that day's real Alpaca pre-market high. Pre-market ranges come from ARGUS's `AlpacaDataFeed.get_premarket_ranges`,
  one call per signal date, cached locally (gitignored). A signal with no pre-market data is excluded and counted.
- Outcome: `simulate_trade(bars, ts_list, idx, "up", entry, stop, 2.5, max_bars_forward=26)` with idx = bisect_right(ts_list,
  signal_ts) - 1 (as in ARGUS `backtest/test_m30i_puts_orb_up_confluence.simulate_orb`). 2.5R is the live automated take-profit.
- Same frozen 95-ticker universe; window bounded by the M15 cache (2025-07-08..2026-08-14) and the UW history.
- Consequence, stated: the ORB UP result is no longer directly comparable with the VIX1D study's ORB population (that study
  used `detect_orb_signals_with_levels` at 2R). The VIX1D secondary still uses the VIX1D study's bucket definition.
- Nothing else changes: the M30i PUTS population, regime, hypotheses (H2 now reads "live ORB UP"), statistics, verdict,
  sanity gate and consequences are as registered above.
