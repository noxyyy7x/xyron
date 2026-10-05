import asyncio
import html
import json
import logging
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query
from psycopg.types.json import Jsonb

from .db import get_conn
from .deps import current_user
from .events import UPSERT, feed_status

log = logging.getLogger("xyron.news")
router = APIRouter()

APP_DIR = Path(__file__).parent
CITIES_FILE = APP_DIR / "data" / "cities.json"
COUNTRIES_FILE = APP_DIR / "static" / "globe" / "dots.json"

# (name shown to people, feed address, treat every story as politics?)
FEEDS = [
    ("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml", False),
    ("BBC News", "https://feeds.bbci.co.uk/news/world/africa/rss.xml", False),
    ("BBC News", "https://feeds.bbci.co.uk/news/world/asia/rss.xml", False),
    ("BBC News", "https://feeds.bbci.co.uk/news/world/europe/rss.xml", False),
    ("BBC News", "https://feeds.bbci.co.uk/news/world/latin_america/rss.xml", False),
    ("BBC News", "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml", False),
    ("BBC News", "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml", False),
    ("BBC News", "https://feeds.bbci.co.uk/news/politics/rss.xml", True),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", False),
    ("The Guardian", "https://www.theguardian.com/world/rss", False),
    ("France 24", "https://www.france24.com/en/rss", False),
]
POLL_SECONDS = 900      # every 15 minutes
FEED_SPACING = 2        # seconds between feeds
KEEP_DAYS = 7
MAX_PER_FEED = 60
MAX_FEED_BYTES = 3_000_000

# Edit this list to change what counts as "politics".
POLITICS_RE = re.compile(
    r"\b(election|elections|elect|voters?|vote|votes|parliament\w*|president\w*|prime minister|government|"
    r"minister\w*|protest\w*|sanction\w*|summit|ceasefire|treaty|senate|congress|coalition|referendum|"
    r"diplomat\w*|opposition|lawmakers?|cabinet)\b",
    re.IGNORECASE,
)

# short forms and adjectives that name a country in headlines
ALIASES = {
    "US": "United States of America", "U.S.": "United States of America", "USA": "United States of America",
    "America": "United States of America", "Washington": "United States of America", "UK": "United Kingdom", "Britain": "United Kingdom",
    "British": "United Kingdom", "England": "United Kingdom", "Scotland": "United Kingdom", "Wales": "United Kingdom",
    "West Bank": "Palestine", "Palestinian": "Palestine", "Palestinians": "Palestine",
    "UAE": "United Arab Emirates", "Saudi": "Saudi Arabia", "Ivory Coast": "C\u00f4te d'Ivoire",
    "DR Congo": "Dem. Rep. Congo", "DRC": "Dem. Rep. Congo", "Czech Republic": "Czechia",
    "Ukrainian": "Ukraine", "Russian": "Russia", "Iranian": "Iran", "Israeli": "Israel", "Chinese": "China",
    "Indian": "India", "Pakistani": "Pakistan", "French": "France", "German": "Germany", "Italian": "Italy",
    "Spanish": "Spain", "Turkish": "Turkey", "Syrian": "Syria", "Afghan": "Afghanistan", "Sudanese": "Sudan",
    "Nigerian": "Nigeria", "Egyptian": "Egypt", "Brazilian": "Brazil", "Mexican": "Mexico",
    "Venezuelan": "Venezuela", "Japanese": "Japan", "Taiwanese": "Taiwan", "Iraqi": "Iraq",
    "Lebanese": "Lebanon", "Yemeni": "Yemen", "Libyan": "Libya", "Ethiopian": "Ethiopia", "Kenyan": "Kenya",
    "Australian": "Australia", "Canadian": "Canada", "Argentine": "Argentina", "Greek": "Greece",
    "Polish": "Poland", "Dutch": "Netherlands", "Swedish": "Sweden", "Irish": "Ireland", "Cuban": "Cuba",
    "Colombian": "Colombia", "Somali": "Somalia", "Haitian": "Haiti", "Indonesian": "Indonesia",
    "Filipino": "Philippines", "Thai": "Thailand", "Vietnamese": "Vietnam", "Burmese": "Myanmar",
}
# modern or alternative spellings of cities that the city list holds under another name
ALIAS_CITIES = {
    "Kyiv": "Kiev", "Odesa": "Odessa", "Kharkov": "Kharkiv", "Yangon": "Rangoon",
    "Saint Petersburg": "St. Petersburg", "Lviv": "Lvov", "Bombay": "Mumbai", "Calcutta": "Kolkata",
    "Madras": "Chennai", "Sevilla": "Seville", "Nay Pyi Taw": "Naypyidaw",
}
# ordinary words that are also small-city names
AMBIGUOUS_CITIES = {"Nice", "Reading", "Mobile", "Orange", "Victoria", "Hope", "Lincoln", "Bath"}


