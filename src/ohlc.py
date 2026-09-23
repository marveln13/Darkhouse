"""GET /api/stock/{ticker}/ohlc/{candle_size}"""
from .models import Candle

# Verified live 2026-09-23: these sizes return intraday candles; 1d returns a different row shape and is not used here.
CANDLE_SIZES = ("1m", "5m", "15m", "30m", "1h")


def candles(client, ticker, candle_size="5m", date=None, session="r"):
    """Intraday candles for one trading day, oldest first. `session` keeps one market_time ("r" = regular hours,
    "pr" pre-market, "po" post-market); None keeps all. The API returns rows newest-first, so they are sorted here."""
    if candle_size not in CANDLE_SIZES:
        raise ValueError(f"candle_size must be one of {CANDLE_SIZES}, got {candle_size!r}")
    params = {"date": date} if date else {}
    raw = client.get(f"/api/stock/{ticker}/ohlc/{candle_size}", params=params)
    rows = [Candle.from_api(r) for r in raw.get("data", raw)]
    if session is not None:
        rows = [c for c in rows if c.market_time == session]
    return sorted(rows, key=lambda c: c.start_time)
