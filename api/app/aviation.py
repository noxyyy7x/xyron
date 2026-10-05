import asyncio
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from .deps import current_user
from .events import feed_status

log = logging.getLogger("xyron.aviation")
router = APIRouter()

TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
STATES_URL = "https://opensky-network.org/api/states/all?extended=1"
POLL_SECONDS = 100  # a global snapshot costs 4 credits; 720 a day is about 2,900 of the 4,000 allowed

_token = {"value": None, "expires": 0.0}
_snapshot = {"body": b'{"time":0,"count":0,"flights":[]}'}


def _get_token():
    now = time.time()
    if _token["value"] and now < _token["expires"]:
        return _token["value"]
    cid = os.environ.get("OPENSKY_CLIENT_ID")
    secret = os.environ.get("OPENSKY_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("OpenSky credentials are not set")
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": cid, "client_secret": secret,
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=20) as r:
        j = json.load(r)
    _token["value"] = j["access_token"]
    _token["expires"] = now + int(j.get("expires_in", 1800)) - 60
    return _token["value"]


def _fetch_states():
    req = urllib.request.Request(STATES_URL, headers={
        "Authorization": "Bearer " + _get_token(),
        "User-Agent": "XYRON/1.0 (private dashboard)",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            remaining = r.headers.get("X-Rate-Limit-Remaining")
            return json.load(r), remaining
    except urllib.error.HTTPError as e:
        if e.code == 401:
            _token["value"] = None  # token expired, fetch a new one next time
        raise


def compact(data: dict):
    """Airborne aircraft only, as short arrays to keep the download small."""
    out = []
    for s in data.get("states") or []:
        if len(s) < 17:
            continue
        lon, lat = s[5], s[6]
        if lat is None or lon is None or s[8]:  # no position, or on the ground
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        cat = s[17] if len(s) > 17 and s[17] is not None else 0
        if cat in (16, 17, 18, 19, 20):  # surface vehicles and fixed obstacles
            continue
        alt = s[13] if s[13] is not None else s[7]
        out.append([
            s[0],                                   # 0 icao24
            (s[1] or "").strip(),                   # 1 callsign
            round(lat, 4), round(lon, 4),           # 2, 3
            round(alt) if alt is not None else 0,   # 4 altitude, metres
            round(s[9] or 0, 1),                    # 5 ground speed, m/s
            round(s[10] or 0, 1),                   # 6 track, degrees clockwise from north
            round(s[11] or 0, 1),                   # 7 vertical rate, m/s
            cat,                                    # 8 category
            s[2] or "",                             # 9 registered country
            s[3] or s[4] or data.get("time") or 0,  # 10 time of the position, unix seconds
            s[14] or "",                            # 11 squawk
        ])
    return out


def publish(unix_time, flights):
    _snapshot["body"] = json.dumps(
        {"time": unix_time, "count": len(flights), "flights": flights}, separators=(",", ":")
    ).encode()


async def ingest_loop():
    await asyncio.sleep(20)
    while True:
        wait = POLL_SECONDS
        try:
            data, remaining = await asyncio.to_thread(_fetch_states)
            flights = compact(data)
            publish(data.get("time"), flights)
            feed_status["aviation"] = {
                "last_ok": datetime.now(timezone.utc), "error": None, "count": len(flights),
            }
            log.info("aviation: %d aircraft airborne, credits left: %s", len(flights), remaining)
        except asyncio.CancelledError:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = max(wait, int(e.headers.get("X-Rate-Limit-Retry-After-Seconds") or 600))
            feed_status["aviation"] = {"last_ok": None, "error": f"HTTP {e.code}", "count": 0}
            log.warning("aviation feed error: HTTP %s, retrying in %s s", e.code, wait)
        except Exception as e:
            feed_status["aviation"] = {"last_ok": None, "error": type(e).__name__, "count": 0}
            log.exception("aviation feed failed")
        await asyncio.sleep(wait)


@router.get("/api/flights")
def flights(user=Depends(current_user)):
    return Response(content=_snapshot["body"], media_type="application/json")


# ---------- route and aircraft details for one selected plane (adsbdb.com, free, no key) ----------
_detail_cache = {}
_ICAO24_RE = re.compile(r"^[0-9a-fA-F]{6}$")
_CALLSIGN_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


def _adsbdb(path):
    req = urllib.request.Request(
        "https://api.adsbdb.com/v0/" + path, headers={"User-Agent": "XYRON/1.0 (private dashboard)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"response": "unknown"}
        raise


def _airport(a):
    if not isinstance(a, dict):
        return None
    lat, lon = a.get("latitude"), a.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {
        "name": a.get("name"), "city": a.get("municipality"), "country": a.get("country_name"),
        "iata": a.get("iata_code"), "icao": a.get("icao_code"), "lat": lat, "lon": lon,
    }


def clean_route(j):
    resp = (j or {}).get("response")
    fr = resp.get("flightroute") if isinstance(resp, dict) else None
    if not isinstance(fr, dict):
        return None
    origin, dest = _airport(fr.get("origin")), _airport(fr.get("destination"))
    if not origin or not dest:
        return None
    al = fr.get("airline") if isinstance(fr.get("airline"), dict) else None
    return {
        "callsign": fr.get("callsign"),
        "airline": {k: al.get(k) for k in ("name", "icao", "iata", "country")} if al else None,
        "origin": origin, "destination": dest, "via": _airport(fr.get("midpoint")),
    }


def clean_aircraft(j):
    resp = (j or {}).get("response")
    ac = resp.get("aircraft") if isinstance(resp, dict) else None
    if not isinstance(ac, dict):
        return None
    photo = ac.get("url_photo")
    return {
        "type": ac.get("type"), "icao_type": ac.get("icao_type"), "manufacturer": ac.get("manufacturer"),
        "registration": ac.get("registration"), "owner": ac.get("registered_owner"),
        "country": ac.get("registered_owner_country_name"),
        "photo": photo if isinstance(photo, str) and photo.startswith("https://") else None,
    }


@router.get("/api/flight/{icao24}")
def flight_detail(icao24: str, callsign: str = "", user=Depends(current_user)):
    if not _ICAO24_RE.match(icao24):
        raise HTTPException(400, "Invalid transponder code")
    callsign = callsign.strip().upper()
    if callsign and not _CALLSIGN_RE.match(callsign):
        raise HTTPException(400, "Invalid callsign")
    key = (icao24.lower(), callsign)
    now = time.time()
    cached = _detail_cache.get(key)
    if cached and now < cached[0]:
        return cached[1]
    result = {"route": None, "aircraft": None}
    ok = True
    if callsign:
        try:
            result["route"] = clean_route(_adsbdb("callsign/" + urllib.parse.quote(callsign)))
        except Exception as e:
            ok = False
            log.warning("route lookup failed: %s", type(e).__name__)
    try:
        result["aircraft"] = clean_aircraft(_adsbdb("aircraft/" + icao24.lower()))
    except Exception as e:
        ok = False
        log.warning("aircraft lookup failed: %s", type(e).__name__)
    ttl = (12 * 3600 if (result["route"] or result["aircraft"]) else 1800) if ok else 60
    if len(_detail_cache) > 5000:
        _detail_cache.clear()
    _detail_cache[key] = (now + ttl, result)
    return result
