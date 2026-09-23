from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import main
from src import analysis, chart, darkpool, demo, gex, ohlc
from src.models import Candle, DarkPoolPriceLevels


# ---- candles ----

def test_candles_parse_sort_oldest_first_and_keep_regular_session(fake_client):
    rows = ohlc.candles(fake_client, "SPY")
    assert len(rows) == 78                                     # the fixture has 1 pre-market + 78 regular + 1 post
    assert all(c.market_time == "r" for c in rows)
    assert rows[0].start_time == "2026-09-18T13:30:00Z"        # the API returns newest first; sorted here
    assert [c.start_time for c in rows] == sorted(c.start_time for c in rows)
    assert isinstance(rows[0].open, float) and rows[0].high >= max(rows[0].open, rows[0].close)
    assert len(ohlc.candles(fake_client, "SPY", session=None)) == 80


def test_candles_reject_unknown_sizes(fake_client):
    with pytest.raises(ValueError):
        ohlc.candles(fake_client, "SPY", candle_size="1d")


# ---- chart data ----

def _candle(i, o, h, l, c):
    start = datetime(2026, 9, 18, 13, 30 + 5 * i, tzinfo=timezone.utc) if i < 6 else None
    s = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    e = start.replace(minute=start.minute + 5).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Candle(s, e, o, h, l, c, 1000, "r")


CANDLES = [_candle(0, 100, 101, 99.5, 100.5), _candle(1, 100.5, 101.2, 100, 101), _candle(2, 101, 101.5, 100.8, 101.4)]


def _levels(*rows):
    return DarkPoolPriceLevels.from_api("X", {"date": "2026-09-17", "data": [
        {"price": str(p), "dark_pool_volume": v, "regular_volume": 1000} for p, v in rows]})