# ---------- placing a headline on the map ----------
class Gazetteer:
    def __init__(self, cities, countries):
        self.by_name = {}
        for c in cities:
            if c["name"] in AMBIGUOUS_CITIES:
                continue
            self.by_name[c["name"]] = ("city", f"{c['name']}, {c['country']}", c["lat"], c["lon"])
        for alias, target in ALIAS_CITIES.items():
            if alias not in self.by_name and self.by_name.get(target, ("",))[0] == "city":
                kind, place, lat, lon = self.by_name[target]
                self.by_name[alias] = (kind, place.replace(target, alias, 1), lat, lon)
        by_country = {}
        for c in countries:
            by_country[c["name"]] = c
            self.by_name[c["name"]] = ("country", c["name"], c["lat"], c["lon"])
        for alias, target in ALIASES.items():
            t = by_country.get(target)
            if t:
                self.by_name[alias] = ("country", t["name"], t["lat"], t["lon"])
        names = sorted(self.by_name, key=len, reverse=True)
        self.regex = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z])")

    def locate(self, title, description=""):
        """A city beats a country; the title beats the description. Returns (place, lat, lon) or None."""
        for text in (title, description):
            city = country = None
            for m in self.regex.finditer(text or ""):
                kind, place, lat, lon = self.by_name[m.group(1)]
                if kind == "city" and city is None:
                    city = (place, lat, lon)
                elif kind == "country" and country is None:
                    country = (place, lat, lon)
            if city or country:
                return city or country
        return None


def load_gazetteer():
    cities = json.loads(CITIES_FILE.read_text(encoding="utf-8"))
    countries = json.loads(COUNTRIES_FILE.read_text(encoding="utf-8"))["countries"]
    return Gazetteer(cities, countries)


