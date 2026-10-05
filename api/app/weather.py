import asyncio
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

from .db import get_conn
from .events import UPSERT, feed_status

log = logging.getLogger("xyron.weather")

CITIES_FILE = Path(__file__).parent / "data" / "cities.json"
API = "https://api.open-meteo.com/v1/forecast"
CURRENT = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,"
    "weather_code,wind_speed_10m,wind_direction_10m"
)
BATCH = 100
POLL_SECONDS = 14400

# WMO weather interpretation codes used by Open-Meteo
WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Light freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Violent showers",
    85: "Light snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


def load_cities():
    with open(CITIES_FILE, encoding="utf-8") as f:
        return json.load(f)


def _fetch(cities):
    q = urllib.parse.urlencode({
        "latitude": ",".join(str(c["lat"]) for c in cities),
        "longitude": ",".join(str(c["lon"]) for c in cities),
        "current": CURRENT,
        "timeformat": "unixtime",
        "wind_speed_unit": "kmh",
    })
    req = urllib.request.Request(API + "?" + q, headers={"User-Agent": "XYRON/1.0 (private dashboard)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def weather_rows(cities, results):
    """Turn Open-Meteo answers into rows for the shared events table."""
    if isinstance(results, dict):  # a single location comes back as an object, not a list
        results = [results]
    rows = []
    for city, res in zip(cities, results):
        cur = (res or {}).get("current") or {}
        temp = cur.get("temperature_2m")
        when = cur.get("time")
        if temp is None or when is None:
            continue
        code = cur.get("weather_code")
        cond = WMO.get(code, "Unknown conditions")
        rows.append((
            "open-meteo", f"{city['name']}|{city['country']}", "weather",
            f"{city['name']}: {round(temp)}\u00b0C, {cond.lower()}",
            city["lat"], city["lon"], float(temp),
            datetime.fromtimestamp(when, tz=timezone.utc), None,
            "https://open-meteo.com/",
            Jsonb({
                "city": city["name"], "country": city["country"], "pop": city["pop"],
                "condition": cond, "code": code,
                "feels_like": cur.get("apparent_temperature"),
                "humidity": cur.get("relative_humidity_2m"),
                "wind_kmh": cur.get("wind_speed_10m"),
                "wind_dir": cur.get("wind_direction_10m"),
                "precip_mm": cur.get("precipitation"),
            }),
        ))
    return rows


def _store(rows):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT, rows)
    return len(rows)


async def ingest_loop():
    await asyncio.sleep(12)
    cities = load_cities()
    while True:
        try:
            total = 0
            for i in range(0, len(cities), BATCH):
                chunk = cities[i:i + BATCH]
                data = await asyncio.to_thread(_fetch, chunk)
                total += await asyncio.to_thread(_store, weather_rows(chunk, data))
                await asyncio.sleep(20)
            feed_status["weather"] = {"last_ok": datetime.now(timezone.utc), "error": None}
            log.info("weather: %d cities stored", total)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            feed_status["weather"] = {"last_ok": None, "error": type(e).__name__}
            log.exception("weather feed failed")
        await asyncio.sleep(POLL_SECONDS)
