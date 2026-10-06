import asyncio
import json
import logging
import math
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Path as FPath, Response

from . import ships_data as D
from .db import get_conn
from .deps import current_user
from .events import feed_status

log = logging.getLogger("xyron.ships")
router = APIRouter()

URL = "wss://stream.aisstream.io/v0/stream"
PORTS_FILE = Path(__file__).parent / "data" / "ports.json"
STALE_AFTER = 2 * 3600       # a ship not heard from for this long is no longer drawn
DROP_AFTER = 6 * 3600        # ...and is forgotten after this long
SNAPSHOT_EVERY = 20
FLUSH_EVERY = 60
TRACK_MIN_KM = 2.0           # a trail point is kept when the ship has moved this far...
TRACK_MIN_SECONDS = 900      # ...and at least this long has passed
TRACK_KEEP_HOURS = 36
MAX_SHIPS = 60000
KNOT = 0.514444

VESSELS = {}     # mmsi -> latest position report
STATIC = {}      # mmsi -> name, type, size, destination ...
TRACKBUF = []    # trail points waiting to be saved
DIRTY = set()    # mmsi whose static data changed and must be saved
STATS = {"connected": False, "messages": 0, "positions": 0, "statics": 0, "dropped": 0, "last_message": None, "last_error": None, "refused": None}
REFUSED_WAIT = 300           # seconds to wait after AISstream refuses us (a wrong key, say), so we never hammer them
SNAPSHOT = {"body": b'{"ships":[],"updated":null}', "count": 0}


# ---------- reading AIS messages ----------
def valid_mmsi(m):
    return isinstance(m, int) and not isinstance(m, bool) and 200_000_000 <= m <= 799_999_999  # ships; base stations, buoys and aircraft use other ranges


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def km_between(la1, lo1, la2, lo2):
    x = math.radians(lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2))
    y = math.radians(la2 - la1)
    return 6371.0 * math.hypot(x, y)


def flag_of(mmsi):
    return D.MID.get(mmsi // 1_000_000, "")


def eta_iso(eta, now):
    """AIS gives only month, day, hour and minute; pick the year that makes it the next such date."""
    eta = eta if isinstance(eta, dict) else {}
    mo, da, hr, mi = (num(eta.get(k)) for k in ("Month", "Day", "Hour", "Minute"))
    if not mo or not da or not (1 <= mo <= 12) or not (1 <= da <= 31):
        return None
    hr = int(hr) if hr is not None and 0 <= hr < 24 else 0
    mi = int(mi) if mi is not None and 0 <= mi < 60 else 0
    for year in (now.year, now.year + 1, now.year - 1):
        try:
            when = datetime(year, int(mo), int(da), hr, mi, tzinfo=timezone.utc)
        except ValueError:
            continue
        if when >= now - timedelta(days=30):
            return when.isoformat()
    return None


def handle_position(body, now_ts):
    mmsi, lat, lon = body.get("UserID"), num(body.get("Latitude")), num(body.get("Longitude"))
    if not valid_mmsi(mmsi) or lat is None or lon is None:
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0) or lat == 91 or lon == 181:
        return False
    sog, cog, hdg, nav = num(body.get("Sog")), num(body.get("Cog")), num(body.get("TrueHeading")), num(body.get("NavigationalStatus"))
    v = VESSELS.get(mmsi)
    if v is None:
        v = VESSELS[mmsi] = {"trk": None}
    v.update({"lat": lat, "lon": lon, "sog": sog if sog is not None and sog < 102.3 else None, "cog": cog if cog is not None and cog < 360 else None,
              "hdg": hdg if hdg is not None and 0 <= hdg < 360 else None, "nav": int(nav) if nav is not None and 0 <= nav <= 15 else 15, "t": now_ts})
    last = v["trk"]
    if last is None or (now_ts - last[0] >= TRACK_MIN_SECONDS and km_between(last[1], last[2], lat, lon) >= TRACK_MIN_KM):
        v["trk"] = (now_ts, lat, lon)
        if len(TRACKBUF) < 400_000:
            TRACKBUF.append((mmsi, datetime.fromtimestamp(now_ts, tz=timezone.utc), lat, lon, v["sog"]))
    return True


