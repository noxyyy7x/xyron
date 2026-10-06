import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from . import sports
from .db import get_conn
from .deps import current_user
from .news import _download, parse_feed

log = logging.getLogger("xyron.football")
router = APIRouter(prefix="/api/football")

SITE = sports.ESPN
V2 = "https://site.api.espn.com/apis/v2/sports/"
NEWS_RSS = [("BBC Sport", "https://feeds.bbci.co.uk/sport/football/rss.xml"), ("The Guardian", "https://www.theguardian.com/football/rss")]
DEFAULT_NEWS_LEAGUES = ["eng.1", "uefa.champions"]

STAT_LABELS = {
    "possessionPct": "Possession %", "totalShots": "Shots", "shotsOnTarget": "Shots on target", "wonCorners": "Corners",
    "foulsCommitted": "Fouls", "offsides": "Offsides", "saves": "Saves", "yellowCards": "Yellow cards", "redCards": "Red cards",
    "totalPasses": "Passes", "accuratePasses": "Passes completed", "passPct": "Pass accuracy %", "tackles": "Tackles",
    "interceptions": "Interceptions", "blockedShots": "Blocked shots", "totalCrosses": "Crosses", "totalClearance": "Clearances",
    "goalDifference": "Goal difference", "totalGoals": "Goals", "goalAssists": "Assists", "goalsConceded": "Goals conceded",
}
SEASON_STATS = {"goalDifference", "totalGoals", "goalAssists", "goalsConceded"}
STAT_ORDER = list(STAT_LABELS)

# ---------- a small cache, so many viewers cost ESPN one request ----------
_cache = {}
_lock = threading.Lock()


