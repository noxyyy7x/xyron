"""Account recovery and security settings.

  - forgot password: an emailed one-hour link, then a new password plus an authenticator code or a recovery code
  - recovery codes: ten single-use codes, shown once and stored only as hashes; they work to sign in and to reset a password
  - changing the password or the authenticator while signed in, and signing out other devices
  - the owner or an admin can reset someone's authenticator; the person gets a one-time setup link by email
Whenever something here changes, every other session is signed out and the person is told by Telegram and email.
"""
import hashlib
import hmac
import logging
import re
import secrets
from html import escape
from pathlib import Path
from urllib.parse import parse_qs

import pyotp
from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field

from . import security as sec
from .accounts import _check, _hash, _target, page
from .config import COOKIE_SECURE, PUBLIC_BASE_URL, SECRET_KEY, SESSION_TTL
from .db import audit, get_conn
from .deps import LOGIN_OK_STATUS, client_ip, current_user, require_role
from .mailer import send_mail

log = logging.getLogger("xyron.recovery")
router = APIRouter()
STATIC = Path(__file__).parent / "static"
COOKIE = "xyron_session"
RESET_MINUTES = 60
TWOFA_HOURS = 24
CODE_COUNT = 10
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no 0/o, 1/l/i: easy to read out or copy by hand
GENERIC_RESET = {"message": "If that address has an account, a reset link has been sent. It works for one hour."}
INVALID_LINK = "This link is invalid or has expired."
NO_STORE = {"Cache-Control": "no-store"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS recovery_codes (
  id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, code_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), used_at TIMESTAMPTZ, UNIQUE (user_id, code_hash)
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_pending_enc TEXT;
"""
_ready = {"done": False}


def ensure_schema():
    if _ready["done"]:
        return
    with get_conn() as conn:
        conn.execute(SCHEMA)
    _ready["done"] = True


# ---------- sessions that can be signed out ----------
def _epoch(uid):
    return int(sec.r.get(f"session_epoch:{uid}") or 0)


def install_sessions():
    """Teach the session code to be signed out in one go. Each person has a counter; a session remembers the counter it was made under."""
    if getattr(sec.create_session, "_epoch_aware", False):
        return
    original_create = sec.create_session

    def create_session(user_id):
        token = original_create(user_id)
        ep = _epoch(user_id)
        if ep:
            sec.r.setex(sec._skey(token), SESSION_TTL, f"{user_id}:{ep}")
        return token

    def session_user_id(token):
        key = sec._skey(token)
        raw = sec.r.get(key)
        if not raw:
            return None
        uid_text, _, ep_text = str(raw).partition(":")
        try:
            uid, ep = int(uid_text), int(ep_text or 0)
        except ValueError:
            return None
        if ep != _epoch(uid):
            sec.r.delete(key)
            return None
        sec.r.expire(key, SESSION_TTL)
        return uid

    create_session._epoch_aware = session_user_id._epoch_aware = True
    sec.create_session, sec.session_user_id = create_session, session_user_id


def revoke_sessions(uid, keep_token=None):
    """Sign the person out everywhere (except the session making the change, if given)."""
    ep = sec.r.incr(f"session_epoch:{uid}")
    if keep_token:
        key = sec._skey(keep_token)
        if sec.r.get(key):
            ttl = sec.r.ttl(key)
            sec.r.setex(key, ttl if ttl and ttl > 0 else SESSION_TTL, f"{uid}:{ep}")
    return ep


install_sessions()


# ---------- recovery codes ----------
def _norm(code):
    return re.sub(r"[^a-z0-9]", "", str(code or "").lower())


def _code_hash(norm):
    key = hashlib.sha256((SECRET_KEY + "|recovery-codes").encode()).digest()
    return hmac.new(key, norm.encode(), hashlib.sha256).hexdigest()


def new_codes(n=CODE_COUNT):
    return ["".join(secrets.choice(ALPHABET) for _ in range(5)) + "-" + "".join(secrets.choice(ALPHABET) for _ in range(5)) for _ in range(n)]


def save_codes(conn, uid, codes):
    conn.execute("DELETE FROM recovery_codes WHERE user_id = %s", (uid,))
    for c in codes:
        conn.execute("INSERT INTO recovery_codes (user_id, code_hash) VALUES (%s,%s)", (uid, _code_hash(_norm(c))))


def use_recovery_code(conn, uid, code):
    norm = _norm(code)
    if len(norm) != 10 or any(ch not in ALPHABET for ch in norm):
        return False
    return bool(conn.execute("UPDATE recovery_codes SET used_at = now() WHERE user_id = %s AND code_hash = %s AND used_at IS NULL RETURNING id", (uid, _code_hash(norm))).fetchone())


def codes_left(conn, uid):
    return conn.execute("SELECT count(*) AS n FROM recovery_codes WHERE user_id = %s AND used_at IS NULL", (uid,)).fetchone()["n"]


def second_factor(conn, user, code):
    """An authenticator code (six digits) or a recovery code. Returns 'totp', 'recovery' or None."""
    code = str(code or "").strip()
    if re.fullmatch(r"\d{6}", code):
        return "totp" if sec.verify_totp(user["id"], sec.decrypt_secret(user["totp_secret_enc"]), code) else None
    return "recovery" if use_recovery_code(conn, user["id"], code) else None


# ---------- telling people ----------
def _telegram(uid, html_text):
    try:
        from . import tgbot
        if not tgbot.configured():
            return
        with get_conn() as conn:
            row = conn.execute("SELECT chat_id FROM alert_telegram WHERE user_id = %s AND active", (uid,)).fetchone()
        if row:
            tgbot.send_message(row["chat_id"], html_text)
    except Exception:
        log.debug("telegram notice not sent", exc_info=True)


def tell(bg, user, subject, text, tg_text=None):
    """Email and (if connected) Telegram: something about your account's security changed."""
    bg.add_task(send_mail, user["email"], subject, text)
    bg.add_task(_telegram, user["id"], f"\U0001F510 <b>{escape(subject)}</b>\n{escape(tg_text or text)}")


def private_json(data, status=200):
    """Answers that carry secrets (codes, keys) must never be kept by a browser or a proxy."""
    return JSONResponse(data, status_code=status, headers=NO_STORE)


def _mask(email):
    local, _, domain = email.partition("@")
    return (local[:1] + "\u2022" * max(1, min(6, len(local) - 1)) if local else "") + "@" + domain


def _limited(key, limit, window, count=True):
    if sec.over_limit(key, limit):
        return True
    if count:
        sec.hit(key, window)
    return False


# ---------- forgot password ----------
@router.get("/reset", include_in_schema=False)
def reset_page():
    return FileResponse(STATIC / "reset.html", headers=NO_STORE)


class ResetRequestIn(BaseModel):
    email: EmailStr


@router.post("/auth/reset/request", status_code=202)
def reset_request(body: ResetRequestIn, request: Request, bg: BackgroundTasks):
    ensure_schema()
    ip, email = client_ip(request), body.email.lower()
    ip_key, mail_key = f"rl:reset:ip:{ip}", f"rl:reset:mail:{email}"
    blocked = sec.over_limit(ip_key, 5) or sec.over_limit(mail_key, 3)
    sec.hit(ip_key, 3600)
    sec.hit(mail_key, 3600)
    if blocked:
        raise HTTPException(429, "Too many attempts. Try again later.")
    with get_conn() as conn:
        user = conn.execute("SELECT id, email, status, email_verified FROM users WHERE email = %s", (email,)).fetchone()
        if user and user["status"] in LOGIN_OK_STATUS and user["email_verified"]:
            conn.execute("UPDATE email_tokens SET used_at = now() WHERE user_id = %s AND purpose = 'reset' AND used_at IS NULL", (user["id"],))
            token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO email_tokens (token_hash, user_id, purpose, expires_at) VALUES (%s,%s,'reset', now() + make_interval(mins => %s))", (_hash(token), user["id"], RESET_MINUTES))
        else:
            user = None
    if user:
        audit("password_reset_requested", user_id=user["id"], ip=ip)
        bg.add_task(send_mail, email, "Reset your XYRON password",
                    "Someone asked to reset the password for your XYRON account.\n\n"
                    f"To choose a new password, open this link (it works for {RESET_MINUTES} minutes):\n{PUBLIC_BASE_URL}/reset?token={token}\n\n"
                    "You will need a code from your authenticator app, or one of your recovery codes.\n"
                    "If this was not you, ignore this email: nothing changes unless the link is used together with your code.\n")
        bg.add_task(_telegram, user["id"], "\U0001F510 <b>Password reset requested</b>\nA reset link was sent to your email. If that was not you, ignore it: it cannot be used without your authenticator or a recovery code.")
    else:
        audit("password_reset_unknown", ip=ip, detail={"email": email})
    return GENERIC_RESET


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=100)


