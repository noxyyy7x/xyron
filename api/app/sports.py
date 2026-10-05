import asyncio
import difflib
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from psycopg.types.json import Jsonb

from .db import get_conn
from .deps import current_user
from .events import UPSERT, feed_status

log = logging.getLogger("xyron.sports")
router = APIRouter()

APP_DIR = Path(__file__).parent
PLACES_FILE = APP_DIR / "data" / "places.json"
COUNTRIES_FILE = APP_DIR / "static" / "globe" / "dots.json"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/"
USA = "United States of America"

# (id, label, map layer, ESPN paths, country to assume when a venue has none)
# ESPN has no official API, so any path can change or stop working; a failing path is logged and skipped.
SOURCES = [
    ("football", "Football", "football", ["soccer/all"], None),
    ("basketball", "Basketball", "sports", ["basketball/nba", "basketball/wnba", "basketball/mens-college-basketball"], USA),
    ("american-football", "American football", "sports", ["football/nfl", "football/college-football"], USA),
    ("baseball", "Baseball", "sports", ["baseball/mlb"], USA),
    ("hockey", "Hockey", "sports", ["hockey/nhl"], USA),
    ("f1", "Formula 1", "sports", ["racing/f1"], None),
    ("mma", "MMA", "sports", ["mma/ufc"], USA),
]
LIVE_EVERY = 30        # seconds between checks while a game of that sport is on
SOON_EVERY = 180       # when a game is about to start or has just ended
IDLE_EVERY = 1800      # otherwise
REQUEST_GAP = 1.5      # seconds between any two requests to ESPN
KEEP_DAYS = 3

COUNTRY_ALIASES = {
    "usa": USA, "us": USA, "united states": USA, "england": "United Kingdom", "scotland": "United Kingdom",
    "wales": "United Kingdom", "northern ireland": "United Kingdom", "great britain": "United Kingdom",
    "uae": "United Arab Emirates", "korea republic": "South Korea", "czech republic": "Czechia",
    "ivory coast": "C\u00f4te d'Ivoire", "turkiye": "Turkey",
}


def _norm(name):
    """Lower-case and spell out the abbreviations Natural Earth uses, so both spellings compare equal."""
    s = " " + name.strip().lower().replace("&", "and") + " "
    for a, b in ((" dem. rep. ", " democratic republic "), (" rep. ", " republic "), (" herz. ", " herzegovina "),
                 (" eq. ", " equatorial "), (" is. ", " islands "), (" st. ", " saint "), (" s. ", " south "),
                 (" of the ", " "), (" of ", " "), (" the ", " ")):
        s = s.replace(a, b)
    return " ".join(s.split())


class VenueLocator:
    """Venue city -> map position, using the city list, then the country's centre."""

    def __init__(self, places, countries):
        self.by_city = {}
        for p in places:
            self.by_city.setdefault(p["name"], []).append(p)
        for lst in self.by_city.values():
            lst.sort(key=lambda p: -p["pop"])
        self.countries = {c["name"]: c for c in countries}
        self._keys = {_norm(n): n for n in self.countries}

    def country(self, name):
        if not name:
            return None
        key = _norm(name)
        alias = COUNTRY_ALIASES.get(name.strip().lower())
        if alias:
            key = _norm(alias)
        if key in self._keys:
            return self._keys[key]
        near = difflib.get_close_matches(key, list(self._keys), n=1, cutoff=0.85)
        return self._keys[near[0]] if near else None

    def locate(self, city, country, default_country=None):
        want = self.country(country) or self.country(default_country)
        options = self.by_city.get((city or "").strip(), [])
        if want:
            for p in options:
                if p["country"] == want:
                    return f"{p['name']}, {p['country']}", p["lat"], p["lon"]
            c = self.countries[want]
            return want, c["lat"], c["lon"]
        if options:
            p = options[0]
            return f"{p['name']}, {p['country']}", p["lat"], p["lon"]
        return None


