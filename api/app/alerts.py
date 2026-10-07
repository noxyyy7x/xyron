"""Alerts: rules each user chooses, detectors that spot things worth telling someone about, and careful delivery to Telegram.

Design rules that keep it from being spammy:
  - nothing is on until a user switches it on, and switching a rule on never replays the past
  - the same thing is never sent twice to the same person
  - things that arrive together are grouped into one message
  - a daily limit, quiet hours, a daily-summary mode, a pause, and a mute for each rule
"""
import json
import logging
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timedelta, timezone, time as dtime
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from . import tgbot
from .db import get_conn

log = logging.getLogger("xyron.alerts")

APP_DIR = Path(__file__).resolve().parent
PLACES_FILE = APP_DIR / "data" / "places.json"                  # cities (ships with the search feature)
COUNTRIES_FILE = APP_DIR / "static" / "globe" / "dots.json"      # countries (ships with the globe)

CYCLE = 30                  # seconds between checks
EVENT_KEEP_DAYS = 14
STATE_KEEP_DAYS = 3
LINK_MINUTES = 10
GROUP_AFTER = 3             # more than this many in one go are sent as a single grouped message
GROUP_LINES = 12
URGENT_EXTRA = 10           # urgent alerts may go this far past the daily limit

RULES = {
    "quake": {"label": "Earthquakes", "blurb": "A new earthquake at or above the strength you choose.", "admin": False},
    "hazard": {"label": "Natural hazards", "blurb": "New wildfires, storms, volcanoes and floods reported by NASA.", "admin": False},
    "price": {"label": "Watchlist price moves", "blurb": "When something on your markets watchlist moves a lot in a day.", "admin": False},
    "index": {"label": "Stock index moves", "blurb": "When a major index such as the S&P 500 or FTSE 100 moves a lot in a day.", "admin": False},
    "crypto": {"label": "Crypto moves", "blurb": "When a coin you pick moves a lot in 24 hours.", "admin": False},
    "football": {"label": "Football", "blurb": "Kick-off, goals and full time for the teams you follow.", "admin": False},
    "squawk": {"label": "Aircraft emergencies", "blurb": "An aircraft squawking an emergency code.", "admin": False},
    "security": {"label": "Your account security", "blurb": "Sign-ins to your account from a new address, and repeated failed attempts.", "admin": False},
    "admin": {"label": "Owner and admin notices", "blurb": "New registrations waiting for approval, and bursts of blocked sign-ins.", "admin": True},
}
HAZARD_CATS = {"volcanoes": "Volcanoes", "severeStorms": "Severe storms", "wildfires": "Wildfires", "floods": "Floods", "landslides": "Landslides", "drought": "Drought",
               "dustHaze": "Dust and haze", "seaLakeIce": "Sea and lake ice", "snow": "Snow", "tempExtremes": "Temperature extremes"}
INDEX_CHOICES = [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow Jones"), ("^FTSE", "FTSE 100"), ("^GDAXI", "DAX"), ("^FCHI", "CAC 40"),
                 ("^N225", "Nikkei 225"), ("^HSI", "Hang Seng"), ("000001.SS", "Shanghai"), ("^NSEI", "Nifty 50")]