def _gex(**kw):
    base = dict(ticker="X", date="2026-09-17", source="vol", time=None, call_wall=None, put_wall=None,
                gamma_flip=None, gamma_magnet=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _print(ts, price, size):
    return SimpleNamespace(executed_at=ts, price=price, size=size, notional=price * size)


def test_heavy_levels_are_the_top_n_by_dark_pool_volume():
    lv = _levels((100, 10), (101, 50), (99, 30), (102, 40))
    assert [x.price for x in chart.heavy_levels(lv, top_n=2)] == [101.0, 102.0]


def test_levels_beyond_reach_go_to_the_margin_note_not_the_chart():
    lv = _levels((100.2, 500), (150.0, 900))                  # 150 is far outside the 99.5-101.5 session
    g = _gex(call_wall=101.3, put_wall=80.0)
    c = chart.build_chart(CANDLES, lv, g, [], [])
    assert [x["price"] for x in c["dark_pool"]] == [100.2]
    assert [x["price"] for x in c["gex"]] == [101.3]
    assert {o["price"] for o in c["offscreen"]} == {150.0, 80.0}
    assert c["y_min"] < 99.5 and c["y_max"] > 101.5            # padded around candles + drawn levels only
    assert c["y_max"] < 150


def test_drawn_levels_extend_the_y_range():
    c = chart.build_chart(CANDLES, _levels((98.8, 1)), _gex(), [], [])   # within one session range below the low
    assert c["y_min"] < 98.8


def test_confluence_levels_are_flagged():
    lv = _levels((100.2, 500), (101.0, 900))
    c = chart.build_chart(CANDLES, lv, _gex(gamma_flip=100.2), [], [{"price": 100.2}])
    flags = {x["price"]: x["confluence"] for x in c["dark_pool"]}
    assert flags == {100.2: True, 101.0: False}


def test_block_markers_only_inside_the_candles_and_area_scales_with_notional():
    blocks = [_print("2026-09-18T13:32:30Z", 100.3, 1000),      # half-way through candle 0
              _print("2026-09-18T13:41:00Z", 101.2, 4000),
              _print("2026-09-18T13:29:59Z", 100.0, 9000),      # before the first candle
              _print("2026-09-18T13:45:00Z", 101.0, 9000)]      # at the last candle's end -> outside
    c = chart.build_chart(CANDLES, _levels((100, 1)), _gex(), blocks, [])
    assert c["blocks_outside"] == 2
    xs = sorted(round(b["x"], 3) for b in c["blocks"])
    assert xs == [0.5, 2.2]
    small, big = sorted(c["blocks"], key=lambda b: b["notional"])
    assert big["r"] == chart.BLOCK_R_MAX and small["r"] < big["r"]
    assert small["r"] == pytest.approx(chart.BLOCK_R_MIN + (chart.BLOCK_R_MAX - chart.BLOCK_R_MIN) * (100_300 / 404_800) ** 0.5)


def test_block_radius_edges():
    assert chart.block_radius(0, 0) == chart.BLOCK_R_MIN
    assert chart.block_radius(5, 5) == chart.BLOCK_R_MAX
    assert chart.block_radius(1, 4) < chart.block_radius(2, 4)


def test_no_candles_renders_a_note():
    assert chart.build_chart([], _levels((1, 1)), _gex(), [], []) is None
    assert "No candle data" in chart.render_chart_svg(None)


def test_rendered_svg_escapes_labels_and_embeds_no_raw_script_close():
    c = chart.build_chart(CANDLES, _levels((100.2, 500)), _gex(call_wall=101.3), [], [],
                          levels_date="<b>2026-09-17</b>", levels_note=" </script><x>")
    html = chart.render_chart_svg(c)
    assert "<svg" in html and "Call wall $101.30" in html and "DP $100.20" in html
    assert "<b>2026" not in html and "&lt;b&gt;" in html
    assert html.count("</script>") == 1                          # only the chart's own script tag closes


def test_spread_labels_keeps_a_minimum_gap():
    placed = chart._spread_labels([(100, "a", ""), (105, "b", ""), (106, "c", "")], 13)
    ys = [y for y, _, _ in placed]
    assert ys == [100, 113, 126]


# ---- prior-session levels (the default) ----

def test_prior_weekdays_skip_weekends():
    assert main.prior_weekdays("2026-09-21", n=3) == ["2026-09-18", "2026-09-17", "2026-09-16"]   # Monday


def test_prior_session_levels_skip_empty_days_and_never_use_the_session_itself():
    calls = []

    class Client:
        def get(self, path, params=None):
            calls.append((path, params))
            if path.endswith("/price-levels"):
                return {"data": [] if params["date"] == "2026-09-18" else [
                    {"price": "10", "dark_pool_volume": 5, "regular_volume": 5}]}
            return {"data": {"date": params["date"], "source": "vol", "call_wall": "11"}}

    d, lv, g = main.prior_session_levels(Client(), "X", "2026-09-21")
    assert d == "2026-09-17" and lv.levels and g.call_wall == 11.0          # 09-18 had no levels (holiday-like)
    assert all(p["date"] < "2026-09-21" for _, p in calls)


def test_scan_writes_a_chart_with_prior_session_levels(fake_client, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main, "UnusualWhalesClient", lambda: fake_client)
    out = tmp_path / "r.html"
    main.cmd_scan(SimpleNamespace(ticker="SPY", date=None, block_floor=200_000, html=str(out)))
    printed = capsys.readouterr().out
    assert "session 2026-09-18" in printed and "Levels from 2026-09-17" in printed
    page = out.read_text(encoding="utf-8")
    assert "Black Lantern" in page and "<svg" in page and "prior session" in page
    level_dates = {p.get("date") for path, p in fake_client.calls if path.endswith("/price-levels")}
    assert level_dates == {"2026-09-17"}                        # never the session's own date


def test_same_day_flag_is_labelled_hindsight(fake_client, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main, "UnusualWhalesClient", lambda: fake_client)
    out = tmp_path / "r.html"
    main.cmd_scan(SimpleNamespace(ticker="SPY", date="2026-09-18", block_floor=200_000, html=str(out),
                                  same_day_levels=True))
    assert "hindsight" in capsys.readouterr().out
    assert "hindsight" in out.read_text(encoding="utf-8")


# ---- demo mode ----

def test_demo_renders_offline_without_a_key(monkeypatch, tmp_path):
    monkeypatch.delenv("UNUSUAL_WHALES_API_KEY", raising=False)
    monkeypatch.setattr(main, "UnusualWhalesClient", lambda: (_ for _ in ()).throw(AssertionError("no API in demo")))
    out = tmp_path / "demo.html"
    main.cmd_demo(SimpleNamespace(out=str(out), open=False, block_floor=200_000))
    page = out.read_text(encoding="utf-8")
    assert "SYNTHETIC DEMO DATA" in page and "<svg" in page and "Block print" in page


def test_demo_data_is_deterministic_and_goes_through_the_real_parsers():
    a, b = demo.build(), demo.build()
    assert [c.close for c in a["candles"]] == [c.close for c in b["candles"]]
    assert len(a["candles"]) == 78 and a["levels"].levels and a["gex"].put_wall == 99.8
    assert analysis.block_prints(a["prints"])                   # the demo has real block prints to draw


# ---- day-bounded dark-pool pager ----

def _raw_print(ts, i, price="100.00", size=5000):
    return {"ticker": "X", "executed_at": ts, "price": price, "size": size, "premium": "0", "volume": 0,
            "market_center": "L", "canceled": False, "nbbo_bid": None, "nbbo_ask": None, "tracking_id": i}


class PagedClient:
    """Newest-first pages keyed by the older_than cursor, like the real endpoint."""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, path, params=None):
        self.calls.append(params)
        return {"data": self.pages.get(params.get("older_than"), [])}


