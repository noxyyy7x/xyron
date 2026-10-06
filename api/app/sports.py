import asyncio
import difflib
import json
import logging
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
CORE = "https://sports.core.api.espn.com/v2/sports/"
USA = "United States of America"

# ESPN has no official API, so any address can change or stop working. Every address is polled on its own
# schedule: often while games are on, rarely when nothing is happening, and a broken one backs off.
FOOTBALL_LEAGUES = [
    "eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "uefa.champions", "uefa.europa", "uefa.europa.conf", "uefa.nations",
    "eng.2", "eng.fa", "eng.league_cup", "esp.copa_del_rey", "ned.1", "por.1", "sco.1", "tur.1", "bel.1",
    "bra.1", "arg.1", "usa.1", "usa.nwsl", "mex.1", "sau.1", "jpn.1", "aus.1", "fifa.world", "fifa.friendly",
    "conmebol.libertadores", "conmebol.sudamericana", "concacaf.champions", "concacaf.leagues.cup",
]
# (sport id, label, map layer, ESPN address, country to assume when a venue has none)
FIXED = [
    ("basketball", "Basketball", "sports", "basketball/nba", USA),
    ("basketball", "Basketball", "sports", "basketball/wnba", USA),
    ("basketball", "Basketball", "sports", "basketball/mens-college-basketball", USA),
    ("american-football", "American football", "sports", "football/nfl", USA),
    ("american-football", "American football", "sports", "football/college-football", USA),
    ("baseball", "Baseball", "sports", "baseball/mlb", USA),
    ("hockey", "Hockey", "sports", "hockey/nhl", USA),
    ("f1", "Formula 1", "sports", "racing/f1", None),
    ("mma", "MMA", "sports", "mma/ufc", USA),
]
# sports whose competitions are looked up once a day: (ESPN sport, our sport id, label)
DISCOVER = [
    ("rugby", "rugby", "Rugby union"), ("rugby-league", "rugby-league", "Rugby league"), ("volleyball", "volleyball", "Volleyball"),
    ("tennis", "tennis", "Tennis"), ("golf", "golf", "Golf"), ("lacrosse", "lacrosse", "Lacrosse"),
    ("australian-football", "australian-football", "Australian football"), ("field-hockey", "field-hockey", "Field hockey"),
    ("water-polo", "water-polo", "Water polo"),
]
LIVE_EVERY = 30        # seconds between checks while a game of that feed is on
SOON_EVERY = 180       # when a game is about to start or has just ended
IDLE_EVERY = 1800      # otherwise
OFFSEASON_EVERY = 10800  # a feed that has been empty a few times in a row
DEAD_EVERY = 86400     # an address that answers "not found"
REQUEST_GAP = 1.5      # seconds between any two requests to ESPN
PER_PASS = 12          # feeds polled before the map is refreshed
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


@dataclass
class Feed:
    path: str                 # ESPN address, e.g. "basketball/nba" or "soccer/eng.1"
    sport: str                # our sport id
    label: str
    layer: str                # "football" or "sports"
    default_country: str = None
    dates: str = None         # None, "yesterday" or "tomorrow" (all-football feed only)
    due: float = 0.0
    fails: int = 0
    empty: int = 0

    @property
    def name(self):
        return self.path + (f"[{self.dates}]" if self.dates else "")


def build_feeds():
    feeds = [Feed("soccer/all", "football", "Football", "football"),
             Feed("soccer/all", "football", "Football", "football", dates="yesterday"),
             Feed("soccer/all", "football", "Football", "football", dates="tomorrow")]
    feeds += [Feed("soccer/" + slug, "football", "Football", "football") for slug in FOOTBALL_LEAGUES]
    feeds += [Feed(path, sid, label, layer, dc) for sid, label, layer, path, dc in FIXED]
    return feeds


# ---------- reading ESPN ----------
def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "XYRON/1.0 (private dashboard)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def scoreboard_url(feed, now=None):
    url = ESPN + feed.path + "/scoreboard"
    if feed.dates:
        day = (now or datetime.now(timezone.utc)) + timedelta(days={"yesterday": -1, "tomorrow": 1}[feed.dates])
        url += "?dates=" + day.strftime("%Y%m%d")
    return url


def discover(sport):
    """The competition addresses ESPN lists for a sport, e.g. ['atp', 'wta']."""
    data = _get_json(CORE + sport + "/leagues?limit=100")
    out = []
    for item in data.get("items") or []:
        m = re.search(r"/leagues/([^/?]+)", item.get("$ref", ""))
        if m:
            out.append(m.group(1))
    return out


