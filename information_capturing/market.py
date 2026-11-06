"""Market data: market value, daily prices, the full options chain and prediction markets (Kalshi, Polymarket)."""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .common import (DATA, append_rows, get_json, name_pattern, now, read_json, read_rows, today, write_json)

CAPS = DATA / "calendar" / "market_caps.json"
PRICE_FIELDS = ["date", "open", "high", "low", "close", "adj_close", "volume", "dividends", "splits"]
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
PM_FIELDS = ["captured_at", "venue", "market", "title", "yes_bid", "yes_ask", "last", "volume", "close_time"]


def _yf(ticker):
    import yfinance as yf  # imported here: it is slow to import and only market steps need it
    return yf.Ticker(ticker)


def caps():
    return read_json(CAPS, {})


def refresh_caps(tickers):
    """Market value of each ticker today (yfinance); None when there is no quote."""
    c = caps()
    for t in sorted(set(tickers)):
        try:
            fi = _yf(t).fast_info
            cap = fi.get("marketCap")
            c[t] = {"date": today().isoformat(), "market_cap": float(cap) if cap else None,
                    "price": fi.get("lastPrice"), "shares": fi.get("shares")}
        except Exception as e:  # noqa: BLE001 - one bad ticker must not stop the others
            c[t] = {"date": today().isoformat(), "market_cap": None, "error": f"{type(e).__name__}: {e}"[:200]}
    write_json(CAPS, c)
    return c


def _session_closed():
    """True once today's US session is over (16:15 New York), so today's bar is final."""
    return datetime.now(ZoneInfo("America/New_York")).time() >= datetime.strptime("16:15", "%H:%M").time()


def prices(path, ticker, years=2):
    """Appends the missing daily bars (raw prices plus adjusted close) to a CSV; returns the number added."""
    rows = read_rows(path)
    last = rows[-1]["date"] if rows else None
    start = date.fromisoformat(last) + timedelta(days=1) if last else today() - timedelta(days=365 * years)
    if start > today():
        return 0
    h = _yf(ticker).history(start=start.isoformat(), end=(today() + timedelta(days=1)).isoformat(),
                            auto_adjust=False, actions=True)
    new = []
    for ts, r in h.iterrows():
        d = ts.date()
        if (last and d.isoformat() <= last) or (d == today() and not _session_closed()):
            continue
        new.append({"date": d.isoformat(), "open": r.get("Open"), "high": r.get("High"), "low": r.get("Low"),
                    "close": r.get("Close"), "adj_close": r.get("Adj Close"), "volume": r.get("Volume"),
                    "dividends": r.get("Dividends"), "splits": r.get("Stock Splits")})
    append_rows(path, new, PRICE_FIELDS)
    return len(new)


def options(folder, ticker):
    """Saves today's full options chain (every expiration) as market/options/<date>.json.gz; skips if already saved.

    Options history cannot be bought back later for free, so the chain is stored even before it is analysed.
    """
    p = folder / "options" / f"{today().isoformat()}.json.gz"
    if p.exists():
        return 0
    t = _yf(ticker)
    exps = list(t.options or [])
    rows = []
    for e in exps:
        ch = t.option_chain(e)
        for kind, df in (("call", ch.calls), ("put", ch.puts)):
            for r in df.to_dict("records"):
                rows.append({"expiration": e, "type": kind} | {k: (str(v) if k == "lastTradeDate" else v) for k, v in r.items()})
    if not exps:
        return 0
    price = t.fast_info.get("lastPrice")
    write_json(p, {"ticker": ticker, "captured_at": now(), "underlying_price": price, "expirations": exps,
                   "rows": rows}, gz=True)
    return len(rows)


# ---------------------------------------------------------------- prediction markets


def kalshi_discover(names_by_ticker):
    """Weekly: downloads every Kalshi series (kept, gzip) and links those whose title names a company or drug."""
    d = get_json(f"{KALSHI}/series") or {}
    series = d.get("series") or []
    write_json(DATA / "market" / "kalshi" / f"series_{today().isoformat()}.json.gz", d, gz=True)
    links = {}
    for ticker, names in names_by_ticker.items():
        pat = name_pattern(names)
        if not pat:
            continue
        hits = [s["ticker"] for s in series
                if pat.search(" ".join([s.get("title") or "", s.get("ticker") or "", " ".join(s.get("tags") or [])]))]
        if hits:
            links[ticker] = hits
    write_json(DATA / "market" / "kalshi" / "links.json", {"updated": today().isoformat(), "links": links})
    return links


def kalshi_daily(folder, ticker):
    links = (read_json(DATA / "market" / "kalshi" / "links.json", {}) or {}).get("links", {}).get(ticker, [])
    rows, raw = [], {}
    for s in links:
        d = get_json(f"{KALSHI}/markets", {"series_ticker": s, "status": "open", "limit": 200}) or {}
        raw[s] = d
        for m in d.get("markets") or []:
            rows.append({"captured_at": now(), "venue": "kalshi", "market": m.get("ticker"), "title": m.get("title"),
                         "yes_bid": m.get("yes_bid_dollars"), "yes_ask": m.get("yes_ask_dollars"),
                         "last": m.get("last_price_dollars"), "volume": m.get("volume_fp") or m.get("volume"),
                         "close_time": m.get("close_time")})
    if raw:
        write_json(folder / "prediction_markets" / f"{today().isoformat()}_kalshi.json.gz", raw, gz=True)
    append_rows(folder / "prediction_markets.csv", rows, PM_FIELDS)
    return len(rows)


def polymarket_daily(folder, names):
    """Searches Polymarket for each drug name and keeps open markets whose question names it."""
    pat = name_pattern(names)
    if not pat:
        return 0
    rows, raw = [], {}
    for n in sorted(set(names), key=len, reverse=True)[:3]:
        d = get_json(f"{GAMMA}/public-search", {"q": n, "limit_per_type": 20, "events_status": "active"}) or {}
        for e in d.get("events") or []:
            for m in e.get("markets") or []:
                if m.get("closed") or not pat.search((m.get("question") or "") + " " + (e.get("title") or "")):
                    continue
                raw[m.get("id")] = m
                prices = m.get("outcomePrices")
                prices = json.loads(prices) if isinstance(prices, str) else prices
                rows.append({"captured_at": now(), "venue": "polymarket", "market": m.get("id"), "title": m.get("question"),
                             "yes_bid": m.get("bestBid"), "yes_ask": m.get("bestAsk"),
                             "last": m.get("lastTradePrice") or (prices or [None])[0], "volume": m.get("volume"),
                             "close_time": m.get("endDate")})
    if raw:
        write_json(folder / "prediction_markets" / f"{today().isoformat()}_polymarket.json.gz", raw, gz=True)
    append_rows(folder / "prediction_markets.csv", rows, PM_FIELDS)
    return len(rows)
