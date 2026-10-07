import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from . import aviation, ships, ships_data as D
from .db import get_conn
from .deps import current_user

log = logging.getLogger("xyron.search")
router = APIRouter()

APP_DIR = Path(__file__).parent
PLACES_FILE = APP_DIR / "data" / "places.json"
COUNTRIES_FILE = APP_DIR / "static" / "globe" / "dots.json"
AIRLINES_FILE = APP_DIR / "static" / "globe" / "airlines.json"
PER_GROUP = 6


def fold(text):
    """Lower case, no accents, single spaces, so 'S\u00e3o  Paulo' matches 'sao paulo'."""
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def score(needle, hay):
    """0 means no match. Exact beats prefix beats word-prefix beats contains."""
    if not needle or not hay:
        return 0
    if hay == needle:
        return 100
    if hay.startswith(needle):
        return 80
    if (" " + needle) in (" " + hay):
        return 60
    return 40 if needle in hay else 0


def clip(x, n=80):
    return "" if x is None else str(x)[:n]


# ---------- places ----------
@lru_cache(maxsize=1)
def place_index():
    cities = json.loads(PLACES_FILE.read_text(encoding="utf-8")) if PLACES_FILE.exists() else []
    countries = json.loads(COUNTRIES_FILE.read_text(encoding="utf-8"))["countries"] if COUNTRIES_FILE.exists() else []
    return ([(fold(c["name"]), c) for c in countries], [(fold(c["name"]), c) for c in cities])


def search_places(q):
    countries, cities = place_index()
    out = []
    for key, c in countries:
        s = score(q, key)
        if s:
            out.append((s + 5, {"title": clip(c["name"]), "subtitle": "Country", "action": {"type": "fly", "lat": c["lat"], "lon": c["lon"], "zoom": 2.4}}))
    for key, c in cities:
        s = score(q, key)
        if s:
            out.append((s + min(c.get("pop", 0) / 1e7, 4), {"title": clip(c["name"]), "subtitle": clip(c.get("country")) + " \u00b7 City", "action": {"type": "fly", "lat": c["lat"], "lon": c["lon"], "zoom": 1.8}}))
    out.sort(key=lambda r: -r[0])
    return [r[1] for r in out[:PER_GROUP]]


# ---------- ships ----------
def search_ships(q, raw):
    digits = re.sub(r"\D", "", raw)
    out = []
    for mmsi, v in list(ships.VESSELS.items()):
        if "lat" not in v:
            continue
        st = ships.STATIC.get(mmsi) or {}
        s = score(q, fold(st.get("name", "")))
        if not s and digits and len(digits) >= 4:
            if str(mmsi).startswith(digits):
                s = 70
            elif st.get("imo") and str(st["imo"]).startswith(digits):
                s = 65
        if s:
            out.append((s, mmsi, v, st))
    out.sort(key=lambda r: -r[0])
    items = []
    for _s, mmsi, v, st in out[:PER_GROUP]:
        items.append({"title": clip(st.get("name") or f"MMSI {mmsi}"), "subtitle": " \u00b7 ".join(x for x in (D.CATEGORY_LABEL.get(D.category_of(st.get("type", 0)), ""), ships.flag_of(mmsi), f"MMSI {mmsi}") if x),
                      "action": {"type": "ship", "mmsi": mmsi, "lat": v["lat"], "lon": v["lon"]}})
    return items


# ---------- flights ----------
@lru_cache(maxsize=1)
def airlines():
    if not AIRLINES_FILE.exists():
        return []
    return [(a[0], a[1], a[2], a[3], fold(a[1])) for a in json.loads(AIRLINES_FILE.read_text(encoding="utf-8"))]


_flight_cache = {"body": None, "flights": []}


def current_flights():
    body = aviation._snapshot["body"]
    if body is not _flight_cache["body"]:
        try:
            _flight_cache["flights"] = json.loads(body).get("flights") or []
        except ValueError:
            _flight_cache["flights"] = []
        _flight_cache["body"] = body
    return _flight_cache["flights"]


def search_flights(q, raw):
    flights = current_flights()
    if not flights:
        return []
    up = raw.strip().upper()
    codes = {}
    if len(q) >= 3:
        for icao, name, iata, country, key in airlines():
            s = score(q, key)
            if s:
                codes[icao] = (s, name)
    m = re.fullmatch(r"([A-Z0-9]{2})\s?(\d{1,4}[A-Z]?)", up)  # a flight number such as EK203 is the callsign UAE203
    iata_call = None
    if m:
        for icao, name, iata, country, key in airlines():
            if iata == m.group(1):
                iata_call = icao + (m.group(2).lstrip("0") or m.group(2))
                break
    by_icao = {a[0]: a for a in airlines()}
    out = []
    for f in flights:
        call, hexid = (f[1] or "").upper(), (f[0] or "").upper()
        s = 0
        if call and call == up:
            s = 100
        elif iata_call and re.sub(r"^([A-Z]{3})0+(?=\d)", r"\1", call) == iata_call:
            s = 95
        elif call and len(up) >= 2 and call.startswith(up):
            s = 80
        elif len(up) >= 4 and hexid.startswith(up):
            s = 75
        elif call and len(up) >= 3 and up in call:
            s = 45
        elif codes and call[:3] in codes and re.match(r"[A-Z]{3}\d", call):
            s = 30 + codes[call[:3]][0] / 10
        if s:
            out.append((s, f))
    out.sort(key=lambda r: -r[0])
    items = []
    for _s, f in out[:PER_GROUP]:
        a = by_icao.get((f[1] or "")[:3]) if re.match(r"[A-Z]{3}\d", f[1] or "") else None
        fl = f"FL{round(f[4] * 3.28084 / 100):03d}" if f[4] else "low"
        items.append({"title": clip(f[1] or f[0].upper(), 12), "subtitle": " \u00b7 ".join(x for x in ((a[1] if a else ""), clip(f[9], 24), fl) if x),
                      "action": {"type": "flight", "icao24": f[0], "lat": f[2], "lon": f[3]}})
    return items


