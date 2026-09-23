import argparse
import json
from datetime import date, timedelta

import numpy as np
import pytest

from research.argus_filter import analyze, levels, protocol, stats
from research.caching_client import CachingClient
from research.levels import GEX_FIELDS, label_levels
from src.models import DarkPoolPriceLevel, DarkPoolPriceLevels, GexLevels


# ---------------------------------------------------------------- the registered numbers, pinned

def test_registered_constants_match_the_preregistration_literally():
    assert (protocol.MIN_SIGNALS, protocol.MIN_EFFECT_R, protocol.ALPHA) == (1500, 0.05, 0.05)
    assert (protocol.PLACEBO_MAX_RATIO, protocol.PLACEBO_SHIFT) == (0.5, (0.005, 0.015))
    assert (protocol.SEED, protocol.BOOTSTRAP_RESAMPLES) == (20260921, 2000)
    assert (protocol.DAILY_REQUEST_CAP, protocol.MAX_QUOTA_DAYS, protocol.QUOTA_RESET_HOUR_ET) == (39850, 3, 20)
    assert (protocol.TOP_N_DARKPOOL, protocol.WINDOW_DAYS, protocol.H1_DIRECTION, protocol.H2_DIRECTION) == (5, 365, -1, +1)
    assert (protocol.PINNED_RVOL_20_LOUD_THRESHOLD, protocol.PINNED_TARGET_R_MULTIPLE, protocol.PINNED_HOLD_BARS) == (1.01, 3.0, 13)


# ---------------------------------------------------------------- level rules

def test_in_path_rule_is_target_le_level_lt_entry():
    entry, target = 100.0, 97.0
    assert levels.has_obstacle(entry, target, [97.0])              # exactly on the target: inside
    assert levels.has_obstacle(entry, target, [98.5])
    assert levels.has_obstacle(entry, target, [99.99])
    assert not levels.has_obstacle(entry, target, [100.0])         # exactly on the entry: NOT in the path
    assert not levels.has_obstacle(entry, target, [100.01, 120.0])  # above the entry
    assert not levels.has_obstacle(entry, target, [96.99, 50.0])   # beyond the target
    assert not levels.has_obstacle(entry, target, [])
    assert levels.has_obstacle(entry, target, [50.0, 120.0, 98.0])  # one qualifying level among many is enough


def test_gamma_flip_grouping():
    assert levels.below_gamma_flip(99.0, 100.0) is True
    assert levels.below_gamma_flip(101.0, 100.0) is False
    assert levels.below_gamma_flip(100.0, 100.0) is None           # on the flip: neither group
    assert levels.below_gamma_flip(100.0, None) is None            # no flip that day


def _dp(prices_and_vols):
    return DarkPoolPriceLevels("AAA", "2026-09-08", [DarkPoolPriceLevel(p, v, 1) for p, v in prices_and_vols])


def test_heavy_selection_is_the_same_as_research_levels():
    dp = _dp([(100 + i, 10 * (i + 1)) for i in range(8)])
    empty_gex = GexLevels("AAA", "d", "oi", "t", None, None, None, None)
    reference = {lv["price"] for lv in label_levels(dp, empty_gex, top_n=protocol.TOP_N_DARKPOOL)}
    assert set(levels.heavy_prices(dp)) == reference == {103, 104, 105, 106, 107}     # top 5 by dark-pool volume


def test_parsers_treat_empty_days_as_missing_but_null_fields_as_present():
    assert levels.parse_dp("AAA", None) is None
    assert levels.parse_dp("AAA", {"date": "d", "data": []}) is None
    assert levels.parse_gex("AAA", None) is None
    assert levels.parse_gex("AAA", {"data": {"call_wall": None, "gamma_flip": None}}) is None      # nothing usable
    partial = levels.parse_gex("AAA", {"data": {"call_wall": "110", "gamma_flip": None}})
    assert partial.call_wall == 110.0 and partial.gamma_flip is None                              # a null flip is fine


DP_RAW = {"date": "2026-09-08", "data": [{"price": "99", "dark_pool_volume": 5, "regular_volume": 1},
                                         {"price": "101", "dark_pool_volume": 9, "regular_volume": 1}]}
GEX_RAW = {"data": {"call_wall": "110", "put_wall": "90", "gamma_flip": None, "gamma_magnet": "100"}}


