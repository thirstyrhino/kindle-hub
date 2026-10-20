"""Nifty, Sensex, USD/INR from Yahoo Finance's public chart endpoint.

Unofficial endpoint: free and keyless, but it can rate-limit or change. When it fails,
this screen marks itself unavailable and the playlist skips it.
"""
from datetime import time

from core import fmt

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
INSTRUMENTS = [
    {"symbol": "^NSEI", "name": "Nifty 50", "kind": "index"},
    {"symbol": "^BSESN", "name": "Sensex", "kind": "index"},
    {"symbol": "INR=X", "name": "USD / INR", "kind": "fx"},
]


def _one(ctx, inst):
    if ctx.demo:
        raw = ctx.fixture(f"yahoo_{inst['symbol'].strip('^').replace('=', '_')}.json")
    else:
        raw = ctx.get_json(CHART.format(symbol=inst["symbol"]), params={"range": "1mo", "interval": "1d"},
                           headers={"Accept": "application/json"}, retries=1)
    res = raw["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    price = res["meta"].get("regularMarketPrice") or closes[-1]
    prev = closes[-2] if len(closes) >= 2 else res["meta"].get("chartPreviousClose")
    change = price - prev if prev else 0.0
    pct = (change / prev * 100) if prev else 0.0
    decimals = 4 if inst["kind"] == "fx" else 2
    return {
        "name": inst["name"],
        "value": ("₹" if inst["kind"] == "fx" else "") + fmt.indian(price, 2),
        "change": ("+" if change >= 0 else "−") + fmt.indian(abs(change), decimals if inst["kind"] == "fx" else 2),
        "pct": f"{'+' if pct >= 0 else '−'}{abs(pct):.2f}%",
        "up": change >= 0,
        "spark_svg": fmt.sparkline(closes[-22:], 150, 44),
    }


def fetch(ctx):
    rows, errors = [], []
    for inst in INSTRUMENTS:
        try:
            rows.append(_one(ctx, inst))
        except Exception as e:
            errors.append(inst["name"])
            ctx.log(f"markets: {inst['name']} unavailable: {e}")
    now = ctx.now
    open_now = now.weekday() < 5 and time(9, 15) <= now.time() <= time(15, 30)
    return {
        "available": bool(rows),
        "rows": rows,
        "missing": errors,
        "session": "Market open" if open_now else "Last close",
    }


def tile(data):
    """Summary for the Kindle Hub card on Bookshelf's home screen."""
    rows = data["rows"]
    first, rest = rows[0], [f"{r['name']} {r['value']} {r['pct']}" for r in rows[1:3]]
    return {
        "heading": f"{first['name']} · {data['session']}",
        "value": first["value"],
        "suffix": first["pct"],
        "sub": rest[0] if rest else None,
        "context": rest[1] if len(rest) > 1 else None,
    }