def handle_static(body, now_ts):
    mmsi = body.get("UserID")
    if not valid_mmsi(mmsi):
        return False
    dim = body.get("Dimension") if isinstance(body.get("Dimension"), dict) else {}
    a, b, c, d = (int(num(dim.get(k)) or 0) for k in ("A", "B", "C", "D"))
    new = {"name": str(body.get("Name") or "").strip(" @")[:40], "imo": int(num(body.get("ImoNumber")) or 0) or None,
           "callsign": str(body.get("CallSign") or "").strip(" @")[:10], "type": int(num(body.get("Type")) or 0), "length": a + b, "beam": c + d,
           "draught": num(body.get("MaximumStaticDraught")), "destination": str(body.get("Destination") or "").strip(" @")[:30],
           "eta": body.get("Eta") if isinstance(body.get("Eta"), dict) else None}
    old = STATIC.get(mmsi)
    if old != new:
        STATIC[mmsi] = new
        DIRTY.add(mmsi)
    return True


def handle_message(raw, now_ts=None):
    """One text frame from AISstream. Returns 'position', 'static' or None."""
    STATS["messages"] += 1
    now_ts = now_ts or time.time()
    STATS["last_message"] = now_ts
    try:
        msg = json.loads(raw)
    except (ValueError, TypeError):
        STATS["dropped"] += 1
        return None
    if not isinstance(msg, dict):
        return None
    if "error" in msg:
        STATS["last_error"] = STATS["refused"] = str(msg["error"])[:120]
        return None
    kind = msg.get("MessageType")
    body = (msg.get("Message") or {}).get(kind) if isinstance(msg.get("Message"), dict) else None
    if not isinstance(body, dict):
        return None
    if kind == "PositionReport":
        STATS["positions"] += 1
        return "position" if handle_position(body, now_ts) else None
    if kind == "ShipStaticData":
        STATS["statics"] += 1
        return "static" if handle_static(body, now_ts) else None
    return None


# ---------- ports and destinations ----------
_ports = {}


def norm(text):
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", s).split())


def ports():
    if not _ports:
        by_code, by_name = {}, {}
        rows = json.loads(PORTS_FILE.read_text(encoding="ascii")) if PORTS_FILE.exists() else []
        have = {r[0] for r in rows}
        rows += [[c, n, la, lo] for c, n, la, lo in D.PORT_EXTRAS if c not in have]
        for code, name, lat, lon in rows:
            p = {"locode": code, "name": name, "lat": lat, "lon": lon, "country": code[:2]}
            by_code[code] = p
            by_name.setdefault(norm(name), []).append(p)
        _ports.update({"code": by_code, "name": by_name})
    return _ports


NOT_A_PORT = {"", "NONE", "NA", "N A", "TBA", "TBN", "TBD", "UNKNOWN", "FOR ORDERS", "FOR ORDER", "ORDERS", "ORDER", "AT SEA", "ANCHORED", "ANCHORAGE", "DRIFTING",
              "FISHING", "FISHING GROUND", "LOCAL", "LOCAL WATERS", "CHECK", "TEST", "NOT SET", "NO DESTINATION", "SEE REMARKS", "SEE ORDERS", "CLASS A", "CLASS B", "OPEN SEA"}


def pick(options, near):
    if not options:
        return None
    if near and len(options) > 1:
        return min(options, key=lambda p: km_between(near[0], near[1], p["lat"], p["lon"]))
    return options[0]