def test_day_levels_collect_dark_pool_plus_the_present_gex_fields():
    lv = levels.DayLevels.from_responses("AAA", DP_RAW, GEX_RAW)
    assert lv.dp == [101.0, 99.0] and lv.gamma_flip is None
    assert sorted(lv.all_prices) == [90.0, 99.0, 100.0, 101.0, 110.0]
    assert levels.DayLevels.from_responses("AAA", None, GEX_RAW) is None
    assert levels.DayLevels.from_responses("AAA", DP_RAW, None) is None


def test_placebo_shift_moves_every_level_by_half_to_one_and_a_half_percent_either_way():
    base = levels.DayLevels([100.0] * 60, {f: 200.0 for f in GEX_FIELDS})
    shifted = levels.DayLevels.shifted(base, levels.placebo_rng(1))
    moves = [s / o - 1 for s, o in zip(shifted.dp + list(shifted.gex.values()), base.dp + list(base.gex.values()))]
    assert len(moves) == 64
    assert all(0.005 <= abs(m) <= 0.015 for m in moves)             # magnitude in U(0.5%, 1.5%); never left unmoved
    assert any(m > 0 for m in moves) and any(m < 0 for m in moves)  # both directions occur
    assert max(abs(m) for m in moves) > 0.012 and min(abs(m) for m in moves) < 0.008   # and the amount really varies


def test_placebo_shift_is_seeded_and_leaves_absent_fields_absent():
    base = levels.DayLevels([100.0, 101.0], {"call_wall": 110.0, "put_wall": None, "gamma_flip": 99.0, "gamma_magnet": None})
    a = base.shifted(levels.placebo_rng(7))
    b = base.shifted(levels.placebo_rng(7))
    c = base.shifted(levels.placebo_rng(8))
    assert (a.dp, a.gex) == (b.dp, b.gex) and (a.dp, a.gex) != (c.dp, c.gex)
    assert a.gex["put_wall"] is None and a.gex["gamma_magnet"] is None


# ---------------------------------------------------------------- the D-1 join

class SpyCache:
    """Cache stand-in that records every peek and holds different data for different dates."""

    def __init__(self, by_date):
        self.by_date, self.peeks = by_date, []

    def peek(self, path, params=None):
        self.peeks.append((path, params["date"]))
        dp, gx = self.by_date.get(params["date"], (None, None))
        return dp if "price-levels" in path else gx


def dp_at(price):
    return {"date": "x", "data": [{"price": str(price), "dark_pool_volume": 5, "regular_volume": 1}]}


def test_signal_on_d_only_ever_reads_data_from_the_prior_session():
    cache = SpyCache({"2026-09-08": (dp_at(101), {"data": {"gamma_flip": "95"}}),      # D-1
                      "2026-09-09": (dp_at(999), {"data": {"gamma_flip": "999"}}),     # D  -- must never be read
                      "2026-09-10": (dp_at(888), {"data": {"gamma_flip": "888"}})})    # D+1 -- must never be read
    rows = [{"ticker": "AAA", "date": "2026-09-09", "prior_date": "2026-09-08"}]
    complete, excluded = analyze.attach_levels(rows, cache)
    assert complete[0]["levels"].dp == [101.0] and complete[0]["levels"].gamma_flip == 95.0
    assert {d for _, d in cache.peeks} == {"2026-09-08"}
    assert not excluded


