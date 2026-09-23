"""
Constants for the pre-registered ARGUS-signal filter study. Every number here is either copied from
PREREGISTRATION.md (marked [PR]) or is an implementation detail the document left open (marked
[IMPL]); each [IMPL] choice was fixed BEFORE any UW data was fetched or any outcome examined, and is
listed in the hand-off so it can be logged as a dated addendum. None of them may change after results.
"""

# ---- population [PR] ----
# Loud threshold, target multiple and hold length are read from the ARGUS modules at export time (the
# document says "the same functions/constants the ARGUS backtests use") and recorded in meta.json.
# The document pins today's values; the export refuses to run if ARGUS has drifted from them, so a
# quiet change on the ARGUS side cannot silently redefine the population.
PINNED_RVOL_20_LOUD_THRESHOLD = 1.01
PINNED_TARGET_R_MULTIPLE = 3.0
PINNED_HOLD_BARS = 13
DIRECTION = "down"                        # M30i PUTS: the swept-low "up" signal mirrored to a put

# [IMPL] "last 12 months of cached data": 365 calendar days back from the newest cached session
# (ARGUS's own LOOKBACK_CALENDAR_DAYS convention). Applied to the signal's session date D.
WINDOW_DAYS = 365

# ---- levels [PR] ----
TOP_N_DARKPOOL = 5                        # top-5 dark-pool price levels by volume (research/levels.py)
# [IMPL] The document names the four GEX fields but not the source; the earlier confluence study fixed
# "OI" for the same fields (research.run default), so the same is used here.
GEX_SOURCE = "oi"

# ---- hypotheses [PR] ----
H1_DIRECTION = -1                         # obstacle in the path -> LOWER mean R
H2_DIRECTION = +1                         # entry below gamma_flip -> HIGHER mean R

# ---- statistics [PR] ----
BOOTSTRAP_RESAMPLES = 2_000
SEED = 20260921                           # bootstrap and fetch order, exactly as registered
ALPHA = 0.05                              # Holm-adjusted
MIN_EFFECT_R = 0.05
MIN_SIGNALS = 1_500
PLACEBO_SHIFT = (0.005, 0.015)            # U(0.5%, 1.5%), random direction
PLACEBO_MAX_RATIO = 0.5                   # placebo effect must be smaller than half the real effect
# [IMPL] The document gives no seed for the placebo draw; the study seed is reused. One draw, as written.
PLACEBO_SEED = SEED
# [IMPL] The document defines the placebo only for H1 ("repeat H1 with every level shifted"), so the verdict's
# "placebo passes" condition applies to H1 only. An H2 placebo (shifting gamma_flip) is still computed and
# printed for information, but is not a condition of H2's verdict: shifting the flip ~1% barely changes whether
# an entry is below or above it, so a genuine regime effect would fail that check by construction.
PLACEBO_REQUIRED = {"H1": True, "H2": False}

# ---- data plan [PR] ----
DAILY_REQUEST_CAP = 39_850                # x-uw-daily-req-count, per quota day
MAX_QUOTA_DAYS = 3
QUOTA_RESET_HOUR_ET = 20                  # UW's daily quota resets at 8 PM ET

# ---- files (under the gitignored .cache/) ----
CACHE_SUBDIR = "argus_filter"
SIGNALS_FILE = "signals.csv"              # WITH outcomes -- read only by analyze.py
KEYS_FILE = "signal_keys.csv"             # NO outcomes -- the only signal file fetch.py may read
CALENDAR_FILE = "calendar.json"
META_FILE = "meta.json"
FETCH_STATE_FILE = "fetch_state.json"
ANALYSIS_MARKER_FILE = "analysis_run.json"