def _when(text):
    try:
        d = datetime.fromisoformat((text or "").replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _side(c):
    team = c.get("team") or {}
    color = team.get("color") or ""
    return {"name": team.get("displayName") or team.get("name") or "?", "abbr": team.get("abbreviation"),
            "score": c.get("score"), "logo": team.get("logo"),
            "color": color if re.fullmatch(r"[0-9a-fA-F]{6}", color) else None}


def league_of(feed, data, ev, names):
    """Which competition an event belongs to. The all-football feed names none, so look the id up."""
    m = re.search(r"~l:(\d+)", ev.get("uid") or "")
    lid = m.group(1) if m else ""
    if feed.path.endswith("/all"):
        info = names.get(lid) or {}
        return {"id": lid, "name": info.get("name", ""), "slug": info.get("slug", "")}
    top = (data.get("leagues") or [{}])[0] or {}
    return {"id": lid or str(top.get("id") or ""), "name": top.get("name") or "", "slug": feed.path.split("/", 1)[1]}


def normalise(feed, lg, ev, locator, now):
    """One ESPN event -> one row for the matches table, or None if it cannot be understood."""
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
    detail = {"sport": feed.sport, "sport_label": feed.label, "league": lg["name"], "league_slug": lg["slug"],
              "league_id": lg["id"], "event_id": str(ev["id"]), "state": state,
              "status": st.get("shortDetail") or status.get("displayClock") or "", "start": start.isoformat()}
    if len(teams) >= 2:
        home = next((c for c in teams if c.get("homeAway") == "home"), teams[0])
        away = next((c for c in teams if c is not home), teams[1])
        h, a = _side(home), _side(away)
        h["form"], a["form"] = home.get("form"), away.get("form")
        detail["home"], detail["away"] = h, a
        title = f"{h['name']} vs {a['name']}" if state == "pre" else f"{h['name']} {h['score']}\u2013{a['score']} {a['name']}"
    else:
        names = [((c.get("athlete") or {}).get("displayName"), c.get("score")) for c in comps]
        detail["competitors"] = [{"name": n, "score": s} for n, s in names if n][:10]
        title = ev.get("name") or ev.get("shortName") or feed.label
    venue = comp.get("venue") or ev.get("venue") or {}
    addr = venue.get("address") or {}
    detail["venue"], detail["city"], detail["country"] = venue.get("fullName"), addr.get("city"), addr.get("country")
    spot = locator.locate(addr.get("city"), addr.get("country"), feed.default_country)
    link = next((l.get("href") for l in ev.get("links") or [] if str(l.get("href", "")).startswith("https://www.espn.com/")), None)
    key = f"football|{ev['id']}" if feed.sport == "football" else f"{feed.path}|{ev['id']}"
    return (key, feed.sport, feed.layer, title[:200], state, start,
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
CREATE TABLE IF NOT EXISTS football_leagues (
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL,
  name TEXT NOT NULL
);
"""
# a feed that cannot name the competition (the all-football feed) must not wipe a name another feed already gave
MATCH_UPSERT = """
INSERT INTO matches (key, sport, layer, title, state, start_at, place, lat, lon, url, detail)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (key) DO UPDATE SET title = EXCLUDED.title, state = EXCLUDED.state, start_at = EXCLUDED.start_at,
  place = EXCLUDED.place, lat = EXCLUDED.lat, lon = EXCLUDED.lon, url = COALESCE(EXCLUDED.url, matches.url),
  detail = CASE WHEN EXCLUDED.detail->>'league' = '' AND COALESCE(matches.detail->>'league', '') <> ''
                THEN EXCLUDED.detail || jsonb_build_object('league', matches.detail->'league',
                     'league_slug', matches.detail->'league_slug', 'league_id', matches.detail->'league_id')
                ELSE EXCLUDED.detail END,
  updated_at = now()
"""
LEAGUE_UPSERT = "INSERT INTO football_leagues (id, slug, name) VALUES (%s,%s,%s) ON CONFLICT (id) DO UPDATE SET slug = EXCLUDED.slug, name = EXCLUDED.name"


def init_schema():
    with get_conn() as conn:
        conn.execute(SCHEMA)


def load_names():
    with get_conn() as conn:
        return {r["id"]: {"slug": r["slug"], "name": r["name"]} for r in conn.execute("SELECT id, slug, name FROM football_leagues").fetchall()}


def next_interval(rows, now):
    """How soon to ask again: often while a game is on, rarely when nothing is happening."""
    if any(r[4] == "in" for r in rows):
        return LIVE_EVERY
    for r in rows:
        until = (r[5] - now).total_seconds()
        if (r[4] == "pre" and 0 <= until <= 5400) or (r[4] == "post" and -4 * 3600 < until <= 0):
            return SOON_EVERY
    return IDLE_EVERY


def poll_feed(feed, locator, names):
    """Fetch one scoreboard, store its games, and return (rows, seconds until the next look)."""
    now = datetime.now(timezone.utc)
    try:
        data = _get_json(scoreboard_url(feed, now))
    except urllib.error.HTTPError as e:
        feed.fails += 1
        log.warning("sports feed %s: HTTP %s", feed.name, e.code)
        return [], (DEAD_EVERY if e.code == 404 else min(7200, 120 * 2 ** feed.fails))
    except Exception as e:  # one broken address must not stop the others
        feed.fails += 1
        log.warning("sports feed %s failed: %s: %s", feed.name, type(e).__name__, str(e)[:100])
        return [], min(7200, 120 * 2 ** feed.fails)
    feed.fails = 0
    rows, learned = [], {}
    for ev in data.get("events") or []:
        lg = league_of(feed, data, ev, names)
        if feed.sport == "football" and not feed.path.endswith("/all") and lg["id"] and lg["name"]:
            learned[lg["id"]] = {"slug": lg["slug"], "name": lg["name"]}
        row = normalise(feed, lg, ev, locator, now)
        if row:
            rows.append(row)
    if rows or learned:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if rows:
                    cur.executemany(MATCH_UPSERT, rows)
                for lid, info in learned.items():
                    cur.execute(LEAGUE_UPSERT, (lid, info["slug"], info["name"]))
        names.update(learned)
    feed.empty = 0 if rows else feed.empty + 1
    interval = next_interval(rows, now) if rows else (OFFSEASON_EVERY if feed.empty >= 3 else IDLE_EVERY)
    return rows, interval


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


def add_discovered(feeds, sport, sid, label):
    have = {f.path for f in feeds}
    added = 0
    for slug in discover(sport):
        path = f"{sport}/{slug}"
        if path not in have:
            feeds.append(Feed(path, sid, label, "sports"))
            added += 1
    return added


async def ingest_loop():
    await asyncio.sleep(40)
    try:
        await asyncio.to_thread(init_schema)
        locator = await asyncio.to_thread(load_locator)
        names = await asyncio.to_thread(load_names)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("sports setup failed")
        return
    feeds = build_feeds()
    next_discovery = 0.0
    while True:
        if time.monotonic() >= next_discovery:
            for sport, sid, label in DISCOVER:
                try:
                    n = await asyncio.to_thread(add_discovered, feeds, sport, sid, label)
                    log.info("sports: %s has %d competitions in ESPN's list", sport, n)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("sports: could not list %s competitions: %s", sport, type(e).__name__)
                await asyncio.sleep(REQUEST_GAP)
            next_discovery = time.monotonic() + 86400
        due = sorted((f for f in feeds if f.due <= time.monotonic()), key=lambda f: f.due)[:PER_PASS]
        if not due:
            await asyncio.sleep(5)
            continue
        games = live = 0
        for feed in due:
            try:
                rows, interval = await asyncio.to_thread(poll_feed, feed, locator, names)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sports feed %s crashed", feed.name)
                rows, interval = [], 600
            feed.due = time.monotonic() + interval * random.uniform(0.9, 1.1)
            games += len(rows)
            live += sum(1 for r in rows if r[4] == "in")
            await asyncio.sleep(REQUEST_GAP)
        try:
            await asyncio.to_thread(rebuild_layers)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("sports map update failed")
        log.info("sports: polled %d feeds, %d games seen, %d live", len(due), games, live)


@router.get("/api/matches")
def list_matches(
    sport: str = Query("", max_length=40),
    state: str = Query("", pattern="^(|pre|in|post)$"),
    q: str = Query("", max_length=60),
    hours: int = Query(36, ge=1, le=72),
    limit: int = Query(200, ge=1, le=500),
    user=Depends(current_user),
):
    sql = ["SELECT key, sport, title, state, start_at, place, lat, lon, url, detail FROM matches "
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