def test_missing_dark_pool_or_gex_excludes_the_signal_and_is_counted_by_reason():
    cache = SpyCache({"2026-09-01": (None, {"data": {"gamma_flip": "95"}}),               # no dark pool
                      "2026-09-02": (dp_at(101), None),                                   # no GEX
                      "2026-09-03": (None, None),                                         # neither
                      "2026-09-04": (dp_at(101), {"data": {"gamma_flip": "95"}})})        # complete
    rows = [{"ticker": "AAA", "date": "x", "prior_date": d} for d in ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04")]
    complete, excluded = analyze.attach_levels(rows, cache)
    assert len(complete) == 1 and excluded == {"no_dark_pool": 1, "no_gex": 1, "no_dark_pool_and_no_gex": 1}


# ---------------------------------------------------------------- statistics

def test_holm_known_values_and_properties():
    assert stats.holm({"a": 0.01, "b": 0.04}) == pytest.approx({"a": 0.02, "b": 0.04})      # 2*0.01, then max(0.02, 1*0.04)
    assert stats.holm({"a": 0.03, "b": 0.04}) == pytest.approx({"a": 0.06, "b": 0.06})      # monotone: b raised to a's 0.06
    assert stats.holm({"b": 0.04, "a": 0.01}) == stats.holm({"a": 0.01, "b": 0.04})         # order-independent
    assert stats.holm({"a": 0.6, "b": 0.7}) == {"a": 1.0, "b": 1.0}                         # capped at 1
    assert stats.holm({"only": 0.03}) == {"only": 0.03}


def rows_from(a, b, dates=None):
    """rows with A values then B values, one signal per date cycling through `dates`."""
    dates = dates or [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(60)]
    out = [{"group": "A", "y": y} for y in a] + [{"group": "B", "y": y} for y in b]
    return [dict(r, date=dates[i % len(dates)]) for i, r in enumerate(out)]


def test_effect_is_mean_a_minus_mean_b():
    assert stats.effect(rows_from([1, 2, 3], [0, 0])) == pytest.approx(2.0)
    assert stats.effect(rows_from([1, 2, 3], [])) is None


def test_bootstrap_is_seeded_finds_a_planted_effect_and_is_quiet_on_noise():
    rng = np.random.default_rng(3)
    planted = rows_from(rng.normal(-0.4, 1.2, 600), rng.normal(0.0, 1.2, 1200))
    boot = stats.day_cluster_bootstrap(planted)
    assert boot["hi"] < 0 and boot["p"] < 0.001 and boot["valid_resamples"] == protocol.BOOTSTRAP_RESAMPLES
    assert stats.day_cluster_bootstrap(planted) == boot                                   # same seed, same answer
    assert stats.day_cluster_bootstrap(planted, seed=1) != boot

    null = rows_from(rng.normal(0, 1.2, 600), rng.normal(0, 1.2, 1200))
    quiet = stats.day_cluster_bootstrap(null)
    assert quiet["lo"] < 0 < quiet["hi"] and quiet["p"] > 0.05


def test_bootstrap_p_is_two_sided():
    days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(40)]
    rows = []
    for i, d in enumerate(days):                                       # every day: A - B = +1 or -1, so the true effect is 0
        rows += [{"date": d, "group": "A", "y": 1.0 if i % 2 else 0.0}, {"date": d, "group": "B", "y": 0.0 if i % 2 else 1.0}]
    assert stats.effect(rows) == 0.0
    assert stats.day_cluster_bootstrap(rows)["p"] > 0.9                # a one-sided p would sit near 0.5


def test_bootstrap_resamples_days_so_day_level_correlation_widens_the_interval():
    rng = np.random.default_rng(5)
    days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(40)]
    day_shock = {d: rng.normal(0, 1.0) for d in days}                    # every signal on a day shares that day's shock
    rows = []
    for i, d in enumerate(days):                                         # a whole day is group A or group B, so the
        for _ in range(30):                                              # shock does NOT cancel in mean(A) - mean(B)
            rows.append({"date": d, "group": "A" if i % 2 else "B", "y": day_shock[d] + rng.normal(0, 0.2)})
    boot = stats.day_cluster_bootstrap(rows)
    naive_half_width = 1.96 * abs(stats.effect(rows)) / abs(stats.welch_t(rows))       # what an unclustered SE would give
    assert (boot["hi"] - boot["lo"]) / 2 > 1.5 * naive_half_width


def test_bootstrap_needs_enough_days_and_both_groups():
    assert stats.day_cluster_bootstrap(rows_from([1, 2, 3, 4], [0, 0, 0, 0], dates=["2026-01-01", "2026-01-02"])) is None
    assert stats.day_cluster_bootstrap(rows_from([1.0] * 20, [])) is None


def test_half_split_cuts_at_the_median_signal_date_and_never_splits_a_day():
    days = [f"2026-01-{d:02d}" for d in range(1, 11)]
    rows = []
    for i, d in enumerate(days):
        first = i < 5
        rows += [{"date": d, "group": "A", "y": 1.0 if first else -1.0}, {"date": d, "group": "B", "y": 0.0}]
    half = stats.half_split(rows)
    assert half["cut"] == "2026-01-06" and half["n_first"] == 10 and half["n_second"] == 10
    assert half["first"] == pytest.approx(1.0) and half["second"] == pytest.approx(-1.0)
    assert stats.half_split(rows[:2]) is None


# ---------------------------------------------------------------- verdict rules

GOOD = dict(eff=-0.20, p_holm=0.01, first=-0.15, second=-0.25, placebo_effect=-0.02)      # a clean H1 win