def resolve_destination(raw, near=None):
    """Turn the free text a ship broadcasts ("SGSIN", "ROTTERDAM", "HOUSTON > NEW ORLEANS") into a port, if we can."""
    text = norm(raw)
    if text in NOT_A_PORT or not re.search(r"[A-Z]", text):
        return None
    p = ports()
    segments = [s for s in re.split(r"\s*(?:>+|-+>|=+>|\bTO\b|[|;,/\\])\s*", (raw or "").upper()) if s.strip()]
    # a hyphen can separate two ports ("SGSIN-NLRTM") or sit inside a name, so it is only tried after the whole piece fails
    hyphen = [h for seg in segments for h in re.split(r"\s*-\s*", seg) if h.strip()] if any("-" in seg for seg in segments) else []
    for seg in list(reversed(segments or [raw or ""])) + list(reversed(hyphen)):
        seg = re.sub(r"\bETA\b.*$", "", seg).strip()
        compact = re.sub(r"[^A-Z0-9]", "", seg)
        if len(compact) == 5 and compact[:2].isalpha() and compact in p["code"]:
            return {**p["code"][compact], "how": "port code"}
        n = norm(seg)
        if n in NOT_A_PORT:
            continue
        hit = pick(p["name"].get(n), near)
        if hit:
            return {**hit, "how": "port name"}
        words = n.split()
        if len(words) > 1 and len(words[0]) == 2:  # "SG SINGAPORE"
            hit = pick(p["name"].get(" ".join(words[1:])), near)
            if hit:
                return {**hit, "how": "port name"}
        if len(words) > 1 and words[-1].isdigit():  # "ROTTERDAM 12"
            hit = pick(p["name"].get(" ".join(words[:-1])), near)
            if hit:
                return {**hit, "how": "port name"}
    return None


