import asyncio
import json
import logging
import urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from psycopg.types.json import Jsonb

from .db import get_conn
from .deps import current_user

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("xyron.events")
router = APIRouter()

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
POLL_SECONDS = 300
KEEP_DAYS = 30

# every feed writes into this one table, whatever it is about
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  layer TEXT NOT NULL,
  title TEXT NOT NULL,
  lat DOUBLE PRECISION NOT NULL,
  lon DOUBLE PRECISION NOT NULL,
  severity REAL,
  occurred_at TIMESTAMPTZ NOT NULL,
  source_updated_at TIMESTAMPTZ,
  url TEXT,
  detail JSONB NOT NULL DEFAULT '{}',
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS events_layer_time_idx ON events (layer, occurred_at DESC);
"""

# live=False layers show as "coming soon" toggles until their feeds exist
LAYERS = [
    {"id": "earthquakes", "label": "Earthquakes", "live": True},
    {"id": "weather", "label": "Weather", "live": True},
    {"id": "aviation", "label": "Aviation", "live": True},
    {"id": "news", "label": "News", "live": False},
    {"id": "politics", "label": "Politics", "live": False},
    {"id": "sports", "label": "Sports", "live": False},
    {"id": "football", "label": "Football", "live": False},
]
LIVE_IDS = {layer["id"] for layer in LAYERS if layer["live"]}
feed_status = {"earthquakes": {"last_ok": None, "error": None}}

UPSERT = """
INSERT INTO events (source, external_id, layer, title, lat, lon, severity,
                    occurred_at, source_updated_at, url, detail)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (source, external_id) DO UPDATE SET
  title = EXCLUDED.title, lat = EXCLUDED.lat, lon = EXCLUDED.lon,
  severity = EXCLUDED.severity, source_updated_at = EXCLUDED.source_updated_at,
  url = EXCLUDED.url, detail = EXCLUDED.detail, fetched_at = now()
"""


def init_schema():
    with get_conn() as conn:
        conn.execute(SCHEMA)


def _ts(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "XYRON/1.0 (private dashboard)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def quake_rows(data: dict):
    rows = []
    for f in data.get("features", []):
        p = f.get("properties") or {}
        c = (f.get("geometry") or {}).get("coordinates") or []
        if len(c) < 2 or not f.get("id"):
            continue
        if p.get("mag") is None or p.get("time") is None:
            continue
        if p.get("type") not in (None, "earthquake"):
            continue
        lon, lat, mag = float(c[0]), float(c[1]), float(p["mag"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        place = p.get("place") or "Unknown location"
        rows.append((
            "usgs", str(f["id"]), "earthquakes",
            p.get("title") or f"M {mag:.1f} - {place}",
            lat, lon, mag, _ts(p["time"]),
            _ts(p["updated"]) if p.get("updated") else None,
            p.get("url"),
            Jsonb({
                "place": place,
                "depth_km": float(c[2]) if len(c) > 2 and c[2] is not None else None,
                "tsunami": p.get("tsunami"),
                "status": p.get("status"),
            }),
        ))
    return rows


def _store(rows):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT, rows)
        conn.execute("DELETE FROM events WHERE occurred_at < now() - make_interval(days => %s)", (KEEP_DAYS,))
    return len(rows)


async def ingest_loop():
    await asyncio.sleep(5)
    while True:
        try:
            data = await asyncio.to_thread(_fetch, USGS_URL)
            n = await asyncio.to_thread(_store, quake_rows(data))
            feed_status["earthquakes"] = {"last_ok": datetime.now(timezone.utc), "error": None}
            log.info("earthquakes: %d events stored", n)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            feed_status["earthquakes"]["error"] = type(e).__name__
            log.exception("earthquake feed failed")
        await asyncio.sleep(POLL_SECONDS)


@router.get("/api/layers")
def layers(user=Depends(current_user)):
    with get_conn() as conn:
        counts = {
            r["layer"]: r["n"]
            for r in conn.execute(
                "SELECT layer, count(*) AS n FROM events "
                "WHERE occurred_at > now() - interval '24 hours' GROUP BY layer"
            ).fetchall()
        }
    out = []
    for layer in LAYERS:
        item = dict(layer)
        item["count"] = counts.get(layer["id"], 0)
        st = feed_status.get(layer["id"]) or {}
        item["updated"] = st["last_ok"].isoformat() if st.get("last_ok") else None
        if st.get("count") is not None:
            item["count"] = st["count"]
        out.append(item)
    return out


@router.get("/api/events")
def list_events(
    layers: str = Query("earthquakes", max_length=200),
    hours: int = Query(24, ge=1, le=168),
    user=Depends(current_user),
):
    wanted = [x for x in layers.split(",") if x in LIVE_IDS]
    if not wanted:
        return []
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, layer, title, lat, lon, severity, occurred_at, url, detail "
            "FROM events WHERE layer = ANY(%s) AND occurred_at > now() - make_interval(hours => %s) "
            "ORDER BY occurred_at DESC LIMIT 5000",
            (wanted, hours),
        ).fetchall()