def verdict(direction=-1, **over):
    kw = dict(GOOD, **over)
    return stats.hypothesis_verdict(direction, kw["eff"], kw["p_holm"], kw["first"], kw["second"], kw["placebo_effect"])


def test_all_conditions_met_is_supported_in_either_direction():
    assert verdict() == (True, [])
    assert verdict(direction=+1, eff=0.2, first=0.15, second=0.25, placebo_effect=0.02) == (True, [])


@pytest.mark.parametrize("over,failed", [
    (dict(p_holm=0.05), ["holm_p"]),                                       # strict: exactly alpha fails
    (dict(p_holm=None), ["holm_p"]),
    (dict(eff=0.20, first=0.15, second=0.25, placebo_effect=0.02), ["direction", "halves"]),   # significant, WRONG way
    (dict(first=0.10), ["halves"]),                                        # halves disagree in sign
    (dict(second=None), ["halves"]),
    (dict(second=0.0), ["halves"]),                                        # zero is not "the same sign"
    (dict(placebo_effect=-0.10), ["placebo"]),                             # exactly half the real effect: fails (strict)
    (dict(placebo_effect=0.15), ["placebo"]),                              # opposite sign but large: still a large placebo
    (dict(placebo_effect=None), ["placebo"]),
    (dict(eff=-0.049, first=-0.05, second=-0.05, placebo_effect=0.0), ["min_effect"]),       # below 0.05R
])
def test_each_single_failed_condition_blocks_support_and_is_named(over, failed):
    supported, reasons = verdict(**over)
    assert not supported and reasons == failed


def test_boundaries_that_still_pass():
    assert verdict(p_holm=0.0499)[0]
    assert verdict(placebo_effect=-0.0999)[0]                              # just under half of |0.20|
    assert verdict(eff=-0.05, first=-0.05, second=-0.05, placebo_effect=0.0)[0]           # |effect| == 0.05 is enough
    assert verdict(placebo_effect=0.0999)[0]                               # the placebo is judged by magnitude


def test_the_placebo_condition_is_registered_for_h1_only():
    assert protocol.PLACEBO_REQUIRED == {"H1": True, "H2": False}
    big_placebo = dict(eff=0.20, first=0.15, second=0.25, placebo_effect=0.19, direction=+1)
    strict = stats.hypothesis_verdict(big_placebo["direction"], big_placebo["eff"], 0.01, big_placebo["first"],
                                      big_placebo["second"], big_placebo["placebo_effect"], placebo_required=True)
    exempt = stats.hypothesis_verdict(big_placebo["direction"], big_placebo["eff"], 0.01, big_placebo["first"],
                                      big_placebo["second"], big_placebo["placebo_effect"], placebo_required=False)
    assert strict == (False, ["placebo"]) and exempt == (True, [])
    assert stats.hypothesis_verdict(+1, 0.2, 0.01, 0.15, 0.25, None, placebo_required=False)[0]   # no placebo number needed


def test_a_missing_effect_can_never_be_supported():
    assert not stats.hypothesis_verdict(-1, None, None, None, None, None)[0]


def test_minimum_sample_rule():
    assert stats.study_status(protocol.MIN_SIGNALS - 1) == "UNDERPOWERED"
    assert stats.study_status(protocol.MIN_SIGNALS) == "EVALUABLE"


# ---------------------------------------------------------------- end to end on synthetic signals

def synthetic(n, obstacle_effect=0.0, flip_effect=0.0, seed=11, days=250):
    """n M30i-PUTS-like signals: entry 100, risk 0.3 (target 99.1), nine levels scattered +-10% around the entry,
    a gamma flip within +-5%. R = noise, shifted by the planted effects."""
    rng = np.random.default_rng(seed)
    start, sigs = date(2025, 9, 1), []
    for i in range(n):
        d = (start + timedelta(days=int(i * days / n))).isoformat()
        dp = list(rng.uniform(90, 110, 5))
        flip = float(rng.uniform(95, 105))
        gex = {"call_wall": float(rng.uniform(90, 110)), "put_wall": float(rng.uniform(90, 110)),
               "gamma_flip": flip, "gamma_magnet": float(rng.uniform(90, 110))}
        lv = levels.DayLevels(dp, gex)
        entry, target = 100.0, 99.1
        r = rng.normal(0.05, 1.2)
        r += obstacle_effect if levels.has_obstacle(entry, target, lv.all_prices) else 0.0
        r += flip_effect if entry < flip else 0.0
        sigs.append({"ticker": f"T{i % 40}", "date": d, "entry": entry, "target": target, "r": float(r), "levels": lv})
    return sigs