# ---------- reading feeds ----------
def _clean(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def _norm_url(url):
    """Drop tracking query strings so the same story from two feeds is one story."""
    p = urlsplit((url or "").strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}{p.path}"


def _when(text):
    try:
        d = parsedate_to_datetime(text)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        return datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except Exception:
        return None


def parse_feed(data: bytes):
    """RSS 2.0 or Atom -> [{title, url, published, description}]"""
    root = ET.fromstring(data)
    items = []
    for it in root.iter():
        tag = it.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        kids = {k.tag.rsplit("}", 1)[-1]: k for k in it}
        title = _clean(kids["title"].text) if "title" in kids else ""
        link = None
        if "link" in kids:
            link = kids["link"].get("href") or kids["link"].text
        url = _norm_url(link)
        pub = None
        for k in ("pubDate", "published", "updated", "date"):
            if k in kids and kids[k].text:
                pub = _when(kids[k].text.strip())
                if pub:
                    break
        desc = ""
        for k in ("description", "summary"):
            if k in kids and kids[k].text:
                desc = _clean(kids[k].text)[:400]
                break
        if title and url:
            items.append({"title": title[:300], "url": url, "published": pub, "description": desc})
        if len(items) >= MAX_PER_FEED:
            break
    return items


def _download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "XYRON/1.0 (private dashboard)", "Accept": "application/rss+xml, application/xml, text/xml"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(MAX_FEED_BYTES)


# ---------- storage ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS headlines (
  url TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  title TEXT NOT NULL,
  published_at TIMESTAMPTZ NOT NULL,
  is_politics BOOLEAN NOT NULL DEFAULT false,
  place TEXT,
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS headlines_pub_idx ON headlines (published_at DESC);
"""
HEADLINE_UPSERT = """
INSERT INTO headlines (url, source, title, published_at, is_politics, place, lat, lon)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (url) DO UPDATE SET title = EXCLUDED.title, is_politics = headlines.is_politics OR EXCLUDED.is_politics,
  place = COALESCE(headlines.place, EXCLUDED.place), lat = COALESCE(headlines.lat, EXCLUDED.lat),
  lon = COALESCE(headlines.lon, EXCLUDED.lon), fetched_at = now()
"""


def init_schema():
    with get_conn() as conn:
        conn.execute(SCHEMA)


def headline_rows(source, politics_feed, items, gaz, now):
    rows = []
    for it in items:
        published = it["published"] or now
        if published < now - timedelta(hours=48) or published > now + timedelta(hours=2):
            continue
        spot = gaz.locate(it["title"], it["description"])
        is_pol = politics_feed or bool(POLITICS_RE.search(it["title"] + " " + it["description"]))
        rows.append((it["url"], source, it["title"], published, is_pol,
                     spot[0] if spot else None, spot[1] if spot else None, spot[2] if spot else None))
    return rows


LAYER_SQL = """
SELECT place, lat, lon, count(*) AS n,
       jsonb_agg(jsonb_build_object('title', title, 'url', url, 'domain', source) ORDER BY published_at DESC) AS arts
FROM headlines
WHERE published_at > now() - interval '24 hours' AND place IS NOT NULL AND (%s OR is_politics)
GROUP BY place, lat, lon
ORDER BY n DESC
LIMIT 300
"""


def rebuild_layers(started):
    with get_conn() as conn:
        for layer, everything in (("news", True), ("politics", False)):
            places = conn.execute(LAYER_SQL, (everything,)).fetchall()
            rows = [(
                "newsfeeds", f"{layer}|{p['place']}", layer,
                f"{p['place']} \u2014 {p['n']} headline" + ("" if p["n"] == 1 else "s"),
                p["lat"], p["lon"], float(p["n"]), started, None, None,
                Jsonb({"place": p["place"], "count": p["n"], "articles": p["arts"][:5]}),
            ) for p in places]
            with conn.cursor() as cur:
                if rows:
                    cur.executemany(UPSERT, rows)
            conn.execute("DELETE FROM events WHERE source = 'newsfeeds' AND layer = %s AND fetched_at < %s", (layer, started))
            feed_status[layer] = {"last_ok": datetime.now(timezone.utc), "error": None}
        conn.execute("DELETE FROM headlines WHERE published_at < now() - make_interval(days => %s)", (KEEP_DAYS,))


def refresh_all(gaz):
    started = datetime.now(timezone.utc)
    ok = failed = new = 0
    for i, (source, url, politics_feed) in enumerate(FEEDS):
        if i:
            time.sleep(FEED_SPACING)
        try:
            items = parse_feed(_download(url))
            rows = headline_rows(source, politics_feed, items, gaz, started)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.executemany(HEADLINE_UPSERT, rows)
            ok += 1
            new += len(rows)
        except Exception as e:  # one broken feed must not stop the others
            failed += 1
            log.warning("feed failed (%s): %s: %s", url, type(e).__name__, str(e)[:100])
    if ok:
        rebuild_layers(started)
    return ok, failed, new


async def ingest_loop():
    await asyncio.sleep(30)
    try:
        await asyncio.to_thread(init_schema)
        gaz = await asyncio.to_thread(load_gazetteer)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("news setup failed")
        return
    while True:
        try:
            ok, failed, n = await asyncio.to_thread(refresh_all, gaz)
            log.info("news: %d feeds read, %d failed, %d headlines seen", ok, failed, n)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("news refresh failed")
        await asyncio.sleep(POLL_SECONDS)


@router.get("/api/headlines")
def list_headlines(
    limit: int = Query(60, ge=1, le=200),
    hours: int = Query(24, ge=1, le=72),
    source: str = Query("", max_length=40),
    q: str = Query("", max_length=60),
    place: str = Query("", max_length=80),
    politics: bool = False,
    user=Depends(current_user),
):
    sql = ["SELECT title, url, source, published_at, is_politics, place FROM headlines "
           "WHERE published_at > now() - make_interval(hours => %s)"]
    args = [hours]
    if source:
        sql.append("AND source = %s"); args.append(source)
    if q:
        sql.append("AND title ILIKE %s"); args.append(f"%{q}%")
    if place:
        sql.append("AND place ILIKE %s"); args.append(f"%{place}%")
    if politics:
        sql.append("AND is_politics")
    sql.append("ORDER BY published_at DESC LIMIT %s"); args.append(limit)
    with get_conn() as conn:
        return conn.execute(" ".join(sql), args).fetchall()
