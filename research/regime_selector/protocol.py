"""Constants for the pre-registered regime-selector study (PREREGISTRATION.md + Addendum 1). None may change after
results; a change goes in the addenda log first."""

# ---- regime ----
UW_TICKER = "SPY"
UW_TIMEFRAME = "2Y"
POS, NEG = "POS", "NEG"                    # net gamma >= 0 dampens moves; < 0 amplifies them

# ---- populations ----
UNIVERSE_SIZE = 95                         # frozen in ARGUS backtest/PREREG_m30_bidirectional.md Addendum 1
PINNED_M30_TARGET_R, PINNED_M30_HOLD_BARS = 3.0, 13
PINNED_ORB_GAP_PCT, PINNED_ORB_MIN_BREAKOUT_BAR = 0.5, 3   # Addendum 1: the live ORB UP
ORB_TARGET_R, ORB_MAX_BARS = 2.5, 26

# ---- hypotheses: rows are grouped so that the effect is always mean(A) - mean(B), hypothesised > 0 ----
HYPOTHESES = {
    "H1": {"setup": "m30i_puts", "A": POS, "B": NEG, "label": "H1 fade: M30i PUTS on POS days - on NEG days"},
    "H2": {"setup": "orb_up", "A": NEG, "B": POS, "label": "H2 breakout: live ORB UP on NEG days - on POS days"},
}

# ---- statistics ----
SEED = 20260924
BOOTSTRAP_RESAMPLES = 2_000
ALPHA = 0.05
MIN_EFFECT_R = 0.05
PLACEBO_SHIFT_SESSIONS = 21
PLACEBO_MAX_RATIO = 0.5
MIN_EPISODES = 20

# ---- sanity gate ----
SANITY_M30_MEAN_R = 0.105
SANITY_TOLERANCE_R = 0.03

# ---- files (under the gitignored .cache/) ----
CACHE_SUBDIR = "regime_selector"
PREMARKET_FILE = "premarket.json"
VIX1D_FILE = "vix1d.json"
MARKER_FILE = "analysis_run.json"