def test_planted_effects_in_the_registered_directions_are_supported():
    res = analyze.run_analysis(synthetic(1800, obstacle_effect=-0.45, flip_effect=+0.45))
    assert res["status"] == "EVALUABLE"
    assert res["verdict"] == {"H1": "SUPPORTED", "H2": "SUPPORTED"}, analyze.render(res)
    h1, h2 = res["hypotheses"]["H1"], res["hypotheses"]["H2"]
    assert h1["effect"] < -0.3 and abs(h1["placebo_effect"]) < 0.5 * abs(h1["effect"])
    assert "informational only" in analyze.render(res)                    # H2's placebo is shown but not a condition
    assert abs(h2["placebo_effect"]) > 0.5 * abs(h2["effect"])            # ... and would have blocked a real regime effect


def test_pure_noise_supports_neither_hypothesis():
    res = analyze.run_analysis(synthetic(1800))
    assert res["verdict"] == {"H1": "NOT SUPPORTED", "H2": "NOT SUPPORTED"}, analyze.render(res)


def test_effects_in_the_wrong_direction_are_not_supported_even_when_significant():
    res = analyze.run_analysis(synthetic(1800, obstacle_effect=+0.45, flip_effect=-0.45))
    assert res["verdict"] == {"H1": "NOT SUPPORTED", "H2": "NOT SUPPORTED"}
    assert "direction" in res["hypotheses"]["H1"]["failed"] and res["hypotheses"]["H1"]["bootstrap"]["p"] < 0.01


def test_below_the_minimum_sample_there_is_no_verdict_at_all():
    res = analyze.run_analysis(synthetic(protocol.MIN_SIGNALS - 1, obstacle_effect=-0.9, flip_effect=+0.9))
    assert res["verdict"] == "UNDERPOWERED -- NO VERDICT"
    assert "descriptive only" in analyze.render(res)


def test_placebo_world_does_not_depend_on_row_order():
    sigs = synthetic(300)
    a = analyze.run_analysis(sigs)["hypotheses"]["H1"]["placebo_effect"]
    b = analyze.run_analysis(list(reversed(sigs)))["hypotheses"]["H1"]["placebo_effect"]
    assert a == pytest.approx(b)


def test_h2_leaves_out_signals_with_no_flip_or_an_entry_exactly_on_it():
    sigs = synthetic(50)
    sigs[0]["levels"].gex["gamma_flip"] = None
    sigs[1]["levels"].gex["gamma_flip"] = sigs[1]["entry"]
    h1, h2, skipped = analyze.group_rows(sigs, lambda s: s["levels"])
    assert len(h1) == 50 and len(h2) == 48 and skipped == {"no_gamma_flip": 1, "entry_on_flip": 1}


# ---------------------------------------------------------------- the run-once rule

def test_analysis_runs_once_and_coverage_never_reads_outcomes(tmp_path, monkeypatch):
    sigs = synthetic(60)
    monkeypatch.setattr(analyze, "load_signals", lambda cache_dir: sigs)
    monkeypatch.setattr(analyze, "attach_levels", lambda rows, client: (rows, {}))
    monkeypatch.setattr(analyze, "RESULTS_FILE", str(tmp_path / "RESULTS.md"))
    args = argparse.Namespace(cache_dir=str(tmp_path), allow_rerun=False)

    analyze.cmd_analyze(args, None)
    marker = tmp_path / protocol.ANALYSIS_MARKER_FILE
    assert json.loads(marker.read_text())["reruns"] == [] and (tmp_path / "RESULTS.md").exists()
    with pytest.raises(SystemExit, match="allows one run"):
        analyze.cmd_analyze(args, None)

    analyze.cmd_analyze(argparse.Namespace(cache_dir=str(tmp_path), allow_rerun=True), None)
    assert len(json.loads(marker.read_text())["reruns"]) == 1                # the rerun is on the record

    def boom(cache_dir):
        raise AssertionError("coverage must not open the outcome file")
    monkeypatch.setattr(analyze, "load_signals", boom)
    monkeypatch.setattr(analyze, "load_keys", lambda cache_dir: [{"ticker": "A", "date": "d", "prior_date": "p"}])
    analyze.cmd_coverage(args, None)                                         # would raise if it read outcomes