def _live_reset_token(conn, token):
    return conn.execute("SELECT u.* FROM email_tokens t JOIN users u ON u.id = t.user_id WHERE t.token_hash = %s AND t.purpose = 'reset' AND t.used_at IS NULL AND t.expires_at > now()", (_hash(token),)).fetchone()


@router.post("/auth/reset/check")
def reset_check(body: TokenIn, request: Request):
    ensure_schema()
    ip = client_ip(request)
    if _limited(f"rl:resetcheck:ip:{ip}", 30, 3600):
        raise HTTPException(429, "Too many attempts. Try again later.")
    with get_conn() as conn:
        user = _live_reset_token(conn, body.token)
    if not user or user["status"] not in LOGIN_OK_STATUS:
        raise HTTPException(400, INVALID_LINK)
    return {"valid": True, "email": _mask(user["email"])}


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=10, max_length=100)
    new_password: str = Field(min_length=14, max_length=256)
    code: str = Field(min_length=1, max_length=32)


@router.post("/auth/reset/confirm")
def reset_confirm(body: ResetConfirmIn, request: Request, bg: BackgroundTasks):
    ensure_schema()
    ip = client_ip(request)
    if sec.over_limit(f"rl:resetc:ip:{ip}", 20):
        raise HTTPException(429, "Too many attempts. Try again later.")
    th = _hash(body.token)
    tok_key = f"rl:resetc:tok:{th[:20]}"
    problem = None   # (status, message): raised after the database work is saved, so a burnt link stays burnt
    with get_conn() as conn:
        user = _live_reset_token(conn, body.token)
        if not user or user["status"] not in LOGIN_OK_STATUS:
            sec.hit(f"rl:resetc:ip:{ip}", 3600)
            problem = (400, INVALID_LINK)
        elif sec.over_limit(tok_key, 5):
            conn.execute("UPDATE email_tokens SET used_at = now() WHERE token_hash = %s", (th,))  # too many wrong codes: this link is finished
            problem = (429, "Too many wrong codes. Request a new reset link.")
        else:
            how = second_factor(conn, user, body.code)
            if not how:
                sec.hit(tok_key, 3600)
                sec.hit(f"rl:resetc:ip:{ip}", 3600)
                problem = (400, "That code was not accepted.")
            elif not conn.execute("UPDATE email_tokens SET used_at = now() WHERE token_hash = %s AND used_at IS NULL RETURNING 1", (th,)).fetchone():
                problem = (400, INVALID_LINK)
            else:
                conn.execute("UPDATE email_tokens SET used_at = now() WHERE user_id = %s AND purpose = 'reset' AND used_at IS NULL", (user["id"],))
                conn.execute("UPDATE users SET password_hash = %s, password_changed_at = now() WHERE id = %s", (sec.hash_password(body.new_password), user["id"]))
                left = codes_left(conn, user["id"])
    if problem:
        if problem[1] == "That code was not accepted.":
            audit("password_reset_failed", user_id=user["id"], ip=ip)
        raise HTTPException(*problem)
    revoke_sessions(user["id"])
    sec.r.delete(f"rl:login:acct:{user['email']}")
    audit("password_reset", user_id=user["id"], ip=ip, detail={"second_factor": how})
    extra = f" A recovery code was used ({left} left)." if how == "recovery" else ""
    tell(bg, user, "Your XYRON password was changed", "Your XYRON password was just reset, and every device was signed out." + extra + "\n\nIf this was not you, tell the owner at once.",
         "Your password was just reset and every device was signed out." + extra + " If this was not you, tell the owner at once.")
    return {"ok": True}


