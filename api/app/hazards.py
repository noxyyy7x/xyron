import asyncio
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from .db import get_conn
from .events import UPSERT, feed_status

log = logging.getLogger("xyron.hazards")

URL = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=500"
POLL_EVERY = 900          # NASA updates its list a few times an hour
SKIP = {"earthquakes"}    # the earthquake layer already has these, from the USGS
# how serious we treat each kind: used for dot size and for which ones pulse
CATEGORY = {
    "volcanoes": ("Volcano", 3), "severeStorms": ("Severe storm", 3), "wildfires": ("Wildfire", 2), "floods": ("Flood", 2),
    "landslides": ("Landslide", 2), "drought": ("Drought", 1), "dustHaze": ("Dust and haze", 1), "seaLakeIce": ("Sea and lake ice", 1),
    "snow": ("Snow", 1), "tempExtremes": ("Temperature extreme", 1), "waterColor": ("Water colour", 1), "manmade": ("Man-made event", 1),
}


def number(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf") else None


def valid(lat, lon):
    return number(lat) is not None and number(lon) is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def position_of(geometry):
    """The latest point of an event, as (lat, lon, date, magnitude, unit). Polygons use their middle."""
    for g in reversed(geometry if isinstance(geometry, list) else []):
        if not isinstance(g, dict):
            continue
        coords, kind = g.get("coordinates"), g.get("type")
        lat = lon = None
        if kind == "Point" and isinstance(coords, list) and len(coords) >= 2:
            lon, lat = coords[0], coords[1]
        elif kind == "Polygon" and isinstance(coords, list) and coords and isinstance(coords[0], list):
            ring = [p for p in coords[0] if isinstance(p, list) and len(p) >= 2 and valid(p[1], p[0])]
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]  # a polygon repeats its first corner at the end; counting it twice would pull the middle off-centre
            if ring:
                lon, lat = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
        if valid(lat, lon):
            return lat, lon, g.get("date"), number(g.get("magnitudeValue")), g.get("magnitudeUnit")
    return None


def normalise(event, now):
    """One EONET event -> one row for the events table, or None."""
    if not isinstance(event, dict) or not event.get("id"):
        return None
    cats = [c for c in event.get("categories") or [] if isinstance(c, dict) and c.get("id")]
    cat = cats[0]["id"] if cats else "other"
    if cat in SKIP:
        return None
    spot = position_of(event.get("geometry"))
    if not spot:
        return None
    lat, lon, date, mag, unit = spot
    label, severity = CATEGORY.get(cat, ((cats[0].get("title") if cats else None) or "Natural event", 1))
    sources = [{"id": str(s.get("id") or "")[:30], "url": s["url"]} for s in event.get("sources") or []
               if isinstance(s, dict) and isinstance(s.get("url"), str) and s["url"].startswith("https://")][:5]
    try:
        when = datetime.fromisoformat(str(date).replace("Z", "+00:00")) if date else None
    except ValueError:
        when = None
    detail = {"category": cat, "category_label": label, "status": "open", "date": when.isoformat() if when else None,
              "magnitude": mag, "unit": unit if mag is not None else None, "description": str(event.get("description") or "")[:300],
              "sources": sources, "points": len(event.get("geometry") or []), "eonet_id": str(event["id"])}
    return ("eonet", f"hazard|{event['id']}", "hazards", str(event.get("title") or label)[:160], lat, lon, float(severity), now, when, None, Jsonb(detail))


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "XYRON/1.0 (private dashboard)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def refresh(data=None):
    """Read the open events and replace the layer with them. Returns how many are on the map."""
    data = data if data is not None else fetch()
    events = data.get("events") if isinstance(data, dict) else None
    if not isinstance(events, list):
        raise ValueError("unexpected answer from EONET")
    now = datetime.now(timezone.utc)
    rows = [r for r in (normalise(e, now) for e in events) if r]
    with get_conn() as conn:
        with conn.cursor() as cur:
            if rows:
                cur.executemany(UPSERT, rows)
        if rows or not events:
            conn.execute("DELETE FROM events WHERE source = 'eonet' AND fetched_at < %s", (now,))  # events NASA has closed
    feed_status["hazards"] = {"last_ok": now, "error": None, "count": len(rows)}
    return len(rows)


async def ingest_loop():
    await asyncio.sleep(70)
    fails = 0
    while True:
        try:
            n = await asyncio.to_thread(refresh)
            log.info("hazards: %d open natural events on the map", n)
            fails = 0
            await asyncio.sleep(POLL_EVERY)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            fails += 1
            msg = f"{type(e).__name__}: {str(e)[:100]}"
            log.warning("hazards feed failed (%s)", msg)
            st = feed_status.get("hazards") or {}
            feed_status["hazards"] = {"last_ok": st.get("last_ok"), "error": msg, "count": st.get("count")}
            await asyncio.sleep(min(3600, 120 * 2 ** min(fails, 5)))