def cached(key, ttl, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
        try:
            value = fn()
        except Exception as e:
            log.warning("football %s failed: %s: %s", key[0], type(e).__name__, str(e)[:100])
            if hit:
                return hit[1]  # an out-of-date answer beats an error
            raise HTTPException(502, "Football data is unavailable right now")
        _cache[key] = (time.time() + (ttl(value) if callable(ttl) else ttl), value)
        if len(_cache) > 300:
            for k in [k for k, v in _cache.items() if v[0] < time.time()]:
                _cache.pop(k, None)
        return value


def d(x):
    """x if it is a dict, otherwise an empty one, so malformed data never crashes a parser."""
    return x if isinstance(x, dict) else {}


def lst(x):
    """The dict items of a list (anything else is ignored)."""
    return [i for i in x if isinstance(i, dict)] if isinstance(x, list) else []


def clip(x, n=200):
    return "" if x is None else str(x)[:n]


def number(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def team_of(c):
    c = d(c)
    team = d(c.get("team"))
    color = team.get("color") or ""
    return {"id": clip(team.get("id"), 20), "name": clip(team.get("displayName") or team.get("name")), "abbr": clip(team.get("abbreviation"), 6),
            "color": color if re.fullmatch(r"[0-9a-fA-F]{6}", color) else None, "score": clip(c.get("score"), 6)}


# ---------- match centre ----------
KINDS = [("own goal", "owngoal"), ("penalty - scored", "penalty"), ("penalty scored", "penalty"), ("penalty - missed", "penmiss"),
         ("penalty - saved", "penmiss"), ("penalty missed", "penmiss"), ("yellow", "yellow"), ("red card", "red"), ("second yellow", "red"),
         ("substitution", "sub"), ("goal", "goal"), ("var", "var"), ("kickoff", "period"), ("kick off", "period"), ("half", "period"),
         ("full time", "period"), ("end of", "period")]


def first(x):
    return x[0] if isinstance(x, list) and x else {}


def kind_of(text):
    low = (text or "").lower()
    for needle, kind in KINDS:
        if needle in low:
            return kind
    return "other"


def side_of(team_id, home, away):
    if team_id and team_id == home["id"]:
        return "home"
    if team_id and team_id == away["id"]:
        return "away"
    return ""


def events_of(summary, home, away):
    raw = lst(summary.get("keyEvents"))
    if not raw:
        raw = lst(d(first(d(summary.get("header")).get("competitions"))).get("details"))
    out = []
    for e in raw:
        t = d(e.get("type"))
        text = clip(t.get("text") or e.get("text") or e.get("shortText"))
        who = [d(p.get("athlete") or p).get("displayName") for p in lst(e.get("participants") or e.get("athletesInvolved"))]
        out.append({"minute": clip(d(e.get("clock")).get("displayValue"), 12), "kind": kind_of(text), "text": text,
                    "player": ", ".join(clip(w, 60) for w in who if w)[:160], "side": side_of(clip(d(e.get("team")).get("id"), 20), home, away)})
    return out[:120]


def stats_of(summary, home, away):
    sides = {}
    for t in lst(d(summary.get("boxscore")).get("teams")):
        side = t.get("homeAway") or side_of(clip(d(t.get("team")).get("id"), 20), home, away)
        if side not in ("home", "away"):
            continue
        for st in lst(t.get("statistics")):
            name = clip(st.get("name"), 40)
            if name:
                sides.setdefault(name, {})[side] = (clip(st.get("displayValue") or st.get("value"), 14), clip(st.get("label") or st.get("displayName"), 40))
    rows = []
    for name, v in sides.items():
        label = STAT_LABELS.get(name) or next((x[1] for x in v.values() if x[1]), name)
        rows.append({"name": name, "label": label, "home": (v.get("home") or ("", ""))[0], "away": (v.get("away") or ("", ""))[0], "season": name in SEASON_STATS})
    rows.sort(key=lambda r: (STAT_ORDER.index(r["name"]) if r["name"] in STAT_ORDER else 999))
    return rows[:30]


def lineups_of(summary):
    out = {}
    for r in lst(summary.get("rosters")):
        side = r.get("homeAway")
        if side not in ("home", "away"):
            continue
        f = r.get("formation")
        players = []
        for p in lst(r.get("roster")):
            a = d(p.get("athlete"))
            pos = d(p.get("position"))
            players.append({"name": clip(a.get("displayName") or a.get("shortName"), 60), "number": clip(p.get("jersey"), 4), "pos": clip(pos.get("abbreviation") or pos.get("displayName"), 6),
                            "starter": bool(p.get("starter")), "place": number(p.get("formationPlace")) or 99,
                            "subbed": bool(p.get("subbedIn") or p.get("subbedOut"))})
        starters = sorted((p for p in players if p["starter"]), key=lambda p: p["place"])
        out[side] = {"formation": clip(f.get("displayName") if isinstance(f, dict) else f, 20),
                     "starters": starters[:11], "subs": [p for p in players if not p["starter"]][:16]}
    return out


def commentary_of(summary):
    out = []
    for c in lst(summary.get("commentary")):
        if c.get("text"):
            out.append({"minute": clip(d(c.get("time")).get("displayValue"), 12), "text": clip(c.get("text"), 300)})
    return list(reversed(out))[:50]


def build_match(summary, event_id):
    summary = d(summary)
    header = d(summary.get("header"))
    hc = d(first(header.get("competitions")))
    comps = lst(hc.get("competitors"))
    home_c = next((c for c in comps if c.get("homeAway") == "home"), comps[0] if comps else {})
    away_c = next((c for c in comps if c is not home_c), comps[1] if len(comps) > 1 else {})
    home, away = team_of(home_c), team_of(away_c)
    status = d(hc.get("status"))
    st = d(status.get("type"))
    gi = d(summary.get("gameInfo"))
    venue = d(gi.get("venue"))
    officials = lst(gi.get("officials"))
    ref = next((o for o in officials if "referee" in str(d(o.get("position")).get("displayName") or "").lower()), officials[0] if officials else None)
    lg = d(header.get("league"))
    slug = ""
    for info in sports.load_names().values() if lg.get("id") else []:
        if info["name"] == lg.get("name"):
            slug = info["slug"]
            break
    return {
        "id": event_id, "league": clip(lg.get("name")), "league_slug": slug,
        "state": st.get("state") if st.get("state") in ("pre", "in", "post") else "pre",
        "status": clip(st.get("shortDetail") or status.get("displayClock")), "clock": clip(status.get("displayClock"), 12),
        "start": clip(hc.get("date"), 40), "home": home, "away": away,
        "venue": clip(venue.get("fullName")), "city": clip(d(venue.get("address")).get("city")),
        "attendance": clip(gi.get("attendance"), 10), "referee": clip((ref or {}).get("displayName"), 60) if ref else "",
        "events": events_of(summary, home, away), "stats": stats_of(summary, home, away),
        "lineups": lineups_of(summary), "commentary": commentary_of(summary),
    }


# ---------- tables ----------
def build_standings(data):
    data = d(data)
    groups = []
    kids = lst(data.get("children")) or ([data] if data.get("standings") else [])
    for kid in kids:
        rows = []
        for i, entry in enumerate(lst(d(kid.get("standings")).get("entries"))):
            stats = {s.get("name"): s for s in lst(entry.get("stats"))}
            val = lambda k: (int(number(stats[k].get("value"))) if k in stats and number(stats[k].get("value")) is not None else None)  # noqa: E731
            t = team_of(entry)
            note = d(entry.get("note"))
            rows.append({"rank": val("rank") or i + 1, "team": t["name"], "abbr": t["abbr"], "color": t["color"], "played": val("gamesPlayed"), "won": val("wins"),
                         "drawn": val("ties"), "lost": val("losses"), "gf": val("pointsFor"), "ga": val("pointsAgainst"), "gd": val("pointDifferential"),
                         "pts": val("points"), "note": clip(note.get("description"), 60), "note_color": clip(note.get("color"), 9)})
        rows.sort(key=lambda r: r["rank"])
        if rows:
            groups.append({"name": clip(kid.get("name") or kid.get("abbreviation")), "rows": rows[:40]})
    return {"name": clip(data.get("name")), "groups": groups}


# ---------- news ----------
def _iso(d):
    return d.isoformat() if isinstance(d, datetime) else (clip(d, 40) or None)


def build_news(league):
    items, seen = [], set()

    def add(title, url, source, published):
        key = (title or "").strip().lower()
        if title and key not in seen and str(url).startswith("https://"):
            seen.add(key)
            items.append({"title": clip(title, 220), "url": clip(url, 400), "source": source, "published": _iso(published)})

    for source, url in NEWS_RSS:
        try:
            for it in parse_feed(_download(url))[:25]:
                add(it["title"], it["url"], source, it["published"])
        except Exception as e:
            log.warning("football news %s failed: %s", source, type(e).__name__)
    for slug in ([league] if league else DEFAULT_NEWS_LEAGUES):
        try:
            for a in (sports._get_json(SITE + f"soccer/{slug}/news").get("articles") or [])[:15]:
                add(a.get("headline"), ((a.get("links") or {}).get("web") or {}).get("href"), "ESPN", a.get("published"))
        except Exception as e:
            log.warning("football news ESPN %s failed: %s", slug, type(e).__name__)
    items.sort(key=lambda i: i["published"] or "", reverse=True)
    return items[:40]


# ---------- routes ----------
def _window(frm, to):
    now = datetime.now(timezone.utc)
    start = sports._when(frm) if frm else now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = sports._when(to) if to else None
    if not start:
        raise HTTPException(422, "Bad 'from' time")
    start = max(start, now - timedelta(days=3))
    end = min(end or start + timedelta(days=1), start + timedelta(days=3))
    return start, end


def flat(row):
    d = row["detail"]
    return {"id": d.get("event_id"), "league": d.get("league", ""), "league_slug": d.get("league_slug", ""), "state": row["state"], "status": d.get("status", ""),
            "start": row["start_at"].isoformat(), "home": d.get("home"), "away": d.get("away"), "venue": d.get("venue"), "city": d.get("city"),
            "lat": row["lat"], "lon": row["lon"], "url": row["url"]}


@router.get("/matches")
def matches(frm: str = Query(None, alias="from", max_length=40), to: str = Query(None, max_length=40),
            state: str = Query("", pattern="^(|pre|in|post)$"), user=Depends(current_user)):
    start, end = _window(frm, to)
    sql = ("SELECT state, start_at, lat, lon, url, detail FROM matches WHERE sport = 'football' AND detail ? 'home' "
           "AND ((start_at >= %s AND start_at < %s) OR state = 'in')")
    args = [start, end]
    if state:
        sql += " AND state = %s"
        args.append(state)
    sql += " ORDER BY (state = 'in') DESC, start_at ASC LIMIT 600"
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return {"matches": [flat(r) for r in rows], "updated": datetime.now(timezone.utc).isoformat()}


@router.get("/leagues")
def leagues(user=Depends(current_user)):
    with get_conn() as conn:
        known = {r["slug"]: r["name"] for r in conn.execute("SELECT slug, name FROM football_leagues").fetchall()}
    return [{"slug": s, "name": known[s]} for s in sports.FOOTBALL_LEAGUES if s in known]


@router.get("/standings")
def standings(league: str = Query(..., pattern=r"^[a-z0-9._-]{2,40}$"), user=Depends(current_user)):
    if league not in sports.FOOTBALL_LEAGUES:
        raise HTTPException(404, "Unknown league")
    return cached(("table", league), 600, lambda: build_standings(sports._get_json(V2 + f"soccer/{league}/standings")))


@router.get("/news")
def news(league: str = Query("", pattern=r"^([a-z0-9._-]{2,40})?$"), user=Depends(current_user)):
    if league and league not in sports.FOOTBALL_LEAGUES:
        raise HTTPException(404, "Unknown league")
    return cached(("news", league), 600, lambda: build_news(league))


@router.get("/match/{event_id}")
def match(event_id: str = Path(..., pattern=r"^\d{3,12}$"), user=Depends(current_user)):
    return cached(("match", event_id), lambda v: 15 if v["state"] == "in" else 180,
                  lambda: build_match(sports._get_json(SITE + f"soccer/all/summary?event={event_id}"), event_id))