# ---------- signing in with a recovery code ----------
class RecoveryLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    recovery_code: str = Field(min_length=1, max_length=32)


@router.post("/auth/login-recovery")
def login_recovery(body: RecoveryLoginIn, request: Request, response: Response, bg: BackgroundTasks):
    ensure_schema()
    ip, email = client_ip(request), body.email.lower()
    acct_key, ip_key = f"rl:login:acct:{email}", f"rl:login:ip:{ip}"
    if sec.over_limit(acct_key, 5) or sec.over_limit(ip_key, 20):
        audit("login_blocked", ip=ip, detail={"email": email})
        raise HTTPException(429, "Too many attempts. Try again later.")
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
        pw_ok = sec.verify_password(user["password_hash"] if user else sec.DUMMY_HASH, body.password)
        ok = bool(user and pw_ok and user["status"] in LOGIN_OK_STATUS)
        if ok:
            ok = use_recovery_code(conn, user["id"], body.recovery_code)
        left = codes_left(conn, user["id"]) if ok else 0
    if not ok:
        sec.hit(acct_key, 900)
        sec.hit(ip_key, 900)
        audit("login_failed", user_id=user["id"] if user else None, ip=ip, detail={"email": email, "recovery_code": True})
        raise HTTPException(401, "Invalid credentials")
    sec.r.delete(acct_key)
    token = sec.create_session(user["id"])
    with get_conn() as conn:
        conn.execute("UPDATE users SET last_login_at = now(), status = 'active' WHERE id = %s", (user["id"],))
    audit("login_ok", user_id=user["id"], ip=ip, detail={"recovery_code": True})
    response.set_cookie(COOKIE, token, max_age=SESSION_TTL, httponly=True, secure=COOKIE_SECURE, samesite="strict", path="/")
    msg = f"A recovery code was used to sign in to your XYRON account ({left} left)."
    tell(bg, user, "XYRON: a recovery code was used", msg + "\n\nIf this was not you, change your password and tell the owner at once.", msg + " If this was not you, change your password and tell the owner at once.")
    return {"email": user["email"], "role": user["role"], "codes_left": left}


