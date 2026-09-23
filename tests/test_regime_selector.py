from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from research.regime_selector import protocol, run, stats
from research.regime_selector.regime import Regime, count_runs, label, series

POS, NEG = protocol.POS, protocol.NEG


def g(d, call, put):
    return SimpleNamespace(date=d, call_gamma=call, put_gamma=put)


def sessions(n, start=date(2026, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# ---- regime ----

def test_net_gamma_is_call_plus_signed_put_and_zero_counts_as_positive():
    assert series([g("2026-01-06", 5, -7), g("2026-01-05", 3, -1)]) == [("2026-01-05", 2), ("2026-01-06", -2)]
    assert label(-0.01) == NEG and label(0) == POS and label(1) == POS


def test_day_d_uses_the_prior_session_never_d_itself():
    r = Regime([g("2026-01-05", 1, -5), g("2026-01-06", 5, -1), g("2026-01-07", 1, -5)])
    assert r.for_day("2026-01-06") == NEG          # from 01-05, not 01-06's own POS
    assert r.for_day("2026-01-07") == POS          # from 01-06
    assert r.for_day("2026-01-10") == NEG          # a weekend/non-row day uses the last row before it
    assert r.for_day("2026-01-05") is None         # no prior session


def test_placebo_is_the_label_21_sessions_before_d_minus_1():
    days = sessions(30)
    rows = [g(d, 1 if i == 3 else 0, -1) for i, d in enumerate(days)]   # only session 3 is POS
    r = Regime(rows)
    assert r.for_day(days[25]) == NEG
    assert r.placebo_for_day(days[25]) == POS      # D-1 = session 24; 24 - 21 = session 3
    assert r.placebo_for_day(days[21]) is None     # D-1 = 20; 20 - 21 < 0
    assert protocol.PLACEBO_SHIFT_SESSIONS == 21


def test_episodes_count_runs_over_the_d_minus_1_sessions():
    assert count_runs([POS, POS, NEG, NEG, POS, NEG]) == {POS: 2, NEG: 2}
    assert count_runs([]) == {POS: 0, NEG: 0}
    days = sessions(6)
    r = Regime([g(d, 1, -5 if i in (2, 3) else 0) for i, d in enumerate(days)])     # P P N N P P
    assert r.episodes(days[1], days[5]) == {POS: 2, NEG: 1}                          # D-1 sessions 0..4: P P N N P
    assert r.episodes(days[0], days[5]) == {POS: 0, NEG: 0}                          # no prior session for day 0


# ---- statistics ----

def rows_(spec):
    """spec: [(date, group, y)]"""
    return [{"date": d, "group": grp, "y": y} for d, grp, y in spec]


def test_iso_week_groups_monday_to_sunday():
    assert stats.iso_week("2026-01-05") == stats.iso_week("2026-01-11") != stats.iso_week("2026-01-12")


def test_week_bootstrap_is_seeded_and_uses_the_registered_p():
    import numpy as np
    days = sessions(60)
    spec = [(d, "A" if i % 2 else "B", (0.3 if i % 2 else 0.1) + (0.4 if i % 7 == 0 else -0.2)) for i, d in enumerate(days)]
    rows = rows_(spec)
    a, b = stats.week_bootstrap(rows), stats.week_bootstrap(rows)
    assert a == b and a["weeks"] == len({stats.iso_week(d) for d in days})
    # recompute the registered p by hand
    weeks = sorted({stats.iso_week(d) for d in days})
    idx = {w: i for i, w in enumerate(weeks)}
    sums, counts = np.zeros((len(weeks), 2)), np.zeros((len(weeks), 2))
    for r in rows:
        j = 0 if r["group"] == "A" else 1
        sums[idx[stats.iso_week(r["date"])], j] += r["y"]
        counts[idx[stats.iso_week(r["date"])], j] += 1
    picks = np.random.default_rng(protocol.SEED).integers(0, len(weeks), size=(protocol.BOOTSTRAP_RESAMPLES, len(weeks)))
    s, c = sums[picks].sum(axis=1), counts[picks].sum(axis=1)
    ok = (c[:, 0] > 0) & (c[:, 1] > 0)
    diffs = s[ok, 0] / c[ok, 0] - s[ok, 1] / c[ok, 1]
    assert a["p"] == pytest.approx(min(1.0, 2 * min(np.mean(diffs <= 0), np.mean(diffs >= 0))))


def test_week_bootstrap_needs_both_groups_and_enough_weeks():
    assert stats.week_bootstrap(rows_([(d, "A", 1.0) for d in sessions(40)])) is None
    assert stats.week_bootstrap(rows_([(d, "A" if i % 2 else "B", 1.0) for i, d in enumerate(sessions(8))])) is None


GOOD = dict(eff=0.08, p_holm=0.01, halves={"first": 0.06, "second": 0.1}, placebo_effect=0.01,
            episodes={POS: 25, NEG: 30})


def test_verdict_supported_when_everything_holds():
    assert stats.verdict(**GOOD) == ("SUPPORTED", [])


@pytest.mark.parametrize("change,reason", [
    (dict(p_holm=0.05), "holm_p"), (dict(p_holm=None), "holm_p"),
    (dict(eff=-0.08), "direction"),
    (dict(eff=0.049, placebo_effect=0.0), "min_effect"),
    (dict(halves={"first": -0.01, "second": 0.2}), "halves"),
    (dict(halves={"first": 0.1, "second": 0.0}), "halves"),
    (dict(halves=None), "halves"),
    (dict(placebo_effect=0.04), "placebo"),        # exactly half is not "smaller than half"
    (dict(placebo_effect=-0.05), "placebo"),       # judged by magnitude
    (dict(placebo_effect=None), "placebo"),
])
def test_verdict_each_condition_fails_alone(change, reason):
    status, failed = stats.verdict(**dict(GOOD, **change))
    assert status == "NOT SUPPORTED" and reason in failed


def test_underpowered_below_20_episodes_of_either_sign():
    assert stats.verdict(**dict(GOOD, episodes={POS: 19, NEG: 40}))[0] == "UNDERPOWERED"
    assert stats.verdict(**dict(GOOD, episodes={POS: 40, NEG: 19}))[0] == "UNDERPOWERED"
    assert stats.verdict(**dict(GOOD, episodes={POS: 20, NEG: 20}))[0] == "SUPPORTED"


def test_registered_constants():
    assert (protocol.SEED, protocol.BOOTSTRAP_RESAMPLES, protocol.ALPHA, protocol.MIN_EFFECT_R, protocol.MIN_EPISODES,
            protocol.PLACEBO_MAX_RATIO, protocol.ORB_TARGET_R, protocol.ORB_MAX_BARS, protocol.UW_TIMEFRAME) == \
        (20260924, 2000, 0.05, 0.05, 20, 0.5, 2.5, 26, "2Y")
    assert protocol.HYPOTHESES["H1"]["A"] == POS and protocol.HYPOTHESES["H2"]["A"] == NEG


# ---- the live ORB UP population ----

def _utc(day, hh, mm):
    return datetime(2026, 3, day, hh, mm, tzinfo=timezone.utc)


def make_tk(signals, sim_calls, universe=("AAA",)):
    bars = [{"timestamp": _utc(10, 13, 30 + 15 * i).isoformat() if i < 2 else _utc(10, 14, 15 * (i - 2)).isoformat()}
            for i in range(6)]

    def tag(sigs, hist, pm):
        out = []
        for s in sigs:
            p = pm.get(datetime.fromisoformat(s["timestamp"]).date(), {}).get(s["ticker"])
            if p is None:
                continue
            out.append(dict(s, _confluence=s["entry_price"] > p["high"]))
        return out

    def sim(bars_, ts_list, idx, direction, entry, stop, target_r, max_bars_forward):
        sim_calls.append((idx, direction, entry, stop, target_r, max_bars_forward))
        return 1.0

    return run.Toolkit(universe, None, lambda t: bars, datetime.fromisoformat, lambda t, b: list(signals), tag, sim, None,
                       {"universe_size": 95, "m30_target_r": 3.0, "m30_hold": 13, "orb_gap_pct": 0.5, "orb_min_bar": 3,
                        "premarket_gate": True})


def test_orb_up_pairs_applies_the_premarket_gate_and_the_live_exits():
    sigs = [{"ticker": "AAA", "timestamp": _utc(10, 14, 15).isoformat(), "entry_price": 101.0, "stop_price": 99.0},
            {"ticker": "AAA", "timestamp": _utc(10, 14, 30).isoformat(), "entry_price": 100.0, "stop_price": 99.0},
            {"ticker": "AAA", "timestamp": _utc(11, 14, 30).isoformat(), "entry_price": 105.0, "stop_price": 99.0}]
    pm = {date(2026, 3, 10): {"AAA": {"high": 100.5}}}               # 03-11 has no pre-market data
    calls = []
    pairs, st = run.orb_up_pairs(make_tk(sigs, calls), pm)
    assert pairs == [("2026-03-10", 1.0)]
    assert st["no_premarket"] == 1 and st["premarket_gate_failed"] == 1 and st["gap_and_go"] == 3
    assert calls == [(3, "up", 101.0, 99.0, 2.5, 26)]              # bar starting 14:15 is index 3; 2.5R, 26 bars


def test_check_pinned_refuses_drift():
    tk = make_tk([], [])
    run.check_pinned(tk)
    for key, bad in (("universe_size", 100), ("orb_gap_pct", 1.0), ("orb_min_bar", 2), ("premarket_gate", False),
                     ("m30_target_r", 2.0), ("m30_hold", 10)):
        broken = tk._replace(constants=dict(tk.constants, **{key: bad}))
        with pytest.raises(RuntimeError, match=key):
            run.check_pinned(broken)


# ---- labelling, grouping, full analysis ----

def test_label_pairs_drops_days_without_a_prior_session():
    r = Regime([g("2026-01-05", 1, -5), g("2026-01-06", 5, -1)])
    rows, dropped = run.label_pairs([("2026-01-05", 1.0), ("2026-01-06", -1.0), ("2026-01-07", 3.0)], r)
    assert dropped == 1
    assert [(x["date"], x["regime"]) for x in rows] == [("2026-01-06", NEG), ("2026-01-07", POS)]


def test_grouping_follows_each_hypothesis_direction():
    rows = [{"date": "d", "r": 1.0, "regime": POS, "placebo": NEG}, {"date": "d", "r": 2.0, "regime": NEG, "placebo": POS}]
    h1, h2 = protocol.HYPOTHESES["H1"], protocol.HYPOTHESES["H2"]
    assert [x["group"] for x in run.grouped(rows, h1["A"], h1["B"])] == ["A", "B"]
    assert [x["group"] for x in run.grouped(rows, h2["A"], h2["B"])] == ["B", "A"]
    assert [x["group"] for x in run.grouped(rows, h1["A"], h1["B"], key="placebo")] == ["B", "A"]


def test_analyse_end_to_end_on_a_planted_effect():
    import random
    days = sessions(300)
    # irregular regime runs (seeded) -> plenty of episodes of each sign, and a 21-session shift is not aligned
    rng, labels, neg = random.Random(3), [], False
    while len(labels) < len(days):
        labels += [neg] * rng.randint(2, 9)
        neg = not neg
    reg = Regime([g(d, 1, -5 if labels[i] else 0) for i, d in enumerate(days)])
    m30, orb = [], []
    for d in days[1:]:
        lab = reg.for_day(d)
        m30.append({"date": d, "r": 0.4 if lab == POS else -0.1, "regime": lab, "placebo": reg.placebo_for_day(d)})
        orb.append({"date": d, "r": 0.0, "regime": lab, "placebo": reg.placebo_for_day(d)})
    res = run.analyse({"m30i_puts": m30, "orb_up": orb}, reg)
    h1, h2 = res["hypotheses"]["H1"], res["hypotheses"]["H2"]
    assert h1["effect"] == pytest.approx(0.5)
    assert h1["status"] == "SUPPORTED", h1["failed"]
    assert h2["effect"] == pytest.approx(0.0) and h2["status"] == "NOT SUPPORTED"
    assert min(h1["episodes"].values()) >= 20
    sec = res["secondary"]
    assert sec["selector"]["trades"] < sec["both_always"]["trades"]
    assert "VERDICT: H1 SUPPORTED, H2 NOT SUPPORTED" in run.render(res, {"sanity_mean": 0.1, "excluded": {}})


def test_run_refuses_a_second_run(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "CACHE_DIR", str(tmp_path))
    (tmp_path / protocol.MARKER_FILE).write_text("{}")
    with pytest.raises(SystemExit, match="already run once"):
        run.run(make_tk([], []))


def test_sanity_gate_stops_before_any_analysis(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "CACHE_DIR", str(tmp_path))
    reg = Regime([g(d, 1, 0) for d in sessions(10)])
    monkeypatch.setattr(run, "build", lambda tk: (reg, {"m30i_puts": [{"date": "x", "r": -0.2}], "orb_up": []}, {}))
    monkeypatch.setattr(run, "analyse", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not analyse")))
    with pytest.raises(SystemExit, match="SANITY GATE FAILED"):
        run.run(make_tk([], []))
    assert not (tmp_path / protocol.MARKER_FILE).exists()