def load_locator():
    places = json.loads(PLACES_FILE.read_text(encoding="utf-8"))
    countries = json.loads(COUNTRIES_FILE.read_text(encoding="utf-8"))["countries"]
    return VenueLocator(places, countries)


# ---------- reading ESPN ----------
def _fetch(path):
    req = urllib.request.Request(ESPN + path + "/scoreboard", headers={"User-Agent": "XYRON/1.0 (private dashboard)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def _when(text):
    try:
        d = datetime.fromisoformat((text or "").replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _side(c):
    team = c.get("team") or {}
    return {"name": team.get("displayName") or team.get("name") or "?", "abbr": team.get("abbreviation"),
            "score": c.get("score"), "logo": team.get("logo")}


def normalise(src, path, league, ev, locator, now):
    """One ESPN event -> one row for the matches table, or None if it cannot be understood."""
    sid, label, layer, _paths, default_country = src
    if not ev.get("id"):
        return None
    start = _when(ev.get("date"))
    if not start:
        return None
    status = ev.get("status") or {}
    st = status.get("type") or {}
    state = st.get("state") if st.get("state") in ("pre", "in", "post") else "pre"
    comp = (ev.get("competitions") or [{}])[0]
    comps = comp.get("competitors") or []
    teams = [c for c in comps if c.get("team")]
    detail = {"sport": sid, "sport_label": label, "league": league or "", "state": state,
              "status": st.get("shortDetail") or status.get("displayClock") or "", "start": start.isoformat()}
    if len(teams) >= 2:
        home = next((c for c in teams if c.get("homeAway") == "home"), teams[0])
        away = next((c for c in teams if c is not home), teams[1])
        h, a = _side(home), _side(away)
        detail["home"], detail["away"] = h, a
        title = f"{h['name']} vs {a['name']}" if state == "pre" else f"{h['name']} {h['score']}\u2013{a['score']} {a['name']}"
    else:
        names = [((c.get("athlete") or {}).get("displayName"), c.get("score")) for c in comps]
        detail["competitors"] = [{"name": n, "score": s} for n, s in names if n][:10]
        title = ev.get("name") or ev.get("shortName") or label
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    detail["venue"], detail["city"], detail["country"] = venue.get("fullName"), addr.get("city"), addr.get("country")
    spot = locator.locate(addr.get("city"), addr.get("country"), default_country)
    link = next((l.get("href") for l in ev.get("links") or [] if str(l.get("href", "")).startswith("https://www.espn.com/")), None)
    return (f"{path}|{ev['id']}", sid, layer, title[:200], state, start,
            spot[0] if spot else None, spot[1] if spot else None, spot[2] if spot else None, link, Jsonb(detail))


SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
  key TEXT PRIMARY KEY,
  sport TEXT NOT NULL,
  layer TEXT NOT NULL,
  title TEXT NOT NULL,
  state TEXT NOT NULL,
  start_at TIMESTAMPTZ NOT NULL,
  place TEXT,
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  url TEXT,
  detail JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS matches_start_idx ON matches (start_at DESC);
"""
MATCH_UPSERT = """
INSERT INTO matches (key, sport, layer, title, state, start_at, place, lat, lon, url, detail)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (key) DO UPDATE SET title = EXCLUDED.title, state = EXCLUDED.state, start_at = EXCLUDED.start_at,
  place = EXCLUDED.place, lat = EXCLUDED.lat, lon = EXCLUDED.lon, url = EXCLUDED.url,
  detail = EXCLUDED.detail, updated_at = now()
"""


def init_schema():
    with get_conn() as conn:
        conn.execute(SCHEMA)


def next_interval(rows, now):
    """How soon to ask again: often while a game is on, rarely when nothing is happening."""
    if any(r[4] == "in" for r in rows):
        return LIVE_EVERY
    for r in rows:
        until = (r[5] - now).total_seconds()
        if (r[4] == "pre" and 0 <= until <= 5400) or (r[4] == "post" and -4 * 3600 < until <= 0):
            return SOON_EVERY
    return IDLE_EVERY


def poll_source(src, locator):
    now = datetime.now(timezone.utc)
    rows = []
    for i, path in enumerate(src[3]):
        if i:
            time.sleep(REQUEST_GAP)
        try:
            data = _fetch(path)
        except Exception as e:  # one broken address must not stop the others
            log.warning("sports feed failed (%s): %s: %s", path, type(e).__name__, str(e)[:100])
            continue
        league = ((data.get("leagues") or [{}])[0]).get("name") or ""
        for ev in data.get("events") or []:
            row = normalise(src, path, league, ev, locator, now)
            if row:
                rows.append(row)
    if rows:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(MATCH_UPSERT, rows)
    return rows, next_interval(rows, now) if rows else IDLE_EVERY


def rebuild_layers():
    """Matches near now that have a map position become events; the rest stay in the hub list only."""
    started = datetime.now(timezone.utc)
    with get_conn() as conn:
        found = conn.execute(
            "SELECT * FROM matches WHERE lat IS NOT NULL AND (state = 'in' OR "
            "start_at BETWEEN now() - interval '24 hours' AND now() + interval '36 hours')"
        ).fetchall()
        rows = []
        for m in found:
            sev = {"in": 2.0, "pre": 1.0}.get(m["state"], 0.0)
            when = started if m["state"] == "in" else m["start_at"]
            rows.append(("espn", f"match|{m['key']}", m["layer"], m["title"], m["lat"], m["lon"], sev,
                         when, None, m["url"], Jsonb(m["detail"])))
        with conn.cursor() as cur:
            if rows:
                cur.executemany(UPSERT, rows)
        conn.execute("DELETE FROM events WHERE source = 'espn' AND fetched_at < %s", (started,))
        conn.execute("DELETE FROM matches WHERE start_at < now() - make_interval(days => %s)", (KEEP_DAYS,))
    for layer in {"football", "sports"}:
        feed_status[layer] = {"last_ok": datetime.now(timezone.utc), "error": None}
    return len(rows)


async def ingest_loop():
    await asyncio.sleep(40)
    try:
        await asyncio.to_thread(init_schema)
        locator = await asyncio.to_thread(load_locator)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("sports setup failed")
        return
    due = {s[0]: 0.0 for s in SOURCES}
    while True:
        did = False
        for src in SOURCES:
            if due[src[0]] > time.monotonic():
                continue
            try:
                rows, interval = await asyncio.to_thread(poll_source, src, locator)
                log.info("sports %s: %d games, next check in %d s", src[0], len(rows), interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sports %s failed", src[0])
                interval = 300
            due[src[0]] = time.monotonic() + interval
            did = True
            await asyncio.sleep(REQUEST_GAP)
        if did:
            try:
                await asyncio.to_thread(rebuild_layers)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sports map update failed")
        await asyncio.sleep(5)


@router.get("/api/matches")
def list_matches(
    sport: str = Query("", max_length=40),
    state: str = Query("", pattern="^(|pre|in|post)$"),
    q: str = Query("", max_length=60),
    hours: int = Query(36, ge=1, le=72),
    limit: int = Query(200, ge=1, le=500),
    user=Depends(current_user),
):
    sql = ["SELECT key, sport, title, state, start_at, place, url, detail FROM matches "
           "WHERE (state = 'in' OR start_at BETWEEN now() - make_interval(hours => %s) AND now() + make_interval(hours => %s))"]
    args = [hours, hours]
    if sport:
        sql.append("AND sport = %s"); args.append(sport)
    if state:
        sql.append("AND state = %s"); args.append(state)
    if q:
        sql.append("AND title ILIKE %s"); args.append(f"%{q}%")
    sql.append("ORDER BY (state = 'in') DESC, start_at ASC LIMIT %s"); args.append(limit)
    with get_conn() as conn:
        return conn.execute(" ".join(sql), args).fetchall()
