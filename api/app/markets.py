import asyncio
import json
import logging
import math
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from . import markets_data as U
from .db import get_conn
from .deps import current_user
from .events import UPSERT, feed_status

log = logging.getLogger("xyron.markets")
router = APIRouter(prefix="/api/markets")

UA = "Mozilla/5.0 (X11; Linux aarch64) XYRON/1.0 (private dashboard)"
YAHOO_GAP = 0.8          # seconds between any two Yahoo requests
SPARK_PAUSE = 4          # seconds between sparkline requests, so quotes keep priority
FINNHUB_GAP = 1.25       # about 48 requests a minute, under the free limit of 60
CRYPTO_EVERY = 10        # seconds between Binance price refreshes
COINGECKO_EVERY = 600    # seconds between top-100 list refreshes
SPARK_EVERY = 10800      # sparklines are refreshed every 3 hours per instrument
STALE_QUIET = 25 * 60    # an index quiet this long during its session is shown as "quiet"
WATCH_LIMIT = 30
FAST_TIER = 24           # US symbols refreshed every minute while the market is open
ALWAYS_FAST = ["TTWO", "NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "META", "SPY", "QQQ"]
US_EXCHANGES = {"NMS", "NYQ", "NGM", "NCM", "PCX", "ASE", "BTS", "NIM", "NYS"}
KIND_OF_YAHOO = {"EQUITY": "stock", "ETF": "stock", "INDEX": "index", "FUTURE": "commodity", "CURRENCY": "fx", "MUTUALFUND": "stock"}
STATE = {"finnhub_ok": True, "open_exchanges": set(), "finnhub_warned": False}


# ---------- small helpers ----------
def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def http_json(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


_ylock = threading.Lock()
_ylast = [0.0]


def yahoo_chart(symbol, rng="1d", interval="1d"):
    """One Yahoo chart request, never faster than YAHOO_GAP apart (an unofficial feed, so we are gentle)."""
    with _ylock:
        wait = YAHOO_GAP - (time.monotonic() - _ylast[0])
        if wait > 0:
            time.sleep(wait)
        _ylast[0] = time.monotonic()
    data = http_json("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol, safe="") + f"?range={rng}&interval={interval}")
    res = ((data.get("chart") or {}).get("result") or [None])[0]
    if not isinstance(res, dict):
        raise ValueError("no data for " + symbol)
    return res


def parse_yahoo(res):
    m = res.get("meta") or {}
    price = num(m.get("regularMarketPrice"))
    if price is None:
        return None
    prev = num(m.get("chartPreviousClose")) or num(m.get("previousClose"))
    ts = num(m.get("regularMarketTime"))
    return {"price": price, "prev_close": prev, "change_abs": (price - prev) if prev else None,
            "change_pct": ((price / prev - 1) * 100) if prev else None, "day_high": num(m.get("regularMarketDayHigh")),
            "day_low": num(m.get("regularMarketDayLow")), "volume": num(m.get("regularMarketVolume")), "currency": m.get("currency"),
            "quoted_at": datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None, "name": m.get("longName") or m.get("shortName"),
            "exchange": m.get("exchangeName"), "itype": m.get("instrumentType")}


def parse_spark(res, points=48):
    closes = [c for c in (((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []) if num(c) is not None]
    if len(closes) > points:
        step = len(closes) / points
        closes = [closes[min(len(closes) - 1, int(i * step))] for i in range(points)] + [closes[-1]]
    return [round(float(c), 6) for c in closes]


def finnhub_quote(symbol, key):
    """None for an unknown ticker; raises HTTPError (401 bad key, 429 slow down) otherwise."""
    d = http_json("https://finnhub.io/api/v1/quote?symbol=" + urllib.parse.quote(symbol, safe="") + "&token=" + urllib.parse.quote(key, safe=""))
    c = num(d.get("c"))
    if not c:
        return None
    t = num(d.get("t"))
    return {"price": c, "prev_close": num(d.get("pc")), "change_abs": num(d.get("d")), "change_pct": num(d.get("dp")), "day_high": num(d.get("h")),
            "day_low": num(d.get("l")), "volume": None, "currency": "USD", "quoted_at": datetime.fromtimestamp(t, tz=timezone.utc) if t else datetime.now(timezone.utc)}


def binance_pairs():
    return {r["symbol"] for r in http_json("https://api.binance.com/api/v3/ticker/price") if isinstance(r, dict) and str(r.get("symbol", "")).endswith("USDT")}


def binance_24h(symbols):
    url = "https://api.binance.com/api/v3/ticker/24hr?symbols=" + urllib.parse.quote(json.dumps(symbols, separators=(",", ":")), safe="")
    return http_json(url)


def parse_binance(row):
    price = num(row.get("lastPrice"))
    sym = str(row.get("symbol", ""))
    if price is None or not sym.endswith("USDT"):
        return None
    close = num(row.get("closeTime"))
    return {"symbol": sym[:-4], "price": price, "prev_close": num(row.get("openPrice")), "change_abs": num(row.get("priceChange")),
            "change_pct": num(row.get("priceChangePercent")), "day_high": num(row.get("highPrice")), "day_low": num(row.get("lowPrice")),
            "volume": num(row.get("quoteVolume")), "currency": "USD",
            "quoted_at": datetime.fromtimestamp(close / 1000, tz=timezone.utc) if close else datetime.now(timezone.utc)}


def coingecko_top():
    headers = {"x-cg-demo-api-key": os.environ["COINGECKO_API_KEY"]} if os.environ.get("COINGECKO_API_KEY") else {}
    return http_json("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
                     "&sparkline=true&price_change_percentage=1h%2C24h%2C7d", headers=headers, timeout=30)


def parse_coingecko(items):
    out, seen = [], set()
    for i, c in enumerate(items if isinstance(items, list) else []):
        if not isinstance(c, dict) or not c.get("symbol"):
            continue
        sym = str(c["symbol"]).upper()
        if sym in seen or not re.fullmatch(r"[A-Z0-9]{1,12}", sym):
            continue
        seen.add(sym)
        spark = [float(p) for p in ((c.get("sparkline_in_7d") or {}).get("price") or []) if num(p) is not None]
        if len(spark) > 48:
            step = len(spark) / 48
            spark = [spark[int(k * step)] for k in range(48)] + [spark[-1]]
        out.append({"id": c.get("id"), "symbol": sym, "name": str(c.get("name") or sym)[:60], "price": num(c.get("current_price")),
                    "market_cap": num(c.get("market_cap")), "rank": int(num(c.get("market_cap_rank")) or i + 1), "volume": num(c.get("total_volume")),
                    "change_pct": num(c.get("price_change_percentage_24h_in_currency", c.get("price_change_percentage_24h"))),
                    "change_1h": num(c.get("price_change_percentage_1h_in_currency")), "change_7d": num(c.get("price_change_percentage_7d_in_currency")),
                    "day_high": num(c.get("high_24h")), "day_low": num(c.get("low_24h")), "spark": spark, "stable": sym in U.STABLECOINS})
    return out


# ---------- stock exchanges: open, closed, break ----------
_tzcache = {}


def tz_of(name):
    if name not in _tzcache:
        try:
            _tzcache[name] = ZoneInfo(name)
        except Exception:
            log.warning("time zone %s not found; using UTC", name)
            _tzcache[name] = timezone.utc
    return _tzcache[name]


def fmt_delta(td):
    mins = max(0, int(td.total_seconds() // 60))
    d, rem = divmod(mins, 1440)
    h, m = divmod(rem, 60)
    if d:
        return f"{d} d {h} h"
    return f"{h} h {m:02d} min" if h else f"{m} min"


def exchange_status(ex, now_utc, quote_age=None):
    """Open, break (lunch), closed or quiet (scheduled open but the index has stopped moving, so likely a holiday)."""
    tz = tz_of(ex["tz"])
    local = now_utc.astimezone(tz)
    sessions = [(dtime(a, b), dtime(c, d)) for a, b, c, d in ex["sessions"]]

    def at(day, t):
        return datetime.combine(day.date(), t, tzinfo=tz)

    state, label, nxt = "closed", "", None
    if local.weekday() in ex["days"]:
        for s, e in sessions:
            if s <= local.time() < e:
                state, nxt = "open", at(local, e)
                break
        else:
            later = [at(local, s) for s, _ in sessions if at(local, s) > local]
            if later and local.time() > sessions[0][0]:
                state, nxt = "break", later[0]
            elif later:
                nxt = later[0]
    if nxt is None:
        for k in range(1, 9):
            day = local + timedelta(days=k)
            if day.weekday() in ex["days"]:
                nxt = at(day, sessions[0][0])
                break
    if state == "open":
        label = "closes in " + fmt_delta(nxt - local)
        if quote_age is not None and quote_age > STALE_QUIET:
            state, label = "quiet", "no recent trades (holiday?)"
    elif nxt is not None:
        label = "opens in " + fmt_delta(nxt - local)
    hours = ", ".join(f"{s:%H:%M}\u2013{e:%H:%M}" for s, e in sessions)
    return {"state": state, "local_time": f"{local:%a %H:%M}", "label": label, "hours": hours, "next_at": nxt.isoformat() if nxt else None}


def us_state(now_utc):
    et = now_utc.astimezone(tz_of("America/New_York"))
    if et.weekday() >= 5:
        return "closed"
    t = et.time()
    if dtime(9, 30) <= t < dtime(16, 0):
        return "open"
    if dtime(4, 0) <= t < dtime(20, 0):
        return "extended"
    return "closed"


def us_interval(tier, state):
    return {("A", "open"): 60, ("A", "extended"): 180, ("A", "closed"): 1800,
            ("B", "open"): 300, ("B", "extended"): 600, ("B", "closed"): 1800}[(tier, state)]


def yahoo_interval(kind, exchange_open):
    if kind == "fx":
        return 60
    if kind == "commodity":
        return 90
    return 120 if exchange_open else 900


# ---------- the database ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
  symbol TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  currency TEXT,
  price DOUBLE PRECISION,
  prev_close DOUBLE PRECISION,
  change_abs DOUBLE PRECISION,
  change_pct DOUBLE PRECISION,
  day_high DOUBLE PRECISION,
  day_low DOUBLE PRECISION,
  volume DOUBLE PRECISION,
  market_cap DOUBLE PRECISION,
  rank INT,
  source TEXT,
  quoted_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ,
  spark JSONB NOT NULL DEFAULT '[]',
  meta JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS quotes_kind_idx ON quotes (kind);
CREATE TABLE IF NOT EXISTS market_watch (
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, symbol)
);
CREATE TABLE IF NOT EXISTS quote_history (
  symbol TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  price DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS quote_history_idx ON quote_history (symbol, ts DESC);
"""
SEED = """INSERT INTO quotes (symbol, kind, name, currency, meta) VALUES (%s,%s,%s,%s,%s)
ON CONFLICT (symbol) DO UPDATE SET kind = EXCLUDED.kind, name = EXCLUDED.name, meta = quotes.meta || EXCLUDED.meta"""
PRICE_UPDATE = """UPDATE quotes SET price = %(price)s, prev_close = COALESCE(%(prev_close)s, prev_close), change_abs = %(change_abs)s,
  change_pct = %(change_pct)s, day_high = COALESCE(%(day_high)s, day_high), day_low = COALESCE(%(day_low)s, day_low),
  volume = COALESCE(%(volume)s, volume), currency = COALESCE(%(currency)s, currency), source = %(source)s,
  quoted_at = COALESCE(%(quoted_at)s, quoted_at), fetched_at = now() WHERE symbol = %(symbol)s"""
CRYPTO_UPSERT = """INSERT INTO quotes (symbol, kind, name, currency, price, change_pct, market_cap, volume, rank, day_high, day_low, source, quoted_at, fetched_at, spark, meta)
VALUES (%(symbol)s,'crypto',%(name)s,'USD',%(price)s,%(change_pct)s,%(market_cap)s,%(volume)s,%(rank)s,%(day_high)s,%(day_low)s,'coingecko',now(),now(),%(spark)s,%(meta)s)
ON CONFLICT (symbol) DO UPDATE SET name = EXCLUDED.name, market_cap = EXCLUDED.market_cap, rank = EXCLUDED.rank, spark = EXCLUDED.spark, meta = EXCLUDED.meta,
  volume = COALESCE(EXCLUDED.volume, quotes.volume),
  price = CASE WHEN quotes.source = 'binance' AND quotes.fetched_at > now() - interval '3 minutes' THEN quotes.price ELSE EXCLUDED.price END,
  change_pct = CASE WHEN quotes.source = 'binance' AND quotes.fetched_at > now() - interval '3 minutes' THEN quotes.change_pct ELSE EXCLUDED.change_pct END,
  source = CASE WHEN quotes.source = 'binance' AND quotes.fetched_at > now() - interval '3 minutes' THEN quotes.source ELSE 'coingecko' END,
  quoted_at = CASE WHEN quotes.source = 'binance' AND quotes.fetched_at > now() - interval '3 minutes' THEN quotes.quoted_at ELSE now() END,
  fetched_at = CASE WHEN quotes.source = 'binance' AND quotes.fetched_at > now() - interval '3 minutes' THEN quotes.fetched_at ELSE now() END"""


def init_schema():
    with get_conn() as conn:
        conn.execute(SCHEMA)


def universe_rows():
    rows, n = [], 0

    def add(sym, kind, name, cur, meta):
        nonlocal n
        n += 1
        rows.append((sym, kind, name, cur, Jsonb({**meta, "ord": n})))
    for t, name, sector in U.US_STOCKS:
        add(t, "stock", name, "USD", {"sector": sector, "country": "United States", "feed": "finnhub"})
    for t, name in U.ETFS:
        add(t, "stock", name, "USD", {"sector": "ETF", "country": "United States", "feed": "finnhub"})
    for t, name, country in U.INTL_STOCKS:
        add(t, "stock", name, None, {"sector": "International", "country": country, "feed": "yahoo"})
    for t, name, country in U.INDICES:
        add(t, "index", name, None, {"country": country, "feed": "yahoo"})
    for t, name, unit, group in U.COMMODITIES:
        add(t, "commodity", name, "USD", {"unit": unit, "group": group, "feed": "yahoo"})
    for t, name in U.FX:
        add(t, "fx", name, None, {"feed": "yahoo"})
    return rows


def seed_universe():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(SEED, universe_rows())


def store_prices(rows, source):
    """rows: dicts with a symbol and the fields of a quote."""
    if not rows:
        return
    full = [{"prev_close": None, "change_abs": None, "change_pct": None, "day_high": None, "day_low": None, "volume": None, "currency": None, "quoted_at": None, **r, "source": source} for r in rows]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(PRICE_UPDATE, full)


def store_crypto(coins):
    rows = [{**c, "spark": Jsonb(c["spark"]), "meta": Jsonb({"cg_id": c["id"], "change_1h": c["change_1h"], "change_7d": c["change_7d"], "stable": c["stable"], "ord": 100000 + c["rank"]})}
            for c in coins if c["price"] is not None]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(CRYPTO_UPSERT, rows)
        if rows:
            conn.execute("DELETE FROM quotes WHERE kind = 'crypto' AND NOT (symbol = ANY(%s)) AND COALESCE(meta->>'watch', '') = ''", ([r["symbol"] for r in rows],))
    return len(rows)


def store_spark(symbol, spark):
    with get_conn() as conn:
        conn.execute("UPDATE quotes SET spark = %s WHERE symbol = %s", (Jsonb(spark), symbol))


def load_watch():
    """All users' watched symbols, with how each is priced."""
    with get_conn() as conn:
        return conn.execute("SELECT DISTINCT w.symbol, q.kind, COALESCE(q.meta->>'feed', 'yahoo') AS feed FROM market_watch w JOIN quotes q ON q.symbol = w.symbol").fetchall()


def yahoo_symbol(symbol, kind, feed="yahoo"):
    if kind == "crypto":
        return f"{symbol}-USD"
    if feed == "finnhub" and "." in symbol:
        return symbol.replace(".", "-")  # BRK.B on Finnhub is BRK-B on Yahoo
    return symbol


def us_symbols():
    """US tickers in the order they are refreshed: fast tier first (always-fast names, then watchlists), then the rest."""
    base = [s for s, _, _ in U.US_STOCKS] + [s for s, _ in U.ETFS]
    watch = [w["symbol"] for w in load_watch() if w["feed"] == "finnhub"]
    fast = []
    for s in ALWAYS_FAST + watch + base:
        if s not in fast and len(fast) < FAST_TIER:
            fast.append(s)
    rest = [s for s in base + watch if s not in fast]
    return [(s, "A") for s in fast] + [(s, "B") for s in dict.fromkeys(rest)]


def yahoo_targets():
    """(database symbol, kind, Yahoo symbol) for everything Yahoo prices."""
    out = [(s, "index", s) for s, _, _ in U.INDICES] + [(s, "commodity", s) for s, _, _, _ in U.COMMODITIES] + [(s, "fx", s) for s, _ in U.FX]
    out += [(s, "stock", s) for s, _, _ in U.INTL_STOCKS]
    for w in load_watch():
        if w["feed"] != "finnhub":
            out.append((w["symbol"], w["kind"], w["symbol"]))
    if not STATE["finnhub_ok"]:  # no working Finnhub key: Yahoo (delayed) covers the US stocks too
        out += [(s, "stock", yahoo_symbol(s, "stock", "finnhub")) for s, _ in us_symbols()]
    return list(dict.fromkeys(out))


def exchange_of_symbol(symbol):
    if symbol in U.INDEX_EXCHANGE:
        return U.INDEX_EXCHANGE[symbol]
    for suffix, ex in U.SUFFIX_EXCHANGE.items():
        if symbol.endswith(suffix):
            return ex
    return None


# ---------- exchange events for the globe ----------
def exchange_rows(quotes, now):
    out = []
    for ex in U.EXCHANGES:
        q = quotes.get(ex["index"]) or {}
        age = (now - q["quoted_at"]).total_seconds() if q.get("quoted_at") else None
        st = exchange_status(ex, now, age)
        chg = q.get("change_pct")
        detail = {"exchange": ex["name"], "city": ex["city"], "country": ex["country"], "lat": ex["lat"], "lon": ex["lon"], "index": ex["index_name"], "index_symbol": ex["index"],
                  "level": q.get("price"), "change_pct": chg, "currency": q.get("currency"), "state": st["state"], "local_time": st["local_time"],
                  "label": st["label"], "hours": st["hours"], "id": ex["id"]}
        title = f"{ex['name']} \u2014 {ex['index_name']}" + (f" {chg:+.2f}%" if chg is not None else "")
        out.append({"ex": ex, "detail": detail, "title": title, "change": chg or 0.0, "state": st["state"]})
    return out


def rebuild_exchange_layer():
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        quotes = {r["symbol"]: r for r in conn.execute("SELECT symbol, price, change_pct, currency, quoted_at FROM quotes WHERE kind = 'index'").fetchall()}
        rows = exchange_rows(quotes, now)
        events = [("markets", f"exchange|{r['ex']['id']}", "markets", r["title"], r["ex"]["lat"], r["ex"]["lon"], float(r["change"]), now, None, None, Jsonb(r["detail"])) for r in rows]
        with conn.cursor() as cur:
            cur.executemany(UPSERT, events)
        conn.execute("DELETE FROM events WHERE source = 'markets' AND fetched_at < %s", (now,))
    STATE["open_exchanges"] = {r["ex"]["id"] for r in rows if r["state"] == "open"}
    feed_status["markets"] = {"last_ok": now, "error": None}
    return len(events)


# ---------- the polling tasks ----------
def poll_binance(listed, pairs):
    syms = [c["symbol"] + "USDT" for c in listed if not c["stable"] and c["symbol"] + "USDT" in pairs][:100]
    if not syms:
        return 0
    rows = [p for p in (parse_binance(r) for r in binance_24h(syms)) if p]
    store_prices(rows, "binance")
    return len(rows)


async def crypto_task():
    listed, pairs, last = [], set(), 0.0
    while True:
        if not listed or time.monotonic() - last > COINGECKO_EVERY:
            try:
                coins = parse_coingecko(await asyncio.to_thread(coingecko_top))
                if coins:
                    await asyncio.to_thread(store_crypto, coins)
                    listed, last = coins, time.monotonic()
                    pairs = await asyncio.to_thread(binance_pairs)
                    log.info("markets: %d coins listed, %d on Binance", len(coins), sum(1 for c in coins if c["symbol"] + "USDT" in pairs))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("markets: crypto list failed: %s: %s", type(e).__name__, str(e)[:100])
                last = time.monotonic() - COINGECKO_EVERY + 60  # try again in a minute
        if listed and pairs:
            try:
                await asyncio.to_thread(poll_binance, listed, pairs)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("markets: Binance failed: %s: %s", type(e).__name__, str(e)[:100])
        await asyncio.sleep(CRYPTO_EVERY)


def poll_finnhub(symbol, key):
    q = finnhub_quote(symbol, key)
    if q is None:
        return False
    store_prices([{"symbol": symbol, **q}], "finnhub")
    return True


async def us_task():
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key:
        STATE["finnhub_ok"] = False
        log.warning("markets: no FINNHUB_API_KEY, so US stocks come from Yahoo (delayed)")
        return
    due, bad, cached_syms, cached_at = {}, {}, [], 0.0
    while STATE["finnhub_ok"]:
        if time.monotonic() - cached_at > 60:
            cached_syms, cached_at = await asyncio.to_thread(us_symbols), time.monotonic()
        now = time.monotonic()
        sym, tier = min(cached_syms, key=lambda st: due.get(st[0], 0.0))
        wait = due.get(sym, 0.0) - now
        if wait > 0:
            await asyncio.sleep(min(5.0, wait))
            continue
        state = us_state(datetime.now(timezone.utc))
        try:
            ok = await asyncio.to_thread(poll_finnhub, sym, key)
            if ok:
                bad[sym] = 0
                due[sym] = time.monotonic() + us_interval(tier, state) * random.uniform(0.9, 1.1)
            else:
                bad[sym] = bad.get(sym, 0) + 1
                due[sym] = time.monotonic() + (86400 if bad[sym] >= 3 else 600)
        except asyncio.CancelledError:
            raise
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                STATE["finnhub_ok"] = False
                log.error("markets: Finnhub rejected the key (HTTP %s), so US stocks fall back to Yahoo (delayed)", e.code)
                return
            due[sym] = time.monotonic() + (60 if e.code == 429 else 300)
            if e.code == 429:
                await asyncio.sleep(60)
        except Exception as e:
            due[sym] = time.monotonic() + 300
            log.warning("markets: Finnhub %s failed: %s", sym, type(e).__name__)
        await asyncio.sleep(FINNHUB_GAP)


def poll_yahoo(symbol, ysym):
    q = parse_yahoo(yahoo_chart(ysym))
    if not q:
        return False
    store_prices([{"symbol": symbol, **{k: q[k] for k in ("price", "prev_close", "change_abs", "change_pct", "day_high", "day_low", "volume", "currency", "quoted_at")}}], "yahoo")
    return True


async def yahoo_task():
    due, bad = {}, {}
    while True:
        targets = await asyncio.to_thread(yahoo_targets)
        pick = min(targets, key=lambda t: due.get(t[0], 0.0)) if targets else None
        if not pick:
            await asyncio.sleep(30)
            continue
        sym, kind, ysym = pick
        wait = due.get(sym, 0.0) - time.monotonic()
        if wait > 0:
            await asyncio.sleep(min(5.0, wait))
            continue
        ex = exchange_of_symbol(sym)
        is_open = ex in STATE["open_exchanges"] if ex else (kind in ("commodity", "fx") or us_state(datetime.now(timezone.utc)) != "closed")
        try:
            ok = await asyncio.to_thread(poll_yahoo, sym, ysym)
            bad[sym] = 0 if ok else bad.get(sym, 0) + 1
            due[sym] = time.monotonic() + (yahoo_interval(kind, is_open) if ok else (86400 if bad[sym] >= 3 else 600)) * random.uniform(0.9, 1.1)
        except asyncio.CancelledError:
            raise
        except urllib.error.HTTPError as e:
            due[sym] = time.monotonic() + (120 if e.code == 429 else 600)
            if e.code == 429:
                log.warning("markets: Yahoo asked us to slow down; pausing a minute")
                await asyncio.sleep(60)
        except Exception as e:
            bad[sym] = bad.get(sym, 0) + 1
            due[sym] = time.monotonic() + (86400 if bad[sym] >= 3 else 600)
            log.warning("markets: Yahoo %s failed: %s", sym, type(e).__name__)


async def spark_task():
    await asyncio.sleep(90)  # let the first prices arrive before spending requests on history
    due = {}
    while True:
        with_spark = await asyncio.to_thread(lambda: [(r["symbol"], r["kind"], r["meta"].get("feed", "yahoo")) for r in _all_rows()])
        targets = [(yahoo_symbol(s, k, f), s) for s, k, f in with_spark if k != "crypto"]
        if not targets:
            await asyncio.sleep(60)
            continue
        ysym, sym = min(targets, key=lambda t: due.get(t[1], 0.0))
        wait = due.get(sym, 0.0) - time.monotonic()
        if wait > 0:
            await asyncio.sleep(min(30.0, wait))
            continue
        try:
            n = await asyncio.to_thread(poll_spark_for, ysym, sym)
            due[sym] = time.monotonic() + SPARK_EVERY * random.uniform(0.9, 1.1) if n else time.monotonic() + 3600
        except asyncio.CancelledError:
            raise
        except Exception as e:
            due[sym] = time.monotonic() + 3600
            log.warning("markets: sparkline %s failed: %s", sym, type(e).__name__)
        await asyncio.sleep(SPARK_PAUSE)


def poll_spark_for(ysym, sym):
    spark = parse_spark(yahoo_chart(ysym, "5d", "60m"))
    if len(spark) >= 2:
        store_spark(sym, spark)
    return len(spark)


def _all_rows():
    with get_conn() as conn:
        return conn.execute("SELECT symbol, kind, meta FROM quotes").fetchall()


async def exchange_task():
    while True:
        try:
            await asyncio.to_thread(rebuild_exchange_layer)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("markets: exchange layer failed")
        await asyncio.sleep(60)


def snapshot_history():
    with get_conn() as conn:
        conn.execute("INSERT INTO quote_history (symbol, ts, price) SELECT symbol, now(), price FROM quotes WHERE price IS NOT NULL")
        conn.execute("DELETE FROM quote_history WHERE ts < now() - interval '14 days'")
        conn.execute("DELETE FROM quotes WHERE COALESCE(meta->>'watch', '') <> '' AND symbol NOT IN (SELECT symbol FROM market_watch)")


async def history_task():
    await asyncio.sleep(120)
    while True:
        try:
            await asyncio.to_thread(snapshot_history)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("markets: history snapshot failed")
        await asyncio.sleep(300)


async def guarded(name, fn):
    """Run a task forever; if it crashes, say so and start it again."""
    while True:
        try:
            await fn()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("markets: %s crashed, restarting in a minute", name)
            await asyncio.sleep(60)


async def ingest_loop():
    await asyncio.sleep(50)
    try:
        await asyncio.to_thread(init_schema)
        await asyncio.to_thread(seed_universe)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("markets setup failed")
        return
    log.info("markets: tracking %d instruments", len(universe_rows()))
    await asyncio.gather(guarded("crypto", crypto_task), guarded("us", us_task), guarded("yahoo", yahoo_task),
                         guarded("sparklines", spark_task), guarded("exchanges", exchange_task), guarded("history", history_task))


# ---------- the API ----------
_cache = {}
_clock = threading.Lock()


def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    with _clock:
        hit = _cache.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
        try:
            value = fn()
        except Exception as e:
            log.warning("markets %s failed: %s: %s", key[0], type(e).__name__, str(e)[:100])
            if hit:
                return hit[1]
            raise HTTPException(502, "Market data is unavailable right now")
        _cache[key] = (time.time() + ttl, value)
        return value


def out_row(r, now):
    return {"symbol": r["symbol"], "name": r["name"], "kind": r["kind"], "price": r["price"], "change_pct": r["change_pct"], "change_abs": r["change_abs"],
            "prev_close": r["prev_close"], "day_high": r["day_high"], "day_low": r["day_low"], "volume": r["volume"], "market_cap": r["market_cap"],
            "rank": r["rank"], "currency": r["currency"], "source": r["source"], "quoted_at": r["quoted_at"].isoformat() if r["quoted_at"] else None,
            "age": int((now - r["fetched_at"]).total_seconds()) if r["fetched_at"] else None, "spark": r["spark"] or [], "meta": r["meta"] or {}}


COLS = "symbol, kind, name, currency, price, prev_close, change_abs, change_pct, day_high, day_low, volume, market_cap, rank, source, quoted_at, fetched_at, spark, meta"


@router.get("/quotes")
def quotes(kind: str = Query(..., pattern="^(crypto|stock|index|commodity|fx|watch)$"), q: str = Query("", max_length=40),
           limit: int = Query(300, ge=1, le=300), user=Depends(current_user)):
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        if kind == "watch":
            rows = conn.execute(f"SELECT {COLS} FROM quotes WHERE symbol IN (SELECT symbol FROM market_watch WHERE user_id = %s) AND price IS NOT NULL", (user["id"],)).fetchall()
        else:
            rows = conn.execute(f"SELECT {COLS} FROM quotes WHERE kind = %s AND price IS NOT NULL", (kind,)).fetchall()
    if q.strip():
        needle = q.strip().lower()
        rows = [r for r in rows if needle in r["symbol"].lower() or needle in r["name"].lower()]
    rows.sort(key=lambda r: (r["rank"] if kind == "crypto" and r["rank"] else (r["meta"] or {}).get("ord", 10 ** 9), r["symbol"]))
    return {"quotes": [out_row(r, now) for r in rows[:limit]], "updated": now.isoformat()}


@router.get("/movers")
def movers(user=Depends(current_user)):
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        rows = conn.execute(f"SELECT {COLS} FROM quotes WHERE kind IN ('stock', 'crypto') AND price IS NOT NULL AND change_pct IS NOT NULL AND fetched_at > now() - interval '3 days'").fetchall()
    out = {}
    for kind in ("stock", "crypto"):
        r = sorted((x for x in rows if x["kind"] == kind and not (x["meta"] or {}).get("stable")), key=lambda x: x["change_pct"])
        out[kind] = {"losers": [out_row(x, now) for x in r[:6]], "gainers": [out_row(x, now) for x in reversed(r[-6:])]}
    return out


@router.get("/ticker")
def ticker(user=Depends(current_user)):
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        rows = {r["symbol"]: r for r in conn.execute(f"SELECT {COLS} FROM quotes WHERE symbol = ANY(%s) AND price IS NOT NULL", (U.TICKER,)).fetchall()}
    return [{k: out_row(rows[s], now)[k] for k in ("symbol", "name", "kind", "price", "change_pct", "currency")} for s in U.TICKER if s in rows]


@router.get("/exchanges")
def exchanges(user=Depends(current_user)):
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        qs = {r["symbol"]: r for r in conn.execute("SELECT symbol, price, change_pct, currency, quoted_at FROM quotes WHERE kind = 'index'").fetchall()}
    return [{**r["detail"], "title": r["title"]} for r in exchange_rows(qs, now)]


RANGES = {"1d": ("1d", "5m", 120), "5d": ("5d", "30m", 600), "1mo": ("1mo", "1d", 900), "6mo": ("6mo", "1d", 1800), "1y": ("1y", "1d", 3600)}


@router.get("/chart")
def chart(symbol: str = Query(..., pattern=r"^[A-Za-z0-9^.=\-]{1,15}$"), range: str = Query("1d", pattern="^(1d|5d|1mo|6mo|1y)$"), user=Depends(current_user)):
    with get_conn() as conn:
        row = conn.execute("SELECT symbol, kind, currency, meta FROM quotes WHERE symbol = %s", (symbol,)).fetchone()
    if not row:
        raise HTTPException(404, "Unknown symbol")
    rng, interval, ttl = RANGES[range]
    ysym = yahoo_symbol(row["symbol"], row["kind"], (row["meta"] or {}).get("feed", "yahoo"))

    def build():
        res = yahoo_chart(ysym, rng, interval)
        times = res.get("timestamp") or []
        closes = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        pts = [[int(t) * 1000, round(float(c), 6)] for t, c in zip(times, closes) if num(c) is not None and num(t) is not None]
        if len(pts) > 300:
            step = len(pts) / 300
            pts = [pts[int(i * step)] for i in range(300)] + [pts[-1]]
        return {"symbol": row["symbol"], "range": range, "currency": row["currency"], "points": pts}
    return cached(("chart", row["symbol"], range), ttl, build)


SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.=^\-]{0,14}$")


class WatchIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=15)


def canonical_symbol(raw):
    s = raw.strip().upper()
    if re.fullmatch(r"[A-Z]{1,5}-[A-Z]", s):
        s = s.replace("-", ".")  # BRK-B and BRK.B are the same share class
    return s


@router.get("/watchlist")
def watch_list(user=Depends(current_user)):
    with get_conn() as conn:
        return [r["symbol"] for r in conn.execute("SELECT symbol FROM market_watch WHERE user_id = %s ORDER BY added_at", (user["id"],)).fetchall()]


@router.post("/watchlist")
def watch_add(body: WatchIn, user=Depends(current_user)):
    sym = canonical_symbol(body.symbol)
    if not SYMBOL_RE.match(sym):
        raise HTTPException(400, "That does not look like a ticker. Try NVDA, RR.L or 7974.T.")
    with get_conn() as conn:
        if conn.execute("SELECT count(*) AS n FROM market_watch WHERE user_id = %s", (user["id"],)).fetchone()["n"] >= WATCH_LIMIT:
            raise HTTPException(400, f"Your watchlist is full ({WATCH_LIMIT}).")
        known = conn.execute("SELECT symbol, kind FROM quotes WHERE symbol = %s", (sym,)).fetchone()
    if known and known["kind"] == "crypto":
        raise HTTPException(400, "Crypto is already in the Crypto tab.")
    if not known:
        q = None
        # "RR.L" is London; "BF.B" is a US share class that Yahoo spells BF-B, so try the plain spelling first
        for cand in [sym] + ([sym.replace(".", "-")] if re.fullmatch(r"[A-Z]{1,5}\.[A-Z]", sym) else []):
            try:
                q = parse_yahoo(yahoo_chart(cand))
            except Exception:
                q = None
            if q:
                break
        if not q or q["itype"] == "CRYPTOCURRENCY":
            raise HTTPException(404, "I could not find that ticker.")
        us = q["exchange"] in US_EXCHANGES and q["itype"] in ("EQUITY", "ETF")
        meta = {"watch": True, "feed": "finnhub" if us else "yahoo", "sector": "Watchlist", "country": "United States" if us else "", "ord": 10 ** 8}
        with get_conn() as conn:
            conn.execute(SEED, (sym, KIND_OF_YAHOO.get(q["itype"], "stock"), (q["name"] or sym)[:80], q["currency"], Jsonb(meta)))
        store_prices([{"symbol": sym, **{k: q[k] for k in ("price", "prev_close", "change_abs", "change_pct", "day_high", "day_low", "volume", "currency", "quoted_at")}}], "yahoo")
    with get_conn() as conn:
        conn.execute("INSERT INTO market_watch (user_id, symbol) VALUES (%s,%s) ON CONFLICT DO NOTHING", (user["id"], sym))
    return watch_list(user)


@router.delete("/watchlist/{symbol}")
def watch_remove(symbol: str = Path(..., pattern=r"^[A-Za-z0-9^.=\-]{1,15}$"), user=Depends(current_user)):
    with get_conn() as conn:
        conn.execute("DELETE FROM market_watch WHERE user_id = %s AND symbol = %s", (user["id"], canonical_symbol(symbol)))
    return watch_list(user)