# ---------- security settings, for someone signed in ----------
def _fail_key(uid):
    return f"rl:acctsec:{uid}"


def _check_password_and_totp(conn, user_id, password, code, actor_email=None):
    """Both the current password and a fresh authenticator code. Counts failures, and refuses after five in a quarter hour."""
    if sec.over_limit(_fail_key(user_id), 5):
        raise HTTPException(429, "Too many wrong attempts. Try again in a few minutes.")
    row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    ok = bool(row and sec.verify_password(row["password_hash"], password) and re.fullmatch(r"\d{6}", str(code or "").strip())
              and sec.verify_totp(user_id, sec.decrypt_secret(row["totp_secret_enc"]), str(code).strip()))
    if not ok:
        sec.hit(_fail_key(user_id), 900)
        raise HTTPException(400, "The password or the authenticator code was not accepted.")
    return row


class ConfirmIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ChangePasswordIn(ConfirmIn):
    new_password: str = Field(min_length=14, max_length=256)


@router.get("/account/security")
def security_overview(user=Depends(current_user)):
    ensure_schema()
    with get_conn() as conn:
        left = codes_left(conn, user["id"])
        made = conn.execute("SELECT max(created_at) AS t FROM recovery_codes WHERE user_id = %s", (user["id"],)).fetchone()["t"]
        row = conn.execute("SELECT password_changed_at, totp_pending_enc IS NOT NULL AS pending FROM users WHERE id = %s", (user["id"],)).fetchone()
    try:
        with get_conn() as conn:
            tg = bool(conn.execute("SELECT 1 FROM alert_telegram WHERE user_id = %s AND active", (user["id"],)).fetchone())
    except Exception:
        tg = False   # alerts are not installed
    return private_json({"email": user["email"], "role": user["role"], "recovery": {"remaining": left, "created_at": made.isoformat() if made else None, "size": CODE_COUNT},
                                "telegram": tg, "totp_pending": bool(row["pending"]), "password_changed_at": row["password_changed_at"].isoformat() if row["password_changed_at"] else None})


