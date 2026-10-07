"""The screens' side of alerts: what a user sees and changes (connect Telegram, choose rules, quiet hours)."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import alerts as A
from . import tgbot
from .db import get_conn
from .deps import current_user

log = logging.getLogger("xyron.alerts")
router = APIRouter(prefix="/api/alerts")


class RuleIn(BaseModel):
    enabled: bool
    params: dict | None = None


class SettingsIn(BaseModel):
    tz: str | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    daily_cap: int | None = None
    mode: str | None = None
    digest_hour: int | None = None


class PauseIn(BaseModel):
    hours: int


def is_admin(user):
    return user["role"] in ("owner", "admin")


def _iso(t):
    return t.isoformat() if t else None


def _telegram(conn, uid):
    r = conn.execute("SELECT name, active, linked_at FROM alert_telegram WHERE user_id = %s", (uid,)).fetchone()
    return {"linked": bool(r and r["active"]), "name": r["name"] if r else None, "since": _iso(r["linked_at"]) if r else None, "blocked": bool(r and not r["active"])}


def _text_of(row):
    return A.plain(A.compose(A.compose_kind(row["rule_kind"]), row["payload"])[1])


@router.get("")
def overview(user=Depends(current_user)):
    now = datetime.now(timezone.utc)
    uid = user["id"]
    with get_conn() as conn:
        rules = {}
        for kind, meta in A.RULES.items():
            if meta["admin"] and not is_admin(user):
                continue
            row = conn.execute("SELECT enabled, params, muted_until FROM alert_rules WHERE user_id = %s AND kind = %s", (uid, kind)).fetchone()
            rules[kind] = {"enabled": bool(row and row["enabled"]), "params": {**A.DEFAULT_PARAMS[kind], **((row or {}).get("params") or {})}, "muted_until": _iso(row["muted_until"]) if row and row["muted_until"] and row["muted_until"] > now else None}
        s = conn.execute("SELECT * FROM alert_settings WHERE user_id = %s", (uid,)).fetchone()
        settings = {k: s[k] for k in A.DEFAULT_SETTINGS} if s else dict(A.DEFAULT_SETTINGS)
        paused = s["paused_until"] if s and s["paused_until"] and s["paused_until"] > now else None
        recent = conn.execute("SELECT id, rule_kind, payload, status, reason, created_at, sent_at FROM alert_deliveries WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT 25", (uid,)).fetchall()
        sent24 = conn.execute("SELECT count(*) AS n FROM alert_deliveries WHERE user_id = %s AND status = 'sent' AND rule_kind <> 'test' AND sent_at > %s", (uid, now - timedelta(hours=24))).fetchone()["n"]
        watch = [r["symbol"] for r in conn.execute("SELECT symbol FROM market_watch WHERE user_id = %s ORDER BY added_at", (uid,)).fetchall()]
        tg = _telegram(conn, uid)
    return {
        "configured": tgbot.configured(), "bot": tgbot.bot_username() or None, "telegram": tg, "settings": settings, "paused_until": _iso(paused), "sent_24h": sent24, "watchlist": watch,
        "rules": rules,
        "catalog": {"kinds": [{"id": k, "label": m["label"], "blurb": m["blurb"], "admin": m["admin"]} for k, m in A.RULES.items() if not m["admin"] or is_admin(user)],
                    "hazard_categories": [{"id": k, "label": v} for k, v in A.HAZARD_CATS.items()], "indices": [{"symbol": s, "name": n} for s, n in A.INDEX_CHOICES],
                    "coins": A.COIN_CHOICES, "squawks": [{"code": c, "meaning": m} for c, m in A.SQUAWKS.items()]},
        "recent": [{"id": r["id"], "kind": r["rule_kind"], "text": _text_of(r), "status": r["status"], "reason": r["reason"], "at": _iso(r["created_at"]), "sent_at": _iso(r["sent_at"])} for r in recent],
    }


@router.get("/telegram")
def telegram_status(user=Depends(current_user)):
    with get_conn() as conn:
        return _telegram(conn, user["id"])


@router.post("/telegram/link")
def telegram_link(user=Depends(current_user)):
    if not tgbot.configured() or not tgbot.bot_username():
        raise HTTPException(503, "Telegram is not set up on this server yet.")
    try:
        with get_conn() as conn:
            token = A.create_link(conn, user["id"])
    except ValueError as e:
        raise HTTPException(429, str(e))
    return {"url": f"https://t.me/{tgbot.bot_username()}?start={token}", "expires_in": A.LINK_MINUTES * 60}


@router.delete("/telegram")
def telegram_unlink(user=Depends(current_user)):
    with get_conn() as conn:
        conn.execute("DELETE FROM alert_telegram WHERE user_id = %s", (user["id"],))
    return {"linked": False}


@router.put("/rules/{kind}")
def set_rule(kind: str, body: RuleIn, user=Depends(current_user)):
    if kind not in A.RULES or (A.RULES[kind]["admin"] and not is_admin(user)):
        raise HTTPException(404, "Unknown alert type")
    try:
        params = A.validate_params(kind, body.params or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    now = datetime.now(timezone.utc)
    uid = user["id"]
    with get_conn() as conn:
        prev = conn.execute("SELECT enabled, params, enabled_at FROM alert_rules WHERE user_id = %s AND kind = %s", (uid, kind)).fetchone()
        was_on = bool(prev and prev["enabled"])
        enabled_at = now if body.enabled and not was_on else (prev["enabled_at"] if prev else None)
        from psycopg.types.json import Jsonb
        conn.execute("INSERT INTO alert_rules (user_id, kind, enabled, params, enabled_at, updated_at) VALUES (%s,%s,%s,%s,%s,now()) "
                     "ON CONFLICT (user_id, kind) DO UPDATE SET enabled = EXCLUDED.enabled, params = EXCLUDED.params, enabled_at = EXCLUDED.enabled_at, updated_at = now(), "
                     "muted_until = CASE WHEN EXCLUDED.enabled AND NOT alert_rules.enabled THEN NULL ELSE alert_rules.muted_until END",
                     (uid, kind, body.enabled, Jsonb(params), enabled_at))
        if not was_on or (prev and prev["params"] != params):
            conn.execute("DELETE FROM alert_state WHERE key LIKE %s", (f"lvl|{uid}|{kind}|%",))  # a changed threshold starts from the situation as it is now
    return {"kind": kind, "enabled": body.enabled, "params": params}


@router.put("/settings")
def set_settings(body: SettingsIn, user=Depends(current_user)):
    uid = user["id"]
    with get_conn() as conn:
        s = conn.execute("SELECT * FROM alert_settings WHERE user_id = %s", (uid,)).fetchone()
        merged = {k: s[k] for k in A.DEFAULT_SETTINGS} if s else dict(A.DEFAULT_SETTINGS)
        merged.update({k: v for k, v in body.model_dump().items() if k in body.model_fields_set})
        try:
            clean = A.validate_settings(merged)
        except ValueError as e:
            raise HTTPException(400, str(e))
        conn.execute("INSERT INTO alert_settings (user_id, tz, quiet_start, quiet_end, daily_cap, mode, digest_hour, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,now()) "
                     "ON CONFLICT (user_id) DO UPDATE SET tz = EXCLUDED.tz, quiet_start = EXCLUDED.quiet_start, quiet_end = EXCLUDED.quiet_end, daily_cap = EXCLUDED.daily_cap, "
                     "mode = EXCLUDED.mode, digest_hour = EXCLUDED.digest_hour, updated_at = now()", (uid, clean["tz"], clean["quiet_start"], clean["quiet_end"], clean["daily_cap"], clean["mode"], clean["digest_hour"]))
    return clean


@router.post("/pause")
def pause(body: PauseIn, user=Depends(current_user)):
    if not 0 <= body.hours <= 72:
        raise HTTPException(400, "Pause for 0 to 72 hours (0 resumes)")
    until = datetime.now(timezone.utc) + timedelta(hours=body.hours) if body.hours else None
    with get_conn() as conn:
        conn.execute("INSERT INTO alert_settings (user_id, paused_until) VALUES (%s,%s) ON CONFLICT (user_id) DO UPDATE SET paused_until = EXCLUDED.paused_until", (user["id"], until))
    return {"paused_until": _iso(until)}


@router.post("/test")
def test_alert(user=Depends(current_user)):
    now = datetime.now(timezone.utc)
    uid = user["id"]
    with get_conn() as conn:
        tg = conn.execute("SELECT chat_id, active FROM alert_telegram WHERE user_id = %s", (uid,)).fetchone()
        if not tg or not tg["active"]:
            raise HTTPException(400, "Connect Telegram first.")
        n = conn.execute("SELECT count(*) AS n FROM alert_deliveries WHERE user_id = %s AND rule_kind = 'test' AND created_at > %s", (uid, now - timedelta(hours=1))).fetchone()["n"]
        if n >= 3:
            raise HTTPException(429, "Three test alerts an hour is the limit.")
        A.add_delivery(conn, uid, "test", f"test|{uid}|{now.timestamp()}", {}, True)
        users = A.load_users(conn)
        if uid not in users:
            raise HTTPException(400, "Connect Telegram first.")
        try:
            sent = A.process_user(conn, users[uid], now, tgbot.send_message)
        except A.RateLimited:
            raise HTTPException(429, "Telegram asked us to slow down. Try again in a minute.")
    return {"sent": sent > 0}
