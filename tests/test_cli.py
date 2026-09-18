from types import SimpleNamespace

import main


def test_scan_command_end_to_end_against_fixtures(fake_client, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main, "UnusualWhalesClient", lambda: fake_client)
    out = tmp_path / "report.html"

    main.cmd_scan(SimpleNamespace(ticker="SPY", date=None, block_floor=200_000, html=str(out)))

    printed = capsys.readouterr().out
    assert "call_wall=445.5" in printed
    assert "Top gamma strikes" in printed
    assert "Options flow bias: bullish" in printed
    assert "Top gamma strikes (vol basis)" in out.read_text(encoding="utf-8")