@router.post("/account/password")
def change_password(body: ChangePasswordIn, request: Request, bg: BackgroundTasks, user=Depends(current_user), xyron_session: str | None = Cookie(default=None)):
    ensure_schema()
    with get_conn() as conn:
        row = _check_password_and_totp(conn, user["id"], body.password, body.code)
        if sec.verify_password(row["password_hash"], body.new_password):
            raise HTTPException(400, "Choose a password you have not used just now.")
        conn.execute("UPDATE users SET password_hash = %s, password_changed_at = now() WHERE id = %s", (sec.hash_password(body.new_password), user["id"]))
    revoke_sessions(user["id"], keep_token=xyron_session)
    audit("password_changed", user_id=user["id"], ip=client_ip(request))
    tell(bg, user, "Your XYRON password was changed", "Your XYRON password was changed, and your other devices were signed out.\n\nIf this was not you, tell the owner at once.", "Your password was changed and your other devices were signed out. If this was not you, tell the owner at once.")
    return private_json({"ok": True})


@router.post("/account/recovery-codes")
def make_recovery_codes(body: ConfirmIn, request: Request, bg: BackgroundTasks, user=Depends(current_user)):
    ensure_schema()
    codes = new_codes()
    with get_conn() as conn:
        _check_password_and_totp(conn, user["id"], body.password, body.code)
        save_codes(conn, user["id"], codes)
    audit("recovery_codes_generated", user_id=user["id"], ip=client_ip(request))
    tell(bg, user, "XYRON: new recovery codes created", "New recovery codes were created for your XYRON account. The old ones no longer work.\n\nIf this was not you, change your password and tell the owner at once.",
         "New recovery codes were created. The old ones no longer work. If this was not you, change your password and tell the owner at once.")
    return private_json({"codes": codes, "size": CODE_COUNT})


@router.post("/account/authenticator/start")
def authenticator_start(body: ConfirmIn, request: Request, user=Depends(current_user)):
    ensure_schema()
    secret = sec.new_totp_secret()
    with get_conn() as conn:
        _check_password_and_totp(conn, user["id"], body.password, body.code)
        conn.execute("UPDATE users SET totp_pending_enc = %s WHERE id = %s", (sec.encrypt_secret(secret), user["id"]))
    audit("authenticator_change_started", user_id=user["id"], ip=client_ip(request))
    return private_json({"secret": secret, "account": user["email"], "uri": pyotp.TOTP(secret).provisioning_uri(name=user["email"], issuer_name="XYRON")})


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


@router.post("/account/authenticator/confirm")
def authenticator_confirm(body: CodeIn, request: Request, bg: BackgroundTasks, user=Depends(current_user), xyron_session: str | None = Cookie(default=None)):
    ensure_schema()
    if sec.over_limit(_fail_key(user["id"]), 5):
        raise HTTPException(429, "Too many wrong attempts. Try again in a few minutes.")
    with get_conn() as conn:
        row = conn.execute("SELECT totp_pending_enc FROM users WHERE id = %s", (user["id"],)).fetchone()
        if not row or not row["totp_pending_enc"]:
            raise HTTPException(409, "There is no authenticator change in progress. Start again.")
        if not pyotp.TOTP(sec.decrypt_secret(row["totp_pending_enc"])).verify(body.code, valid_window=1):
            sec.hit(_fail_key(user["id"]), 900)
            raise HTTPException(400, "That code did not match. Check the app and try the next code.")
        conn.execute("UPDATE users SET totp_secret_enc = totp_pending_enc, totp_pending_enc = NULL, totp_shown = true WHERE id = %s", (user["id"],))
    revoke_sessions(user["id"], keep_token=xyron_session)
    audit("authenticator_changed", user_id=user["id"], ip=client_ip(request))
    tell(bg, user, "XYRON: your authenticator was changed", "The authenticator app for your XYRON account was changed, and your other devices were signed out.\n\nIf this was not you, tell the owner at once.", "Your authenticator app was changed and your other devices were signed out. If this was not you, tell the owner at once.")
    return private_json({"ok": True})


@router.post("/account/authenticator/cancel")
def authenticator_cancel(user=Depends(current_user)):
    ensure_schema()
    with get_conn() as conn:
        conn.execute("UPDATE users SET totp_pending_enc = NULL WHERE id = %s", (user["id"],))
    return private_json({"ok": True})