COIN_CHOICES = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "LTC"]
SQUAWKS = {"7700": "general emergency", "7600": "radio failure", "7500": "hijacking"}
DEFAULT_PARAMS = {
    "quake": {"min_mag": 6.0, "near": None},
    "hazard": {"categories": ["volcanoes", "severeStorms"], "near": None},
    "price": {"threshold": 5.0},
    "index": {"indices": ["^GSPC", "^IXIC", "^FTSE", "^N225"], "threshold": 2.0},
    "crypto": {"coins": ["BTC", "ETH"], "threshold": 8.0},
    "football": {"teams": [], "kickoff": True, "goals": True, "fulltime": True},
    "squawk": {"codes": ["7700", "7500"]},
    "security": {"new_address": True, "failed": True},
    "admin": {"registrations": True, "blocked": True},
}
DEFAULT_SETTINGS = {"tz": "Europe/London", "quiet_start": None, "quiet_end": None, "daily_cap": 30, "mode": "instant", "digest_hour": 8}
TEAM_SUFFIXES = {"women", "w", "u18", "u19", "u21", "u23", "ii", "b", "reserves", "youth"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_settings (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  tz TEXT NOT NULL DEFAULT 'Europe/London', quiet_start TEXT, quiet_end TEXT, daily_cap INT NOT NULL DEFAULT 30,
  mode TEXT NOT NULL DEFAULT 'instant', digest_hour INT NOT NULL DEFAULT 8, paused_until TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS alert_rules (
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT false,
  params JSONB NOT NULL DEFAULT '{}', muted_until TIMESTAMPTZ, enabled_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, kind)
);
CREATE TABLE IF NOT EXISTS alert_telegram (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, chat_id BIGINT NOT NULL UNIQUE, name TEXT,
  active BOOLEAN NOT NULL DEFAULT true, linked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS alert_link_tokens (
  token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS alert_state (key TEXT PRIMARY KEY, value JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS alert_events (key TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), seen_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS alert_deliveries (
  id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, rule_kind TEXT NOT NULL, dedupe_key TEXT NOT NULL,
  payload JSONB NOT NULL, urgent BOOLEAN NOT NULL DEFAULT false, status TEXT NOT NULL DEFAULT 'pending', reason TEXT, attempts INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), deliver_after TIMESTAMPTZ, sent_at TIMESTAMPTZ, UNIQUE (user_id, dedupe_key)
);
ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS seen_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS alert_deliveries_user_idx ON alert_deliveries (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS alert_deliveries_open_idx ON alert_deliveries (status) WHERE status IN ('pending', 'queued');
"""


def init_schema():
    with get_conn() as conn:
        conn.execute(SCHEMA)


# ---------- small helpers ----------
def fold(text):
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def km_between(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(a)))


def tz_of(name):
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Europe/London") if name != "UTC" else timezone.utc


def get_state(conn, key, default=None):
    row = conn.execute("SELECT value FROM alert_state WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key, value):
    conn.execute("INSERT INTO alert_state (key, value, updated_at) VALUES (%s,%s,now()) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()", (key, Jsonb(value)))


# ---------- rule settings: checking what a user sends ----------
def _num(v, lo, hi, name):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(x) or not lo <= x <= hi:
        raise ValueError(f"{name} must be between {lo:g} and {hi:g}")
    return round(x, 2)


def _subset(v, allowed, name, minimum=1):
    if not isinstance(v, list):
        raise ValueError(f"{name} must be a list")
    out = []
    for item in v:
        if str(item) not in allowed:
            raise ValueError(f"{name}: '{str(item)[:20]}' is not one of the choices")
        if str(item) not in out:
            out.append(str(item))
    if len(out) < minimum:
        raise ValueError(f"Pick at least one for {name}")
    return out


def _flag(v, name):
    if not isinstance(v, bool):
        raise ValueError(f"{name} must be on or off")
    return v


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


@lru_cache(maxsize=1)
def place_index():
    """(countries, cities) as (folded name, record) pairs. Whatever data file is missing simply contributes nothing."""
    raw = _read_json(COUNTRIES_FILE, {})
    countries = raw.get("countries", []) if isinstance(raw, dict) else []
    cities = _read_json(PLACES_FILE, [])
    cities = cities if isinstance(cities, list) else []
    return ([(fold(c["name"]), c) for c in countries if isinstance(c, dict) and "name" in c], [(fold(c["name"]), c) for c in cities if isinstance(c, dict) and "name" in c])


def find_place(name):
    """A place by name (a city or a country), as {name, lat, lon}, or None."""
    key = fold(name)
    if len(key) < 2:
        return None
    countries, cities = place_index()
    exact = [c for k, c in countries + cities if k == key]
    if exact:
        best = max(exact, key=lambda c: c.get("pop", 0))
    else:
        near = [c for k, c in countries + cities if k.startswith(key)]
        if not near:
            return None
        best = max(near, key=lambda c: c.get("pop", 0))
    return {"name": best["name"], "lat": best["lat"], "lon": best["lon"]}


def _near(v):
    if v in (None, {}, ""):
        return None
    if not isinstance(v, dict) or not isinstance(v.get("name"), str):
        raise ValueError("'Near' needs a place name")
    place = find_place(v["name"])
    if not place:
        raise ValueError(f"I could not find a place called '{v['name'][:40]}'")
    return {**place, "radius_km": int(_num(v.get("radius_km", 500), 50, 5000, "The distance"))}


def validate_params(kind, params):
    if kind not in RULES:
        raise ValueError("Unknown alert type")
    p = {**DEFAULT_PARAMS[kind], **(params if isinstance(params, dict) else {})}
    if kind == "quake":
        return {"min_mag": _num(p["min_mag"], 4.0, 9.0, "The magnitude"), "near": _near(p["near"])}
    if kind == "hazard":
        return {"categories": _subset(p["categories"], HAZARD_CATS, "Kinds of hazard"), "near": _near(p["near"])}
    if kind == "price":
        return {"threshold": _num(p["threshold"], 1, 50, "The size of move")}
    if kind == "index":
        return {"indices": _subset(p["indices"], dict(INDEX_CHOICES), "Indices"), "threshold": _num(p["threshold"], 0.5, 10, "The size of move")}
    if kind == "crypto":
        return {"coins": _subset(p["coins"], COIN_CHOICES, "Coins"), "threshold": _num(p["threshold"], 2, 50, "The size of move")}
    if kind == "football":
        teams = p["teams"]
        if not isinstance(teams, list) or len(teams) > 12:
            raise ValueError("Follow between 0 and 12 teams")
        clean = []
        for t in teams:
            if not isinstance(t, str) or not 2 <= len(t.strip()) <= 40:
                raise ValueError("A team name must be 2 to 40 characters")
            t = " ".join(t.split())
            if fold(t) not in [fold(x) for x in clean]:
                clean.append(t)
        return {"teams": clean, "kickoff": _flag(p["kickoff"], "Kick-off"), "goals": _flag(p["goals"], "Goals"), "fulltime": _flag(p["fulltime"], "Full time")}
    if kind == "squawk":
        return {"codes": _subset(p["codes"], SQUAWKS, "Codes")}
    if kind == "security":
        return {"new_address": _flag(p["new_address"], "New address"), "failed": _flag(p["failed"], "Failed sign-ins")}
    return {"registrations": _flag(p["registrations"], "Registrations"), "blocked": _flag(p["blocked"], "Blocked sign-ins")}


def _hhmm(v, name):
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ValueError(f"{name} must look like 22:30")
    return v


def validate_settings(data):
    d = {**DEFAULT_SETTINGS, **(data if isinstance(data, dict) else {})}
    tz = d["tz"]
    try:
        ZoneInfo(tz)
    except Exception:
        raise ValueError("That time zone is not recognised")
    qs, qe = _hhmm(d["quiet_start"], "Quiet hours start"), _hhmm(d["quiet_end"], "Quiet hours end")
    if bool(qs) != bool(qe):
        raise ValueError("Give both a start and an end for quiet hours, or neither")
    if qs and qs == qe:
        raise ValueError("Quiet hours cannot start and end at the same time")
    if d["mode"] not in ("instant", "digest"):
        raise ValueError("Delivery must be instant or a daily summary")
    return {"tz": tz, "quiet_start": qs, "quiet_end": qe, "daily_cap": int(_num(d["daily_cap"], 5, 200, "The daily limit")), "mode": d["mode"],
            "digest_hour": int(_num(d["digest_hour"], 0, 23, "The summary hour"))}


# ---------- when is it quiet, when is the next summary ----------
def _parse_hhmm(text):
    h, m = text.split(":")
    return dtime(int(h), int(m))


def in_quiet(settings, now):
    if not settings.get("quiet_start") or not settings.get("quiet_end"):
        return False
    t = now.astimezone(tz_of(settings["tz"])).time()
    s, e = _parse_hhmm(settings["quiet_start"]), _parse_hhmm(settings["quiet_end"])
    return s <= t < e if s < e else (t >= s or t < e)


def next_local(settings, now, at):
    """The next moment (UTC) at which the local clock reads `at` (a time of day)."""
    tz = tz_of(settings["tz"])
    local = now.astimezone(tz)
    cand = datetime.combine(local.date(), at, tzinfo=tz)
    if cand <= local:
        cand = datetime.combine(local.date() + timedelta(days=1), at, tzinfo=tz)
    return cand.astimezone(timezone.utc)


# ---------- what an alert says ----------
def _t(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%H:%M UTC")
    except ValueError:
        return ""


def _fmt_price(p):
    try:
        p = float(p)
    except (TypeError, ValueError):
        return ""
    return f"{p:,.2f}" if abs(p) >= 1 else f"{p:.4f}"


def compose(kind, p):
    """(full message in HTML, one-line version) for an alert."""
    e = tgbot.esc
    if kind == "quake":
        place = re.sub(r"^M\s*[\d.]+\s*-\s*", "", p.get("title", "")) or p.get("title", "")
        return (f"\U0001F30D <b>M{p.get('mag', 0):.1f} earthquake</b>\n{e(place)}\n{_t(p.get('time'))} \u00b7 {p.get('lat', 0):.2f}, {p.get('lon', 0):.2f}",
                f"\U0001F30D M{p.get('mag', 0):.1f} \u00b7 {e(place)}")
    if kind == "hazard":
        size = f" \u00b7 {p['magnitude']:g} {e(p.get('unit') or '')}".rstrip() if p.get("magnitude") is not None else ""
        return (f"\u26A0\uFE0F <b>{e(p.get('label'))}</b>: {e(p.get('title'))}{size}\nReported {_t(p.get('date')) or 'just now'}", f"\u26A0\uFE0F {e(p.get('label'))}: {e(p.get('title'))}")
    if kind in ("price", "index", "crypto"):
        icon = {"price": "\U0001F4C8" if p.get("chg", 0) >= 0 else "\U0001F4C9", "index": "\U0001F4CA", "crypto": "\U0001FA99"}[kind]
        span = "in 24 hours" if kind == "crypto" else "today"
        sym = f" ({e(p.get('symbol'))})" if kind == "price" else ""
        return (f"{icon} <b>{e(p.get('name'))}</b>{sym} {p.get('chg', 0):+.1f}% {span}\nNow {_fmt_price(p.get('price'))} {e(p.get('currency') or '')}".rstrip(),
                f"{icon} {e(p.get('name'))} {p.get('chg', 0):+.1f}% {span}")
    if kind == "match":
        h, a, league = e(p.get("home")), e(p.get("away")), e(p.get("league") or "")
        sub = p.get("sub")
        if sub == "kickoff":
            return (f"\u26BD Kick-off: <b>{h} vs {a}</b>\n{league}".rstrip(), f"\u26BD Kick-off: {h} vs {a}")
        if sub == "goal":
            who = e(p.get("home") if p.get("scorer") == "home" else p.get("away"))
            return (f"\u26BD <b>GOAL</b> {who}\n{h} {p.get('hs')}\u2013{p.get('as')} {a}\n{e(p.get('minute') or '')} {league}".strip(), f"\u26BD GOAL {who}: {h} {p.get('hs')}\u2013{p.get('as')} {a}")
        return (f"\U0001F3C1 Full time: <b>{h} {p.get('hs')}\u2013{p.get('as')} {a}</b>\n{league}".rstrip(), f"\U0001F3C1 FT {h} {p.get('hs')}\u2013{p.get('as')} {a}")
    if kind == "squawk":
        who = e(p.get("callsign") or str(p.get("icao24", "")).upper())
        alt = f" \u00b7 {round(p['alt_m'] * 3.28084):,} ft" if p.get("alt_m") else ""
        return (f"\u2708\uFE0F <b>{who}</b> is squawking {e(p.get('code'))} ({e(p.get('meaning'))})\n{e(p.get('country') or '')}{alt} \u00b7 {p.get('lat', 0):.2f}, {p.get('lon', 0):.2f}",
                f"\u2708\uFE0F {who} squawking {e(p.get('code'))} ({e(p.get('meaning'))})")
    if kind == "security":
        if p.get("sub") == "failed":
            return (f"\U0001F510 <b>{p.get('count')} failed sign-in attempts</b> on your XYRON account in the last 15 minutes.\nIf that was not you, change your password.", f"\U0001F510 {p.get('count')} failed sign-ins on your account")
        return (f"\U0001F510 <b>New sign-in</b> to your XYRON account\nFrom address {e(p.get('ip'))} at {_t(p.get('time'))}.\nIf that was not you, change your password and tell the owner.", f"\U0001F510 New sign-in from {e(p.get('ip'))}")
    if kind == "admin":
        if p.get("sub") == "blocked":
            return (f"\U0001F6C2 <b>{p.get('count')} sign-ins blocked</b> by the rate limit in the last 15 minutes.", f"\U0001F6C2 {p.get('count')} sign-ins blocked")
        return (f"\U0001F6C2 <b>New registration</b> waiting for approval:\n{e(p.get('email'))}", f"\U0001F6C2 New registration: {e(p.get('email'))}")
    if kind == "test":
        return ("\u2705 <b>XYRON test alert</b>\nIf you can read this, alerts will reach you here.", "\u2705 XYRON test alert")
    return (e(json.dumps(p)[:200]), e(kind))


def plain(html_text):
    return re.sub(r"<[^>]+>", "", html_text).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def is_urgent(kind, p):
    if kind == "quake":
        return p.get("mag", 0) >= 7.5
    if kind == "squawk":
        return p.get("code") in ("7500", "7700")
    return kind == "security"


# ---------- spotting things: detectors ----------
def detect_quakes(conn, now):
    out = []
    rows = conn.execute("SELECT external_id, title, lat, lon, severity, occurred_at, url FROM events WHERE layer = 'earthquakes' AND occurred_at > %s AND COALESCE(severity, 0) >= 4.0", (now - timedelta(hours=2),)).fetchall()
    for r in rows:
        p = {"mag": float(r["severity"]), "title": r["title"], "lat": r["lat"], "lon": r["lon"], "time": r["occurred_at"].isoformat(), "url": r["url"]}
        out.append({"kind": "quake", "key": f"quake|{r['external_id']}", "payload": p, "urgent": is_urgent("quake", p)})
    return out


def detect_hazards(conn, now):
    out = []
    for r in conn.execute("SELECT external_id, title, lat, lon, detail FROM events WHERE layer = 'hazards'").fetchall():
        d = r["detail"] or {}
        p = {"title": r["title"], "lat": r["lat"], "lon": r["lon"], "category": d.get("category"), "label": d.get("category_label") or "Natural event", "magnitude": d.get("magnitude"), "unit": d.get("unit"), "date": d.get("date")}
        out.append({"kind": "hazard", "key": f"hazard|{r['external_id']}", "payload": p, "urgent": False})
    return out


def _score(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def detect_matches(conn, now):
    """Football moments, found by comparing each match with how it looked last time."""
    out = []
    rows = conn.execute("SELECT detail, state FROM matches WHERE sport = 'football' AND (state = 'in' OR start_at BETWEEN %s AND %s) AND detail ? 'home'", (now - timedelta(hours=8), now + timedelta(hours=1))).fetchall()
    for r in rows:
        d = r["detail"]
        eid = d.get("event_id")
        if not eid:
            continue
        cur = {"state": r["state"], "hs": _score((d.get("home") or {}).get("score")), "as": _score((d.get("away") or {}).get("score"))}
        prev = get_state(conn, f"m|{eid}")
        set_state(conn, f"m|{eid}", cur)
        if prev is None:
            continue  # first sight: just remember it, never announce the past
        base = {"home": (d.get("home") or {}).get("name"), "away": (d.get("away") or {}).get("name"), "league": d.get("league"), "event_id": eid, "hs": cur["hs"], "as": cur["as"], "minute": d.get("status")}
        if prev["state"] == "pre" and cur["state"] == "in":
            out.append({"kind": "match", "key": f"m|{eid}|ko", "payload": {**base, "sub": "kickoff"}, "urgent": False})
        if cur["state"] in ("in", "post") and (cur["hs"] > prev["hs"] or cur["as"] > prev["as"]):
            scorer = "home" if cur["hs"] > prev["hs"] else "away"
            out.append({"kind": "match", "key": f"m|{eid}|g|{cur['hs']}-{cur['as']}", "payload": {**base, "sub": "goal", "scorer": scorer}, "urgent": False})
        if prev["state"] in ("pre", "in") and cur["state"] == "post":
            out.append({"kind": "match", "key": f"m|{eid}|ft", "payload": {**base, "sub": "fulltime"}, "urgent": False})
    return out


_flights = {"body": None, "rows": []}


def current_flights():
    """The aircraft the globe is showing, read straight from the flights feed (parsed again only when it changes)."""
    from . import aviation
    body = aviation._snapshot.get("body")
    if body is not _flights["body"]:
        try:
            _flights["rows"] = json.loads(body).get("flights") or []
        except (ValueError, TypeError, AttributeError):
            _flights["rows"] = []
        _flights["body"] = body
    return _flights["rows"]


def detect_squawks(now):
    out = []
    for f in current_flights():
        code = str(f[11]) if len(f) > 11 and f[11] else ""
        if code in SQUAWKS:
            p = {"icao24": f[0], "callsign": f[1], "code": code, "meaning": SQUAWKS[code], "country": f[9], "alt_m": f[4], "lat": f[2], "lon": f[3]}
            out.append({"kind": "squawk", "key": f"sq|{f[0]}|{code}|{int(now.timestamp() // 21600)}", "payload": p, "urgent": is_urgent("squawk", p)})
    return out


def detect_security(conn, now):
    """Sign-in events, aimed at one user or at all admins."""
    out = []
    wm = get_state(conn, "audit_wm")
    top = conn.execute("SELECT COALESCE(max(id), 0) AS m FROM audit_log").fetchone()["m"]
    if wm is None:
        set_state(conn, "audit_wm", top)  # first run: start from now
        wm = top
    else:
        set_state(conn, "audit_wm", max(top, wm))
    for r in conn.execute("SELECT id, user_id, event, ip, ts FROM audit_log WHERE id > %s AND event IN ('login_ok', 'register', 'email_verified') ORDER BY id", (wm,)).fetchall():
        if r["event"] == "login_ok" and r["user_id"]:
            seen = conn.execute("SELECT 1 FROM audit_log WHERE user_id = %s AND event = 'login_ok' AND ip = %s AND id < %s AND ts > %s LIMIT 1", (r["user_id"], r["ip"], r["id"], now - timedelta(days=90))).fetchone()
            if not seen:
                p = {"sub": "newip", "ip": r["ip"], "time": r["ts"].isoformat()}
                out.append({"kind": "security", "target": r["user_id"], "key": f"sec|newip|{r['user_id']}|{r['ip']}", "payload": p, "urgent": True})
        elif r["event"] == "email_verified" and r["user_id"]:
            u = conn.execute("SELECT email FROM users WHERE id = %s", (r["user_id"],)).fetchone()
            if u:
                out.append({"kind": "admin", "target": "admins", "key": f"adm|reg|{r['user_id']}", "payload": {"sub": "registration", "email": u["email"]}, "urgent": False})
    bucket = int(now.timestamp() // 900)
    for r in conn.execute("SELECT user_id, count(*) AS n FROM audit_log WHERE event = 'login_failed' AND user_id IS NOT NULL AND ts > %s GROUP BY user_id HAVING count(*) >= 3", (now - timedelta(minutes=15),)).fetchall():
        out.append({"kind": "security", "target": r["user_id"], "key": f"sec|fail|{r['user_id']}|{bucket}", "payload": {"sub": "failed", "count": r["n"]}, "urgent": True})
    n = conn.execute("SELECT count(*) AS n FROM audit_log WHERE event = 'login_blocked' AND ts > %s", (now - timedelta(minutes=15),)).fetchone()["n"]
    if n >= 5:
        out.append({"kind": "admin", "target": "admins", "key": f"adm|blocked|{bucket}", "payload": {"sub": "blocked", "count": n}, "urgent": False})
    return out


# ---------- who wants what ----------
def team_matches(name, team):
    n, t = fold(name), fold(team)
    if not n or not t:
        return False
    if n == t:
        return True
    if n.startswith(t + " "):
        rest = n[len(t) + 1:].split()
        return not all(w in TEAM_SUFFIXES for w in rest)  # "Arsenal" is not "Arsenal Women" unless you said so
    return False


def near_ok(near, p):
    if not near:
        return True
    return km_between(near["lat"], near["lon"], p.get("lat", 0), p.get("lon", 0)) <= near.get("radius_km", 500)


def wants(kind, params, cand):
    p = cand["payload"]
    if kind == "quake":
        return p["mag"] >= params["min_mag"] and near_ok(params.get("near"), p)
    if kind == "hazard":
        return p.get("category") in params["categories"] and near_ok(params.get("near"), p)
    if kind == "match":
        flag = {"kickoff": "kickoff", "goal": "goals", "fulltime": "fulltime"}[p["sub"]]
        return params.get(flag, False) and any(team_matches(p.get("home"), t) or team_matches(p.get("away"), t) for t in params["teams"])
    if kind == "squawk":
        return p["code"] in params["codes"]
    if kind == "security":
        return params.get("new_address" if p.get("sub") == "newip" else "failed", False)
    if kind == "admin":
        return params.get("registrations" if p.get("sub") == "registration" else "blocked", False)
    return False


def rule_kind_of(cand_kind):
    return "football" if cand_kind == "match" else cand_kind


def load_users(conn):
    """Everyone who could receive something: a linked, active Telegram chat, and their rules and settings."""
    users = {}
    for r in conn.execute("SELECT t.user_id, t.chat_id, u.role, u.email FROM alert_telegram t JOIN users u ON u.id = t.user_id WHERE t.active AND u.status IN ('approved', 'active')").fetchall():
        users[r["user_id"]] = {"id": r["user_id"], "chat_id": r["chat_id"], "role": r["role"], "email": r["email"], "rules": {}, "settings": dict(DEFAULT_SETTINGS), "paused_until": None}
    if not users:
        return users
    ids = list(users)
    for r in conn.execute("SELECT * FROM alert_rules WHERE user_id = ANY(%s)", (ids,)).fetchall():
        users[r["user_id"]]["rules"][r["kind"]] = r
    for r in conn.execute("SELECT * FROM alert_settings WHERE user_id = ANY(%s)", (ids,)).fetchall():
        users[r["user_id"]]["settings"] = {k: r[k] for k in DEFAULT_SETTINGS}
        users[r["user_id"]]["paused_until"] = r["paused_until"]
    return users


def add_delivery(conn, user_id, rule_kind, key, payload, urgent):
    row = conn.execute("INSERT INTO alert_deliveries (user_id, rule_kind, dedupe_key, payload, urgent) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_id, dedupe_key) DO NOTHING RETURNING id",
                       (user_id, rule_kind, key, Jsonb(payload), urgent)).fetchone()
    return bool(row)


def route_candidates(conn, users, cands):
    """Turn newly detected things into pending alerts for the people whose rules want them."""
    made = 0
    for c in cands:
        rk = rule_kind_of(c["kind"])
        for u in users.values():
            rule = u["rules"].get(rk)
            if not rule or not rule["enabled"]:
                continue
            if c.get("target") not in (None, u["id"], "admins"):
                continue
            if c.get("target") == "admins" and u["role"] not in ("owner", "admin"):
                continue
            if RULES[rk]["admin"] and u["role"] not in ("owner", "admin"):
                continue
            if wants(c["kind"], rule["params"], c):
                made += add_delivery(conn, u["id"], rk, c["key"], c["payload"], c["urgent"])
    return made


def eval_moves(conn, users, now):
    """Price, index and crypto rules: alert when a move first crosses the user's threshold, and again only if it grows to the next step."""
    made = 0
    today = now.strftime("%Y-%m-%d")
    for u in users.values():
        for rk in ("price", "index", "crypto"):
            rule = u["rules"].get(rk)
            if not rule or not rule["enabled"]:
                continue
            params = rule["params"]
            t = float(params["threshold"])
            if rk == "price":
                symbols = [r["symbol"] for r in conn.execute("SELECT symbol FROM market_watch WHERE user_id = %s", (u["id"],)).fetchall()]
            else:
                symbols = params["indices"] if rk == "index" else params["coins"]
            if not symbols:
                continue
            rows = conn.execute("SELECT symbol, name, price, change_pct, currency, fetched_at FROM quotes WHERE symbol = ANY(%s) AND price IS NOT NULL AND change_pct IS NOT NULL AND fetched_at > %s", (symbols, now - timedelta(hours=3))).fetchall()
            for q in rows:
                chg = float(q["change_pct"])
                level = int(abs(chg) // t) * (1 if chg >= 0 else -1)
                key = f"lvl|{u['id']}|{rk}|{q['symbol']}"
                prev = get_state(conn, key)
                if prev is None:
                    set_state(conn, key, {"level": level, "day": today})  # the starting point; never announce what was already true
                    continue
                stored = prev["level"]
                if prev["day"] != today:
                    if rk == "crypto":
                        set_state(conn, key, {"level": level, "day": today})  # crypto's 24 hours roll on, so a new date changes nothing
                        continue
                    stored = 0  # shares and indices start each day afresh
                if abs(level) > abs(stored) or (level and stored and (level > 0) != (stored > 0)):
                    p = {"symbol": q["symbol"], "name": q["name"], "chg": chg, "price": q["price"], "currency": q["currency"], "level": level}
                    if add_delivery(conn, u["id"], rk, f"{rk}|{q['symbol']}|{today}|{level}", p, False):
                        made += 1
                    set_state(conn, key, {"level": level, "day": today})
                elif abs(chg) + 0.5 * t < abs(stored) * t:
                    # it has fallen well back, so it may alert again if it climbs again (the half step stops it flickering around the line)
                    set_state(conn, key, {"level": int((abs(chg) + 0.5 * t) // t) * (1 if chg >= 0 else -1), "day": today})
                elif prev["day"] != today:
                    set_state(conn, key, {"level": stored, "day": today})
    return made


# ---------- delivering, with all the care that keeps it from being spammy ----------
class RateLimited(Exception):
    def __init__(self, seconds):
        super().__init__(f"Telegram asked us to wait {seconds} s")
        self.seconds = seconds


def compose_kind(rule_kind):
    return "match" if rule_kind == "football" else rule_kind


def _mark(conn, row, status, reason=None, now=None):
    conn.execute("UPDATE alert_deliveries SET status = %s, reason = %s, sent_at = CASE WHEN %s = 'sent' THEN %s ELSE sent_at END WHERE id = %s", (status, reason, status, now or datetime.now(timezone.utc), row["id"]))


def _queue(conn, row, until):
    conn.execute("UPDATE alert_deliveries SET status = 'queued', deliver_after = %s WHERE id = %s", (until, row["id"]))


def _buttons(rule_kind=None):
    row = []
    if rule_kind in RULES:
        row.append({"text": "\U0001F515 Mute this type for 24 h", "callback_data": f"m:{rule_kind}"})
    row.append({"text": "\u23F8 Pause all for 1 h", "callback_data": "p:1"})
    return [row]


def _after_error(conn, rows, err, uid, now):
    if err.code == 429:
        raise RateLimited(err.retry_after or 5)
    if err.code in (400, 403) and ("blocked" in err.description.lower() or "chat not found" in err.description.lower() or "deactivated" in err.description.lower()):
        conn.execute("UPDATE alert_telegram SET active = false WHERE user_id = %s", (uid,))
        for r in rows:
            _mark(conn, r, "failed", "you blocked the bot or deleted the chat", now)
        return
    for r in rows:
        n = r["attempts"] + 1
        if n >= 3:
            _mark(conn, r, "failed", "Telegram could not be reached", now)
        else:
            conn.execute("UPDATE alert_deliveries SET attempts = %s, status = 'pending', deliver_after = %s WHERE id = %s", (n, now + timedelta(seconds=60 * n), r["id"]))


def process_user(conn, u, now, send):
    """Decide, for one person, which waiting alerts go now, which wait, and which are dropped; then send them. Returns how many alerts were sent."""
    uid, st = u["id"], u["settings"]
    rows = conn.execute("SELECT * FROM alert_deliveries WHERE user_id = %s AND status IN ('pending', 'queued') AND (deliver_after IS NULL OR deliver_after <= %s) ORDER BY created_at, id", (uid, now)).fetchall()
    if not rows:
        return 0
    paused = bool(u["paused_until"] and u["paused_until"] > now)
    quiet = in_quiet(st, now)
    ready = []
    for d in rows:
        kind = d["rule_kind"]
        is_test = kind == "test"
        rule = u["rules"].get(kind)
        if not is_test:
            if not rule or not rule["enabled"]:
                _mark(conn, d, "suppressed", "that alert type was switched off", now)
                continue
            if rule["muted_until"] and rule["muted_until"] > now:
                _mark(conn, d, "suppressed", "muted", now)
                continue
            if paused:
                _queue(conn, d, u["paused_until"])
                continue
            if quiet and not d["urgent"]:
                _queue(conn, d, next_local(st, now, _parse_hhmm(st["quiet_end"])))
                continue
            if st["mode"] == "digest" and d["status"] != "queued" and not d["urgent"]:
                _queue(conn, d, next_local(st, now, dtime(st["digest_hour"])))
                continue
        ready.append(d)
    used = conn.execute("SELECT count(*) AS n FROM alert_deliveries WHERE user_id = %s AND status = 'sent' AND rule_kind <> 'test' AND sent_at > %s", (uid, now - timedelta(hours=24))).fetchone()["n"]
    cap, kept, over = st["daily_cap"], [], 0
    for d in ready:
        if d["rule_kind"] == "test":
            kept.append(d)
        elif used < (cap + URGENT_EXTRA if d["urgent"] else cap):
            kept.append(d)
            used += 1
        else:
            _mark(conn, d, "suppressed", "daily limit reached", now)
            over += 1
    sent = 0
    if over:
        day = now.strftime("%Y-%m-%d")
        if not get_state(conn, f"capnotice|{uid}|{day}"):
            set_state(conn, f"capnotice|{uid}|{day}", True)
            try:
                send(u["chat_id"], f"\U0001F6D1 <b>Daily alert limit reached</b> ({cap}). I will hold back the rest until the count drops. Urgent safety alerts still come through. You can change the limit in XYRON, under Alerts.", None)
            except tgbot.TelegramError as e:
                if e.code == 429:
                    raise RateLimited(e.retry_after or 5)
    if not kept:
        return 0
    flush = any(d["status"] == "queued" for d in kept)
    try:
        if len(kept) <= GROUP_AFTER and not flush:
            for d in kept:
                text, _line = compose(compose_kind(d["rule_kind"]), d["payload"])
                try:
                    send(u["chat_id"], text, None if d["rule_kind"] == "test" else _buttons(d["rule_kind"]))
                except tgbot.TelegramError as e:
                    _after_error(conn, [d], e, uid, now)
                    if e.code in (400, 403):
                        break
                    continue
                _mark(conn, d, "sent", None, now)
                sent += 1
        else:
            title = "Your XYRON summary" if st["mode"] == "digest" and flush else "While you were away" if flush else "New alerts"
            for i in range(0, len(kept), GROUP_LINES):
                chunk = kept[i:i + GROUP_LINES]
                lines = [f"\u2022 {compose(compose_kind(d['rule_kind']), d['payload'])[1]}" for d in chunk]
                head = f"\U0001F514 <b>{title}</b> ({len(kept)})" + ("" if i == 0 else " continued")
                try:
                    send(u["chat_id"], head + "\n" + "\n".join(lines), [[{"text": "\u23F8 Pause all for 1 h", "callback_data": "p:1"}]])
                except tgbot.TelegramError as e:
                    _after_error(conn, chunk, e, uid, now)
                    if e.code in (400, 403):
                        break
                    continue
                for d in chunk:
                    _mark(conn, d, "sent", None, now)
                sent += len(chunk)
    except RateLimited:
        raise
    return sent


def run_cycle(now=None, send=None):
    """One pass: spot new things, work out who wants them, and deliver what is due."""
    now = now or datetime.now(timezone.utc)
    send = send or tgbot.send_message
    stats = {"new": 0, "queued": 0, "sent": 0}
    with get_conn() as conn:
        users = load_users(conn)
        cands = []
        for name, check in (("earthquake", lambda: detect_quakes(conn, now)), ("hazard", lambda: detect_hazards(conn, now)), ("football", lambda: detect_matches(conn, now)), ("aircraft", lambda: detect_squawks(now))):
            try:
                with conn.transaction():  # a savepoint: if this check fails, the others (and the delivery below) carry on
                    cands += check()
            except Exception:
                log.exception("alerts: the %s check failed; the other checks carry on", name)
        fresh = []
        if cands:
            # only things never seen before count as news, so enabling an alert never replays what is already going on (one query for all of them)
            by_key = {c["key"]: c for c in cands}
            added = {r["key"] for r in conn.execute("INSERT INTO alert_events (key, kind) SELECT k, kd FROM unnest(%s::text[], %s::text[]) AS t(k, kd) ON CONFLICT (key) DO NOTHING RETURNING key",
                                                    (list(by_key), [c["kind"] for c in by_key.values()])).fetchall()}
            fresh = [by_key[k] for k in by_key if k in added]
            conn.execute("UPDATE alert_events SET seen_at = %s WHERE key = ANY(%s) AND seen_at < %s", (now, list(by_key), now - timedelta(hours=1)))  # still being reported, so it is not forgotten (a drought can last for months)
        try:
            with conn.transaction():
                fresh += detect_security(conn, now)
        except Exception:
            log.exception("alerts: the security check failed; the other checks carry on")
        stats["new"] = len(fresh)
        if users:
            stats["queued"] = route_candidates(conn, users, fresh) + eval_moves(conn, users, now)
        conn.execute("UPDATE alert_deliveries SET status = 'suppressed', reason = 'Telegram is not connected' WHERE status IN ('pending', 'queued') AND user_id NOT IN (SELECT user_id FROM alert_telegram WHERE active)")
        until = get_state(conn, "tg_backoff_until")
        if until and datetime.fromisoformat(until) > now:
            return stats
        for u in users.values():
            try:
                stats["sent"] += process_user(conn, u, now, send)
            except RateLimited as e:
                set_state(conn, "tg_backoff_until", (now + timedelta(seconds=e.seconds)).isoformat())
                log.warning("alerts: Telegram asked us to slow down for %s s", e.seconds)
                break
            except Exception:
                log.exception("alerts: delivery for user %s failed", u["id"])
        last = get_state(conn, "alerts_cleanup")
        if not last or datetime.fromisoformat(last) < now - timedelta(hours=1):
            set_state(conn, "alerts_cleanup", now.isoformat())
            conn.execute("DELETE FROM alert_events WHERE seen_at < %s", (now - timedelta(days=EVENT_KEEP_DAYS),))
            conn.execute("DELETE FROM alert_deliveries WHERE created_at < %s", (now - timedelta(days=30),))
            conn.execute("DELETE FROM alert_state WHERE key LIKE 'm|%%' AND updated_at < %s", (now - timedelta(days=STATE_KEEP_DAYS),))
            conn.execute("DELETE FROM alert_link_tokens WHERE expires_at < %s", (now - timedelta(days=1),))
    return stats


# ---------- linking a Telegram chat to an account, and the bot's commands ----------
def _sha(token):
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def create_link(conn, user_id, now=None):
    now = now or datetime.now(timezone.utc)
    n = conn.execute("SELECT count(*) AS n FROM alert_link_tokens WHERE user_id = %s AND created_at > %s", (user_id, now - timedelta(hours=1))).fetchone()["n"]
    if n >= 5:
        raise ValueError("Too many connection links were made in the last hour. Try again later.")
    import secrets
    token = secrets.token_urlsafe(24)
    conn.execute("INSERT INTO alert_link_tokens (token_hash, user_id, expires_at, created_at) VALUES (%s,%s,%s,%s)", (_sha(token), user_id, now + timedelta(minutes=LINK_MINUTES), now))
    return token


def link_chat(conn, token, chat_id, name, now=None):
    """Returns the account's email if the link worked, otherwise None."""
    now = now or datetime.now(timezone.utc)
    row = conn.execute("UPDATE alert_link_tokens SET used_at = %s WHERE token_hash = %s AND used_at IS NULL AND expires_at > %s RETURNING user_id", (now, _sha(token), now)).fetchone()
    if not row:
        return None
    user = conn.execute("SELECT id, email FROM users WHERE id = %s AND status IN ('approved', 'active')", (row["user_id"],)).fetchone()
    if not user:
        return None
    conn.execute("DELETE FROM alert_telegram WHERE chat_id = %s OR user_id = %s", (chat_id, user["id"]))  # one chat belongs to one account, and one account has one chat
    conn.execute("INSERT INTO alert_telegram (user_id, chat_id, name, active, linked_at) VALUES (%s,%s,%s,true,%s)", (user["id"], chat_id, (name or "")[:60], now))
    return user["email"]


def describe_rule(kind, p):
    near = f" within {p['near']['radius_km']} km of {p['near']['name']}" if p.get("near") else ""
    if kind == "quake":
        return f"Earthquakes M{p['min_mag']:g}+{near}"
    if kind == "hazard":
        return "Hazards: " + ", ".join(HAZARD_CATS[c] for c in p["categories"]) + near
    if kind == "price":
        return f"Watchlist moves of {p['threshold']:g}%+"
    if kind == "index":
        return f"Indices ({', '.join(dict(INDEX_CHOICES)[i] for i in p['indices'])}) {p['threshold']:g}%+"
    if kind == "crypto":
        return f"Crypto ({', '.join(p['coins'])}) {p['threshold']:g}%+"
    if kind == "football":
        what = [w for w, f in (("kick-off", "kickoff"), ("goals", "goals"), ("full time", "fulltime")) if p.get(f)]
        return "Football: " + (", ".join(p["teams"]) or "no teams yet") + f" ({', '.join(what)})"
    if kind == "squawk":
        return "Aircraft squawking " + ", ".join(p["codes"])
    return RULES[kind]["label"]


HELP = ("<b>XYRON alerts</b>\nI send the alerts you switch on in XYRON, under Alerts.\n\n/status \u2013 what is on\n/pause [hours] \u2013 pause everything (default 1 hour)\n/resume \u2013 start again\n"
        "/mute \u2013 mute one type for 24 hours\n/unlink \u2013 disconnect this chat\n/help \u2013 this message")
_chat_hits = {}


def _limited(chat_id, now_ts):
    hits = [t for t in _chat_hits.get(chat_id, []) if now_ts - t < 60]
    hits.append(now_ts)
    _chat_hits[chat_id] = hits
    return len(hits) > 20


def _settings_row(conn, uid):
    conn.execute("INSERT INTO alert_settings (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (uid,))


def handle_update(update, send=None, answer=None, now=None):
    """One thing someone sent the bot."""
    send = send or tgbot.send_message
    answer = answer or tgbot.answer_callback
    now = now or datetime.now(timezone.utc)
    if "callback_query" in update:
        return _handle_button(update["callback_query"], send, answer, now)
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    text = (msg.get("text") or "").strip()
    if chat.get("type") != "private" or not chat.get("id") or not text:
        return  # groups and anything that is not text are ignored
    chat_id = chat["id"]
    if _limited(chat_id, now.timestamp()):
        return
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip()
    with get_conn() as conn:
        linked = conn.execute("SELECT t.user_id, u.email FROM alert_telegram t JOIN users u ON u.id = t.user_id WHERE t.chat_id = %s AND t.active", (chat_id,)).fetchone()
        if cmd == "/start" and arg:
            email = link_chat(conn, arg[:80], chat_id, (msg.get("from") or {}).get("first_name"), now)
            if email:
                return send(chat_id, f"\u2705 <b>Connected.</b> This chat now receives alerts for <b>{tgbot.esc(email)}</b>.\n\nNothing is switched on yet: open XYRON, go to Alerts, and choose what you want to hear about. Send /help to see what I can do.", None)
            return send(chat_id, "That link has expired or was already used. Open XYRON, go to Alerts, and press Connect Telegram for a fresh one.", None)
        if cmd in ("/start", "/help") or not linked:
            if not linked and cmd not in ("/start", "/help"):
                return send(chat_id, "This chat is not connected to an XYRON account yet. Open XYRON, go to Alerts, and press Connect Telegram.", None)
            return send(chat_id, HELP if linked else "Hello. I send alerts from XYRON. To connect this chat, open XYRON, go to Alerts, and press Connect Telegram.", None)
        uid = linked["user_id"]
        if cmd == "/status":
            return send(chat_id, _status_text(conn, uid, linked["email"], now), None)
        if cmd == "/pause":
            try:
                hours = max(1, min(72, int(float(arg)))) if arg else 1
            except ValueError:
                return send(chat_id, "Use /pause 3 to pause for 3 hours (1 to 72).", None)
            _settings_row(conn, uid)
            conn.execute("UPDATE alert_settings SET paused_until = %s WHERE user_id = %s", (now + timedelta(hours=hours), uid))
            return send(chat_id, f"\u23F8 Paused for {hours} hour{'s' if hours != 1 else ''}. Alerts are held, not lost. /resume starts them sooner.", None)
        if cmd == "/resume":
            _settings_row(conn, uid)
            conn.execute("UPDATE alert_settings SET paused_until = NULL WHERE user_id = %s", (uid,))
            return send(chat_id, "\u25B6\uFE0F Alerts are on again.", None)
        if cmd == "/mute":
            kinds = [r["kind"] for r in conn.execute("SELECT kind FROM alert_rules WHERE user_id = %s AND enabled ORDER BY kind", (uid,)).fetchall()]
            if not kinds:
                return send(chat_id, "You have no alert types switched on.", None)
            return send(chat_id, "Mute which type for 24 hours?", [[{"text": RULES[k]["label"], "callback_data": f"m:{k}"}] for k in kinds if k in RULES])
        if cmd == "/unlink":
            return send(chat_id, "Disconnect this chat from XYRON? You will stop receiving alerts here.", [[{"text": "Yes, disconnect", "callback_data": "u:yes"}, {"text": "No, keep it", "callback_data": "u:no"}]])
        return send(chat_id, "I did not understand that. Send /help to see what I can do.", None)


def _status_text(conn, uid, email, now):
    rules = conn.execute("SELECT kind, params, muted_until FROM alert_rules WHERE user_id = %s AND enabled ORDER BY kind", (uid,)).fetchall()
    s = conn.execute("SELECT * FROM alert_settings WHERE user_id = %s", (uid,)).fetchone()
    st = {k: s[k] for k in DEFAULT_SETTINGS} if s else dict(DEFAULT_SETTINGS)
    sent = conn.execute("SELECT count(*) AS n FROM alert_deliveries WHERE user_id = %s AND status = 'sent' AND rule_kind <> 'test' AND sent_at > %s", (uid, now - timedelta(hours=24))).fetchone()["n"]
    paused = s and s["paused_until"] and s["paused_until"] > now
    lines = [f"<b>XYRON alerts</b> \u00b7 {tgbot.esc(email)}", "Status: " + (f"paused until {s['paused_until'].astimezone(tz_of(st['tz'])):%H:%M}" if paused else "on")]
    lines.append("Switched on:" + ("" if rules else " nothing yet"))
    for r in rules:
        muted = " (muted)" if r["muted_until"] and r["muted_until"] > now else ""
        lines.append(f"\u2022 {tgbot.esc(describe_rule(r['kind'], r['params']))}{muted}")
    lines.append(f"Sent in the last 24 hours: {sent} of {st['daily_cap']}")
    lines.append(f"Quiet hours: {st['quiet_start']}\u2013{st['quiet_end']} ({st['tz']})" if st["quiet_start"] else "Quiet hours: none")
    lines.append(f"Delivery: daily summary at {st['digest_hour']:02d}:00" if st["mode"] == "digest" else "Delivery: instant")
    return "\n".join(lines)


def _handle_button(cb, send, answer, now):
    chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
    data = str(cb.get("data") or "")
    if not chat_id:
        return
    with get_conn() as conn:
        linked = conn.execute("SELECT user_id FROM alert_telegram WHERE chat_id = %s AND active", (chat_id,)).fetchone()
        if not linked:
            return answer(cb.get("id"), "This chat is not connected.")
        uid = linked["user_id"]
        if data.startswith("m:") and data[2:] in RULES:
            conn.execute("UPDATE alert_rules SET muted_until = %s WHERE user_id = %s AND kind = %s", (now + timedelta(hours=24), uid, data[2:]))
            return answer(cb.get("id"), f"{RULES[data[2:]]['label']} muted for 24 hours.")
        if data.startswith("p:") and data[2:].isdigit():
            hours = max(1, min(72, int(data[2:])))
            _settings_row(conn, uid)
            conn.execute("UPDATE alert_settings SET paused_until = %s WHERE user_id = %s", (now + timedelta(hours=hours), uid))
            return answer(cb.get("id"), f"Paused for {hours} hour{'s' if hours != 1 else ''}.")
        if data == "u:yes":
            conn.execute("DELETE FROM alert_telegram WHERE user_id = %s", (uid,))
            answer(cb.get("id"), "Disconnected.")
            return send(chat_id, "Disconnected. You will not receive alerts here any more.", None)
        if data == "u:no":
            return answer(cb.get("id"), "Kept.")
    answer(cb.get("id"), "")


def load_offset():
    with get_conn() as conn:
        return int(get_state(conn, "tg_offset", 0) or 0)


def save_offset(offset):
    with get_conn() as conn:
        set_state(conn, "tg_offset", offset)


# ---------- the background loops ----------
async def engine_loop():
    import asyncio
    while True:
        try:
            stats = await asyncio.to_thread(run_cycle)
            if stats["sent"] or stats["queued"]:
                log.info("alerts: %d new, %d queued, %d sent", stats["new"], stats["queued"], stats["sent"])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("alerts: cycle failed")
        await asyncio.sleep(CYCLE)


async def ingest_loop():
    import asyncio
    await asyncio.sleep(75)
    try:
        await asyncio.to_thread(init_schema)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("alerts setup failed")
        return
    if not tgbot.configured():
        log.warning("alerts: no TELEGRAM_BOT_TOKEN, so alerts cannot be delivered")
    await asyncio.gather(engine_loop(), tgbot.poll_loop(handle_update, load_offset, save_offset))