# ---------- the snapshot the globe reads ----------
def build_snapshot(now_ts):
    rows = []
    for mmsi, v in list(VESSELS.items()):
        if now_ts - v["t"] > STALE_AFTER or "lat" not in v:
            continue
        st = STATIC.get(mmsi) or {}
        rows.append([mmsi, round(v["lat"], 4), round(v["lon"], 4), round(v["sog"], 1) if v["sog"] is not None else 0,
                     round(v["cog"]) if v["cog"] is not None else -1, round(v["hdg"]) if v["hdg"] is not None else -1,
                     st.get("type", 0), st.get("length", 0), st.get("name", ""), v["nav"], int(v["t"]), flag_of(mmsi)])
    if len(rows) > MAX_SHIPS:
        rows.sort(key=lambda r: -r[10])
        rows = rows[:MAX_SHIPS]
    body = json.dumps({"ships": rows, "updated": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return body, len(rows)


def forget_old(now_ts):
    old = [m for m, v in VESSELS.items() if now_ts - v["t"] > DROP_AFTER]
    for m in old:
        del VESSELS[m]
    return len(old)


# ---------- saving ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS vessel_static (
  mmsi BIGINT PRIMARY KEY, name TEXT, imo BIGINT, callsign TEXT, ship_type INT, length INT, beam INT,
  draught DOUBLE PRECISION, destination TEXT, eta JSONB, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS vessel_track (
  mmsi BIGINT NOT NULL, ts TIMESTAMPTZ NOT NULL, lat DOUBLE PRECISION NOT NULL, lon DOUBLE PRECISION NOT NULL, sog REAL
);
CREATE INDEX IF NOT EXISTS vessel_track_idx ON vessel_track (mmsi, ts);
"""
STATIC_UPSERT = """INSERT INTO vessel_static (mmsi, name, imo, callsign, ship_type, length, beam, draught, destination, eta, updated_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
ON CONFLICT (mmsi) DO UPDATE SET name = EXCLUDED.name, imo = EXCLUDED.imo, callsign = EXCLUDED.callsign, ship_type = EXCLUDED.ship_type, length = EXCLUDED.length,
  beam = EXCLUDED.beam, draught = EXCLUDED.draught, destination = EXCLUDED.destination, eta = EXCLUDED.eta, updated_at = now()"""


def init_schema():
    with get_conn() as conn:
        conn.execute(SCHEMA)


def load_static():
    with get_conn() as conn:
        rows = conn.execute("SELECT mmsi, name, imo, callsign, ship_type, length, beam, draught, destination, eta FROM vessel_static WHERE updated_at > now() - interval '30 days'").fetchall()
    for r in rows:
        STATIC[r["mmsi"]] = {"name": r["name"] or "", "imo": r["imo"], "callsign": r["callsign"] or "", "type": r["ship_type"] or 0, "length": r["length"] or 0,
                             "beam": r["beam"] or 0, "draught": r["draught"], "destination": r["destination"] or "", "eta": r["eta"]}
    return len(rows)


def flush():
    from psycopg.types.json import Jsonb
    dirty = list(DIRTY)
    DIRTY.clear()
    points = TRACKBUF[:]
    del TRACKBUF[:len(points)]
    with get_conn() as conn:
        with conn.cursor() as cur:
            if dirty:
                cur.executemany(STATIC_UPSERT, [(m, s["name"], s["imo"], s["callsign"], s["type"], s["length"], s["beam"], s["draught"], s["destination"],
                                                 Jsonb(s["eta"]) if s["eta"] is not None else None) for m in dirty for s in [STATIC[m]]])
            if points:
                cur.executemany("INSERT INTO vessel_track (mmsi, ts, lat, lon, sog) VALUES (%s,%s,%s,%s,%s)", points)
    return len(dirty), len(points)


def prune():
    with get_conn() as conn:
        conn.execute("DELETE FROM vessel_track WHERE ts < now() - make_interval(hours => %s)", (TRACK_KEEP_HOURS,))
        conn.execute("DELETE FROM vessel_static WHERE updated_at < now() - interval '30 days'")


def trail_of(mmsi, limit=150):
    with get_conn() as conn:
        rows = conn.execute("SELECT ts, lat, lon FROM vessel_track WHERE mmsi = %s AND ts > now() - make_interval(hours => %s) ORDER BY ts", (mmsi, TRACK_KEEP_HOURS)).fetchall()
    pts = [[int(r["ts"].timestamp()), r["lat"], r["lon"]] for r in rows]
    pts += [[int(t.timestamp()), la, lo] for m, t, la, lo, _s in TRACKBUF if m == mmsi]
    pts.sort()
    if len(pts) > limit:
        step = len(pts) / limit
        pts = [pts[int(i * step)] for i in range(limit)] + [pts[-1]]
    return pts


# ---------- the live stream ----------
def subscription(key):
    return {"APIKey": key, "BoundingBoxes": [[[-90, -180], [90, 180]]], "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}


class Refused(Exception):
    """AISstream sent an error message instead of data."""


async def stream_loop(url=None):
    key = os.environ.get("AISSTREAM_API_KEY", "").strip()
    if not key:
        log.warning("ships: no AISSTREAM_API_KEY, so the ships layer stays empty")
        return
    try:
        import websockets
    except ImportError:
        log.error("ships: the 'websockets' package is not installed; rebuild the container")
        return
    backoff = 5
    while True:
        try:
            async with websockets.connect(url or URL, compression="deflate", max_size=2 ** 22, ping_interval=20, ping_timeout=40, open_timeout=20) as ws:
                await ws.send(json.dumps(subscription(key)))
                STATS["connected"] = True
                log.info("ships: connected to AISstream")
                n = 0
                first = True
                async for raw in ws:
                    if handle_message(raw):
                        backoff = 5  # only real data counts as the connection working
                        if first:
                            first = False
                            log.info("ships: receiving ship positions")
                    if STATS["refused"]:
                        raise Refused(STATS["refused"])
                    n += 1
                    if n % 200 == 0:
                        await asyncio.sleep(0)  # let the web server breathe during busy moments
        except asyncio.CancelledError:
            raise
        except Refused as e:
            STATS["connected"] = False
            STATS["refused"] = None
            log.error("ships: AISstream refused the connection (%s); trying again in %d s", e, REFUSED_WAIT)
            await asyncio.sleep(REFUSED_WAIT)
        except Exception as e:
            STATS["connected"] = False
            STATS["last_error"] = f"{type(e).__name__}: {str(e)[:100]}"
            log.warning("ships: stream dropped (%s); trying again in %d s", STATS["last_error"], backoff)
            await asyncio.sleep(backoff)
            backoff = min(300, backoff * 2)


def run_snapshot():
    now = time.time()
    body, count = build_snapshot(now)
    SNAPSHOT.update({"body": body, "count": count})
    forget_old(now)
    feed_status["ships"] = {"last_ok": datetime.now(timezone.utc) if STATS["messages"] else None, "error": None if STATS["connected"] else STATS["last_error"], "count": count}
    return count


async def snapshot_loop():
    n = 0
    while True:
        try:
            count = await asyncio.to_thread(run_snapshot)
            n += 1
            if n % 15 == 0:
                log.info("ships: %s, %d messages, %d ships on the map, %d with details", "connected" if STATS["connected"] else "NOT connected", STATS["messages"], count, len(STATIC))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ships: snapshot failed")
        await asyncio.sleep(SNAPSHOT_EVERY)


async def save_loop():
    n = 0
    while True:
        await asyncio.sleep(FLUSH_EVERY)
        try:
            await asyncio.to_thread(flush)
            n += 1
            if n % 60 == 0:
                await asyncio.to_thread(prune)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ships: saving failed")


async def ingest_loop():
    await asyncio.sleep(55)
    try:
        await asyncio.to_thread(init_schema)
        n = await asyncio.to_thread(load_static)
        log.info("ships: %d ships' details loaded from the last run", n)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("ships setup failed")
        return
    await asyncio.gather(stream_loop(), snapshot_loop(), save_loop())


# ---------- the API ----------
@router.get("/api/ships")
def ships(user=Depends(current_user)):
    return Response(content=SNAPSHOT["body"], media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/api/ships/status")
def ships_status(user=Depends(current_user)):
    """A plain readout of the connection, for checking that ships are flowing."""
    now = time.time()
    return {"connected": STATS["connected"], "messages": STATS["messages"], "positions": STATS["positions"], "statics": STATS["statics"],
            "dropped": STATS["dropped"], "last_message_age_s": int(now - STATS["last_message"]) if STATS["last_message"] else None,
            "last_error": STATS["last_error"], "ships_tracked": len(VESSELS), "ships_on_map": SNAPSHOT["count"], "details_known": len(STATIC),
            "trail_points_waiting": len(TRACKBUF), "key_present": bool(os.environ.get("AISSTREAM_API_KEY", "").strip())}


@router.get("/api/ship/{mmsi}")
def ship(mmsi: int = FPath(..., ge=200_000_000, le=799_999_999), user=Depends(current_user)):
    v = VESSELS.get(mmsi)
    if not v or "lat" not in v:
        raise HTTPException(404, "That ship is not being tracked right now")
    st = STATIC.get(mmsi) or {}
    now = datetime.now(timezone.utc)
    dest = resolve_destination(st.get("destination"), (v["lat"], v["lon"]))
    return {
        "mmsi": mmsi, "name": st.get("name", ""), "imo": st.get("imo"), "callsign": st.get("callsign", ""), "flag": flag_of(mmsi),
        "type": st.get("type", 0), "type_text": D.type_text(st.get("type", 0)), "category": D.category_of(st.get("type", 0)),
        "length": st.get("length", 0), "beam": st.get("beam", 0), "draught": st.get("draught"),
        "sog": v["sog"], "cog": v["cog"], "heading": v["hdg"], "nav": v["nav"], "nav_text": D.NAV_STATUS.get(v["nav"], "Not defined"),
        "lat": v["lat"], "lon": v["lon"], "age": int(time.time() - v["t"]),
        "destination": st.get("destination", ""), "port": dest, "eta": eta_iso(st.get("eta"), now), "trail": trail_of(mmsi),
    }