# ---------- football, markets, events and news (from the database) ----------
def like(raw):
    return "%" + re.sub(r"[%_\\]", lambda m: "\\" + m.group(0), raw.strip()) + "%"


def search_matches(raw):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT title, state, start_at, detail FROM matches WHERE sport = 'football' AND title ILIKE %s "
            "AND (state = 'in' OR start_at BETWEEN now() - interval '36 hours' AND now() + interval '60 hours') "
            "ORDER BY (state = 'in') DESC, start_at LIMIT %s", (like(raw), PER_GROUP)).fetchall()
    items = []
    for r in rows:
        d = r["detail"] or {}
        when = {"in": "LIVE " + clip(d.get("status"), 10), "post": "Finished"}.get(r["state"]) or r["start_at"].strftime("%a %H:%M UTC")
        items.append({"title": clip(r["title"], 70), "subtitle": " \u00b7 ".join(x for x in (clip(d.get("league"), 40), when) if x),
                      "action": {"type": "match", "id": clip(d.get("event_id"), 20)}})
    return [i for i in items if i["action"]["id"]]


def search_quotes(raw):
    up = raw.strip().upper()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol, kind, name, price, change_pct, currency FROM quotes WHERE price IS NOT NULL AND (symbol ILIKE %s OR name ILIKE %s) LIMIT 60",
            (like(raw), like(raw))).fetchall()
    low = raw.strip().lower()

    def rank(r):
        sym, name = r["symbol"].upper(), r["name"].lower()
        return (0 if sym == up else 1 if sym.startswith(up) else 2 if name.startswith(low) else 3, len(r["name"]))
    rows.sort(key=rank)
    items = []
    for r in rows[:PER_GROUP]:
        chg = f"{r['change_pct']:+.2f}%" if r["change_pct"] is not None else ""
        items.append({"title": clip(r["name"], 60), "subtitle": " \u00b7 ".join(x for x in (r["symbol"], r["kind"], chg) if x),
                      "action": {"type": "quote", "symbol": r["symbol"], "kind": r["kind"]}})
    return items


def search_events(raw):
    items = []
    try:
        with get_conn() as conn:
            for r in conn.execute("SELECT title, layer, lat, lon FROM events WHERE layer IN ('earthquakes', 'hazards') AND title ILIKE %s ORDER BY severity DESC LIMIT %s",
                                  (like(raw), PER_GROUP)).fetchall():
                items.append({"title": clip(r["title"], 80), "subtitle": "Earthquake" if r["layer"] == "earthquakes" else "Natural hazard",
                              "action": {"type": "fly", "lat": r["lat"], "lon": r["lon"], "zoom": 2.0}})
            for r in conn.execute("SELECT title, source, place, lat, lon FROM headlines WHERE title ILIKE %s AND lat IS NOT NULL AND published_at > now() - interval '48 hours' "
                                  "ORDER BY published_at DESC LIMIT %s", (like(raw), PER_GROUP)).fetchall():
                items.append({"title": clip(r["title"], 90), "subtitle": " \u00b7 ".join(x for x in (clip(r["source"], 24), clip(r["place"], 40)) if x),
                              "action": {"type": "fly", "lat": r["lat"], "lon": r["lon"], "zoom": 2.0}})
    except Exception as e:  # the news table may not exist yet
        log.warning("search: events failed: %s", type(e).__name__)
    return items[:PER_GROUP]


GROUPS = [("places", "Places"), ("ships", "Ships"), ("flights", "Flights"), ("football", "Football"), ("markets", "Markets"), ("events", "Events and news")]


@router.get("/api/search")
def search(q: str = Query(..., min_length=2, max_length=60), user=Depends(current_user)):
    raw = q.strip()
    needle = fold(raw)
    if len(needle) < 2:
        return {"q": raw, "groups": []}
    builders = {"places": lambda: search_places(needle), "ships": lambda: search_ships(needle, raw), "flights": lambda: search_flights(needle, raw),
                "football": lambda: search_matches(raw), "markets": lambda: search_quotes(raw), "events": lambda: search_events(raw)}
    groups = []
    for gid, label in GROUPS:
        try:
            items = builders[gid]()
        except Exception as e:  # one broken source must not break the whole search
            log.warning("search: %s failed: %s: %s", gid, type(e).__name__, str(e)[:80])
            items = []
        if items:
            groups.append({"id": gid, "label": label, "items": items})
    return {"q": raw, "groups": groups}