@router.post("/account/sessions/revoke")
def sign_out_others(request: Request, user=Depends(current_user), xyron_session: str | None = Cookie(default=None)):
    revoke_sessions(user["id"], keep_token=xyron_session)
    audit("sessions_revoked", user_id=user["id"], ip=client_ip(request))
    return private_json({"ok": True})


# ---------- the owner or an admin resets someone's authenticator ----------
@router.post("/admin/users/{uid}/reset-2fa")
def admin_reset_2fa(uid: int, request: Request, actor=Depends(require_role("owner", "admin"))):
    ensure_schema()
    secret = sec.new_totp_secret()
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        t = _target(conn, uid)
        _check(actor, t)
        if t["status"] not in LOGIN_OK_STATUS:
            raise HTTPException(409, "User is not active")
        conn.execute("UPDATE users SET totp_secret_enc = %s, totp_shown = false, totp_pending_enc = NULL WHERE id = %s", (sec.encrypt_secret(secret), uid))
        conn.execute("DELETE FROM recovery_codes WHERE user_id = %s", (uid,))
        conn.execute("UPDATE email_tokens SET used_at = now() WHERE user_id = %s AND purpose = 'twofa' AND used_at IS NULL", (uid,))
        conn.execute("INSERT INTO email_tokens (token_hash, user_id, purpose, expires_at) VALUES (%s,%s,'twofa', now() + make_interval(hours => %s))", (_hash(token), uid, TWOFA_HOURS))
    revoke_sessions(uid)
    audit("authenticator_reset_by_admin", user_id=actor["id"], ip=client_ip(request), detail={"target": uid})
    emailed = send_mail(t["email"], "Set up your XYRON authenticator again",
                        "The owner reset the authenticator on your XYRON account, and every device was signed out.\n\n"
                        f"To set up your authenticator app again, open this link (it works for {TWOFA_HOURS} hours, once):\n{PUBLIC_BASE_URL}/auth/twofa?token={token}\n\n"
                        "Your password has not changed. After you sign in, create new recovery codes under Security.\n"
                        "If you did not expect this, tell the owner.\n")
    _telegram(uid, "\U0001F510 <b>Authenticator reset</b>\nThe owner reset your authenticator. Check your email for the setup link. If you did not expect this, tell the owner.")
    return {"ok": True, "emailed": emailed}


@router.get("/auth/twofa", response_class=HTMLResponse)
def twofa_form(token: str = ""):
    if not token or len(token) > 100:
        return page("<p>This link is invalid.</p>", 400)
    return page("<h2>Set up your authenticator again</h2>"
                '<form method="post" action="/auth/twofa">'
                f'<input type="hidden" name="token" value="{escape(token)}">'
                '<button type="submit">Show my setup key</button></form>')


@router.post("/auth/twofa", response_class=HTMLResponse)
async def twofa_show(request: Request):
    ensure_schema()
    ip = client_ip(request)
    if sec.over_limit(f"rl:twofa:ip:{ip}", 20):
        return page("<p>Too many attempts. Try again later.</p>", 429)
    sec.hit(f"rl:twofa:ip:{ip}", 3600)
    token = parse_qs((await request.body())[:2048].decode(errors="ignore")).get("token", [""])[0]
    if not token or len(token) > 100:
        return page(f"<p>{INVALID_LINK}</p>", 400)
    with get_conn() as conn:
        row = conn.execute("UPDATE email_tokens SET used_at = now() WHERE token_hash = %s AND purpose = 'twofa' AND used_at IS NULL AND expires_at > now() RETURNING user_id", (_hash(token),)).fetchone()
        if not row:
            return page(f"<p>{INVALID_LINK}</p>", 400)
        user = conn.execute("UPDATE users SET totp_shown = true WHERE id = %s RETURNING email, totp_secret_enc", (row["user_id"],)).fetchone()
    audit("authenticator_setup_shown", user_id=row["user_id"], ip=ip)
    secret = sec.decrypt_secret(user["totp_secret_enc"])
    return page("<h2>Your new authenticator key</h2>"
                "<p>In your authenticator app choose &ldquo;enter a setup key&rdquo; and add:</p>"
                f"<p>Account: <code>{escape(user['email'])}</code></p><p>Key: <code>{escape(secret)}</code></p>"
                "<p>This key is shown only once. Your password has not changed. After you sign in, create new recovery codes under Security.</p>")
