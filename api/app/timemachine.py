"""Time machine: remembers what happened and serves the last day or week of it, ready to replay on the globe.

Already stored by other features: earthquakes (30 days), headlines (7 days), market prices (14 days), ship tracks (kept for 8 days once this is installed).
Not stored by anything else, so recorded here: when each natural hazard first appeared, and football kick-offs, goals and full times.
"""
import asyncio
import logging
import time as _time
from bisect import bisect_right
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.types.json import Jsonb

from .db import get_conn
from .deps import current_user

log = logging.getLogger("xyron.timemachine")
router = APIRouter(prefix="/api/time")

WINDOWS = (24, 168)               # hours: a day or a week
KEEP_DAYS = 10
RECORD_EVERY = 60
CAPS = {"q": 4000, "h": 2000, "f": 3000, "n": 2500}   # most items of each kind sent for one window
SHIP_CAP = {24: 3000, 168: 2000}
SHIP_GAP_MIN = {24: 60, 168: 180}                      # minutes between points kept for each ship
FT_MINUTES = 115                                       # a match that was already over when first seen ends about this long after kick-off
MARKET_NONE = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS timeline_moments (
  id BIGSERIAL PRIMARY KEY, key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL,
  lat DOUBLE PRECISION, lon DOUBLE PRECISION, title TEXT NOT NULL, detail JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS timeline_moments_idx ON timeline_moments (kind, ts DESC);
CREATE TABLE IF NOT EXISTS timeline_state (key TEXT PRIMARY KEY, value JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
"""
_ready = {"done": False}


def ensure_schema():
    if not _ready["done"]:
        with get_conn() as conn:
            conn.execute(SCHEMA)
        _ready["done"] = True


def _when(text):
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(timezone.utc) if text else None
    except ValueError:
        return None


def _score(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


# ---------- remembering ----------
def record_hazards(conn, now):
    """When did each natural hazard first show up? NASA's own date is used when it is recent, otherwise the moment we first saw it."""
    have = {r["key"] for r in conn.execute("SELECT key FROM timeline_moments WHERE kind = 'hazard'").fetchall()}
    made = 0
    for r in conn.execute("SELECT external_id, title, lat, lon, detail FROM events WHERE layer = 'hazards'").fetchall():
        key = "hz|" + str(r["external_id"]).split("|", 1)[-1]   # the feed's own id, without its 'hazard|' prefix
        if key in have:
            continue
        d = r["detail"] or {}
        when = _when(d.get("date"))
        ts = when if when and now - timedelta(days=8) <= when <= now else now
        detail = {"category": d.get("category"), "label": d.get("category_label") or "Natural event", "magnitude": d.get("magnitude"), "unit": d.get("unit")}
        made += bool(conn.execute("INSERT INTO timeline_moments (key, kind, ts, lat, lon, title, detail) VALUES (%s,'hazard',%s,%s,%s,%s,%s) ON CONFLICT (key) DO NOTHING RETURNING id",
                                  (key, ts, r["lat"], r["lon"], str(r["title"])[:160], Jsonb(detail))).fetchone())
    return made


def _moment(conn, key, kind, ts, lat, lon, title, detail):
    return bool(conn.execute("INSERT INTO timeline_moments (key, kind, ts, lat, lon, title, detail) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (key) DO NOTHING RETURNING id",
                             (key, kind, ts, lat, lon, title[:160], Jsonb(detail))).fetchone())


def _state(conn, key):
    row = conn.execute("SELECT value FROM timeline_state WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else None


def _set_state(conn, key, value):
    conn.execute("INSERT INTO timeline_state (key, value, updated_at) VALUES (%s,%s,now()) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()", (key, Jsonb(value)))


def record_matches(conn, now):
    """Kick-off, goals and full time. A goal is only known when we see the score change; earlier matches get a kick-off and an approximate full time."""
    made = 0
    rows = conn.execute("SELECT title, state, start_at, lat, lon, detail FROM matches WHERE sport = 'football' AND lat IS NOT NULL AND start_at <= %s AND start_at > %s AND detail ? 'home'",
                        (now + timedelta(minutes=5), now - timedelta(days=8))).fetchall()
    for r in rows:
        d = r["detail"]
        eid = d.get("event_id")
        if not eid:
            continue
        home, away = (d.get("home") or {}), (d.get("away") or {})
        cur = {"state": r["state"], "hs": _score(home.get("score")), "as": _score(away.get("score"))}
        base = {"home": home.get("name"), "away": away.get("name"), "league": d.get("league"), "hs": cur["hs"], "as": cur["as"]}
        lat, lon = r["lat"], r["lon"]
        made += _moment(conn, f"m|{eid}|ko", "kickoff", r["start_at"], lat, lon, f"{base['home']} vs {base['away']}", {**base, "hs": 0, "as": 0})
        prev = _state(conn, f"m|{eid}")
        _set_state(conn, f"m|{eid}", cur)
        score_title = f"{base['home']} {cur['hs']}\u2013{cur['as']} {base['away']}"
        if prev is None:
            if cur["state"] == "post":  # already over when first seen: its goals are unknown, so give the final score at about the right time
                made += _moment(conn, f"m|{eid}|ft", "fulltime", min(now, r["start_at"] + timedelta(minutes=FT_MINUTES)), lat, lon, score_title, {**base, "approx": True})
            continue
        if cur["state"] in ("in", "post") and (cur["hs"] > prev["hs"] or cur["as"] > prev["as"]):
            made += _moment(conn, f"m|{eid}|g|{cur['hs']}-{cur['as']}", "goal", now, lat, lon, score_title, {**base, "scorer": "home" if cur["hs"] > prev["hs"] else "away", "minute": d.get("status")})
        if prev["state"] in ("pre", "in") and cur["state"] == "post":
            made += _moment(conn, f"m|{eid}|ft", "fulltime", now, lat, lon, score_title, {**base, "approx": False})
    return made


def record_once(now=None):
    now = now or datetime.now(timezone.utc)
    ensure_schema()
    out = {"hazards": 0, "matches": 0}
    with get_conn() as conn:
        for name, fn in (("hazards", record_hazards), ("matches", record_matches)):
            try:
                with conn.transaction():
                    out[name] = fn(conn, now)
            except Exception:
                log.exception("timemachine: recording %s failed; the other recorder carries on", name)
        conn.execute("DELETE FROM timeline_moments WHERE ts < %s", (now - timedelta(days=KEEP_DAYS),))
        conn.execute("DELETE FROM timeline_state WHERE updated_at < %s", (now - timedelta(days=KEEP_DAYS),))
    return out


async def ingest_loop():
    await asyncio.sleep(90)
    while True:
        try:
            out = await asyncio.to_thread(record_once)
            if out["hazards"] or out["matches"]:
                log.info("timemachine: recorded %d hazards, %d match moments", out["hazards"], out["matches"])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("timemachine: recording failed")
        await asyncio.sleep(RECORD_EVERY)


# ---------- answering ----------
_cache = {}


def cached(key, ttl, build, now=_time.time):
    hit = _cache.get(key)
    if hit and now() - hit[0] < ttl:
        return hit[1]
    value = build()
    _cache[key] = (now(), value)
    return value


def window_of(hours):
    if hours not in WINDOWS:
        raise HTTPException(400, "Choose 24 hours or 168 hours (7 days)")
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=hours), now


def _clip(text, n):
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1] + "\u2026"


def _https(url):
    return url if isinstance(url, str) and url.startswith("https://") and len(url) < 400 else ""


@router.get("/range")
def coverage(user=Depends(current_user)):
    """How far back each kind of history really goes, so the screen can say so honestly."""
    def build():
        now = datetime.now(timezone.utc)
        out = {}
        with get_conn() as conn:
            for name, sql in (("earthquakes", "SELECT min(occurred_at) AS t FROM events WHERE layer = 'earthquakes'"),
                              ("hazards", "SELECT min(ts) AS t FROM timeline_moments WHERE kind = 'hazard'"),
                              ("football", "SELECT min(ts) AS t FROM timeline_moments WHERE kind IN ('kickoff', 'goal', 'fulltime')"),
                              ("headlines", "SELECT min(published_at) AS t FROM headlines WHERE lat IS NOT NULL"),
                              ("ships", "SELECT min(ts) AS t FROM vessel_track"),
                              ("markets", "SELECT min(ts) AS t FROM quote_history")):
                try:
                    with conn.transaction():
                        t = conn.execute(sql).fetchone()["t"]
                except Exception:
                    t = None
                out[name] = t.isoformat() if t else None
        return {"now": now.isoformat(), "earliest": out}
    ensure_schema()
    return cached("range", 60, build)


@router.get("/moments")
def moments(hours: int = Query(24), user=Depends(current_user)):
    """Everything that happened at a point in time: [seconds, kind, lat, lon, number, title, a, b], oldest first.
    kinds: q quake (number = magnitude), h hazard (a = category, b = label), k kick-off, g goal, f full time (a = league, b = '~' if the time is approximate), n headline (a = source, b = link)."""
    start, now = window_of(hours)
    ensure_schema()

    def build():
        items = []
        with get_conn() as conn:
            q = conn.execute("SELECT occurred_at, lat, lon, severity, title FROM events WHERE layer = 'earthquakes' AND occurred_at >= %s AND occurred_at <= %s ORDER BY severity DESC NULLS LAST LIMIT %s", (start, now, CAPS["q"])).fetchall()
            items += [[int(r["occurred_at"].timestamp()), "q", round(r["lat"], 3), round(r["lon"], 3), float(r["severity"] or 0), _clip(r["title"], 90), "", ""] for r in q]
            h = conn.execute("SELECT ts, lat, lon, title, detail FROM timeline_moments WHERE kind = 'hazard' AND ts >= %s AND lat IS NOT NULL ORDER BY ts DESC LIMIT %s", (start, CAPS["h"])).fetchall()
            items += [[int(r["ts"].timestamp()), "h", round(r["lat"], 3), round(r["lon"], 3), float((r["detail"] or {}).get("magnitude") or 0), _clip(r["title"], 90), (r["detail"] or {}).get("category") or "", (r["detail"] or {}).get("label") or ""] for r in h]
            f = conn.execute("SELECT ts, kind, lat, lon, title, detail FROM timeline_moments WHERE kind IN ('kickoff', 'goal', 'fulltime') AND ts >= %s AND lat IS NOT NULL ORDER BY ts DESC LIMIT %s", (start - timedelta(hours=3), CAPS["f"])).fetchall()
            code = {"kickoff": "k", "goal": "g", "fulltime": "f"}
            items += [[int(r["ts"].timestamp()), code[r["kind"]], round(r["lat"], 3), round(r["lon"], 3), 0, _clip(r["title"], 90), _clip((r["detail"] or {}).get("league"), 40), "~" if (r["detail"] or {}).get("approx") else ""] for r in f]
            n = conn.execute("SELECT published_at, lat, lon, title, source, url FROM headlines WHERE published_at >= %s AND lat IS NOT NULL AND lon IS NOT NULL ORDER BY published_at DESC LIMIT %s", (start, CAPS["n"])).fetchall()
            items += [[int(r["published_at"].timestamp()), "n", round(r["lat"], 3), round(r["lon"], 3), 0, _clip(r["title"], 110), _clip(r["source"], 30), _https(r["url"])] for r in n]
        items.sort(key=lambda x: x[0])
        return {"from": int(start.timestamp()), "to": int(now.timestamp()), "items": items}
    return cached(("moments", hours), 120, build)


def _downsample(points, gap_min):
    """points: [(minutes, lat, lon)] in order. Keep one about every gap_min minutes, always the first and last."""
    out, last_t = [], None
    for i, p in enumerate(points):
        if last_t is None or p[0] - last_t >= gap_min or i == len(points) - 1:
            out.append(p)
            last_t = p[0]
    return out


@router.get("/ships")
def ship_tracks(hours: int = Query(24), user=Depends(current_user)):
    """The ships that moved the most in the window, each as a handful of points: {m: mmsi, n: name, k: kind, p: [[minutes from start, lat*1000, lon*1000]]}."""
    start, now = window_of(hours)
    ensure_schema()

    def build():
        from .ships_data import category_of
        cap, gap = SHIP_CAP[hours], SHIP_GAP_MIN[hours]
        anchor = start - timedelta(hours=3)
        with get_conn() as conn:
            top = [r["mmsi"] for r in conn.execute("SELECT mmsi, count(*) AS n FROM vessel_track WHERE ts >= %s GROUP BY mmsi HAVING count(*) >= 3 ORDER BY n DESC, mmsi LIMIT %s", (anchor, cap)).fetchall()]
            if not top:
                return {"from": int(start.timestamp()), "to": int(now.timestamp()), "vessels": []}
            rows = conn.execute("SELECT mmsi, ts, lat, lon FROM vessel_track WHERE mmsi = ANY(%s) AND ts >= %s ORDER BY mmsi, ts", (top, anchor)).fetchall()
            statics = {r["mmsi"]: r for r in conn.execute("SELECT mmsi, name, ship_type FROM vessel_static WHERE mmsi = ANY(%s)", (top,)).fetchall()}
        by = {}
        for r in rows:
            by.setdefault(r["mmsi"], []).append((round((r["ts"] - start).total_seconds() / 60), r["lat"], r["lon"]))
        vessels = []
        for m in top:
            pts = _downsample(by.get(m, []), gap)
            if len(pts) < 2:
                continue
            s = statics.get(m) or {}
            vessels.append({"m": m, "n": _clip(s.get("name") or "", 30), "k": category_of(s.get("ship_type")), "p": [[t, round(la * 1000), round(lo * 1000)] for t, la, lo in pts]})
        return {"from": int(start.timestamp()), "to": int(now.timestamp()), "vessels": vessels}
    return cached(("ships", hours), 600, build)


@router.get("/markets")
def market_moves(hours: int = Query(24), user=Depends(current_user)):
    """The rolling 24-hour move of every instrument, hour by hour (hundredths of a percent; null where there was no price)."""
    start, now = window_of(hours)
    ensure_schema()

    def build():
        from .markets_data import EXCHANGES
        t0 = start.replace(minute=0, second=0, microsecond=0)
        grid_from = t0 - timedelta(hours=24)
        with get_conn() as conn:
            hist = conn.execute("SELECT symbol, ts, price FROM quote_history WHERE ts >= %s ORDER BY symbol, ts", (grid_from - timedelta(hours=8),)).fetchall()
            info = {r["symbol"]: r for r in conn.execute("SELECT symbol, name, kind FROM quotes").fetchall()}
        series = {}
        for r in hist:
            series.setdefault(r["symbol"], ([], []))
            series[r["symbol"]][0].append(r["ts"].timestamp())
            series[r["symbol"]][1].append(r["price"])

        def price(sym, t):
            ts, ps = series[sym]
            i = bisect_right(ts, t) - 1
            return ps[i] if i >= 0 and t - ts[i] <= 8 * 3600 else None

        symbols, chg = [], []
        for sym in sorted(series):
            row = []
            for i in range(hours + 1):
                t = (t0 + timedelta(hours=i)).timestamp()
                if t > now.timestamp() + 1800:
                    row.append(MARKET_NONE)
                    continue
                a, b = price(sym, t), price(sym, t - 86400)
                row.append(max(-9999, min(9999, round((a / b - 1) * 10000))) if a and b else MARKET_NONE)
            if any(v is not None for v in row):
                symbols.append({"s": sym, "name": (info.get(sym) or {}).get("name") or sym, "kind": (info.get(sym) or {}).get("kind") or ""})
                chg.append(row)
        have = {s["s"] for s in symbols}
        ex = [{"id": e["id"], "name": e["name"], "city": e["city"], "lat": e["lat"], "lon": e["lon"], "index": e["index"]} for e in EXCHANGES if e["index"] in have]
        return {"from": int(t0.timestamp()), "step": 3600, "n": hours + 1, "symbols": symbols, "chg": chg, "exchanges": ex}
    return cached(("markets", hours), 600, build)