def test_prints_for_day_filters_to_the_session_and_stops_at_the_day_boundary():
    pages = {
        None: [_raw_print("2026-09-18T20:10:00Z", 1), _raw_print("2026-09-18T19:00:00Z", 2)],     # 16:10 ET post-close, 15:00
        "2026-09-18T19:00:00Z": [_raw_print("2026-09-18T13:31:00Z", 3), _raw_print("2026-09-18T13:00:00Z", 4)],  # 09:31, 09:00 pre
        "2026-09-18T13:00:00Z": [_raw_print("2026-09-17T19:00:00Z", 5), _raw_print("2026-09-17T18:00:00Z", 6)],  # prior day
    }
    client = PagedClient(pages)
    out, complete = darkpool.prints_for_day(client, "X", "2026-09-18", min_premium=200_000, page_limit=2, max_pages=10)
    assert [p.tracking_id for p in out] == [2, 3]                  # regular hours of 09-18 only
    assert complete is True
    assert len(client.calls) == 3 and all(c["min_premium"] == 200_000 for c in client.calls)


def test_prints_for_day_reports_truncation_when_the_page_cap_runs_out():
    pages = {None: [_raw_print("2026-09-18T19:00:00Z", 1), _raw_print("2026-09-18T18:00:00Z", 2)],
             "2026-09-18T18:00:00Z": [_raw_print("2026-09-18T17:00:00Z", 3), _raw_print("2026-09-18T16:00:00Z", 4)]}
    out, complete = darkpool.prints_for_day(PagedClient(pages), "X", "2026-09-18", page_limit=2, max_pages=2)
    assert complete is False and len(out) == 4


def test_prints_for_day_stops_on_a_short_page():
    out, complete = darkpool.prints_for_day(PagedClient({None: [_raw_print("2026-09-18T15:00:00Z", 1)]}),
                                            "X", "2026-09-18", page_limit=500)
    assert complete is True and len(out) == 1


# ---- reach scales with the session range ----

def test_reach_is_one_session_range_beyond_high_and_low():
    # CANDLES span 99.5..101.5 (range 2.0) -> levels drawn from 97.5 to 103.5
    c = chart.build_chart(CANDLES, _levels((97.6, 1), (97.4, 1), (103.4, 1), (103.6, 1)), _gex(), [], [])
    assert sorted(x["price"] for x in c["dark_pool"]) == [97.6, 103.4]
    assert sorted(o["price"] for o in c["offscreen"]) == [97.4, 103.6]


def test_reach_has_a_floor_for_very_quiet_sessions():
    flat = [_candle(0, 100, 100.01, 99.99, 100), _candle(1, 100, 100.01, 99.99, 100)]
    c = chart.build_chart(flat, _levels((100.2, 1), (100.3, 1)), _gex(), [], [])    # 0.25% of 100 = 0.25
    assert [x["price"] for x in c["dark_pool"]] == [100.2]


def test_truncation_note_is_shown_on_the_chart():
    c = chart.build_chart(CANDLES, _levels((100, 1)), _gex(), [], [], blocks_note="Block prints truncated <x>")
    assert "Block prints truncated &lt;x&gt;" in chart.render_chart_svg(c)
