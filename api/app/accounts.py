import hashlib
import secrets
from html import escape
from urllib.parse import parse_qs

import psycopg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field

from . import security as sec
from .config import OWNER_NOTIFY_EMAIL, PUBLIC_BASE_URL
from .db import audit, get_conn
from .deps import client_ip, require_role
from .mailer import send_mail

router = APIRouter()

GENERIC = {"message": "If this address can be registered, a verification email has been sent."}
ASSIGNABLE = "^(viewer|analyst|admin)$"

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>XYRON</title>
<style>body{background:#0b0f14;color:#e6edf3;font-family:system-ui,sans-serif;display:flex;justify-content:center;padding:48px 16px}
main{max-width:480px;width:100%}h1{letter-spacing:.2em}code{word-break:break-all;background:#161b22;padding:2px 6px;border-radius:4px}
button{background:#238636;color:#fff;border:0;padding:12px 20px;border-radius:6px;font-size:16px;cursor:pointer}</style>
</head><body><main><h1>XYRON</h1>{{BODY}}</main></body></html>"""


def page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(PAGE.replace("{{BODY}}", body), status_code=status)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=14, max_length=256)


@router.post("/auth/register", status_code=202)
def register(body: RegisterIn, request: Request, bg: BackgroundTasks):
    ip = client_ip(request)
    email = body.email.lower()
    if sec.over_limit(f"rl:register:ip:{ip}", 5):
        raise HTTPException(429, "Too many attempts. Try again later.")
    sec.hit(f"rl:register:ip:{ip}", 3600)

    # same work whether or not the address exists, so timing doesn't leak it
    pw_hash = sec.hash_password(body.password)
    totp_enc = sec.encrypt_secret(sec.new_totp_secret())
    token = secrets.token_urlsafe(32)
    created_id = None
    try:
        with get_conn() as conn:
            if not conn.execute("SELECT 1 FROM users WHERE email = %s", (email,)).fetchone():
                created_id = conn.execute(
                    "INSERT INTO users (email, password_hash, totp_secret_enc) VALUES (%s,%s,%s) RETURNING id",
                    (email, pw_hash, totp_enc),
                ).fetchone()["id"]
                conn.execute(
                    "INSERT INTO email_tokens (token_hash, user_id, purpose, expires_at) "
                    "VALUES (%s,%s,'verify', now() + interval '24 hours')",
                    (_hash(token), created_id),
                )
    except psycopg.errors.UniqueViolation:
        created_id = None

    if created_id is None:
        audit("register_duplicate", ip=ip, detail={"email": email})
        return GENERIC
    audit("register", user_id=created_id, ip=ip)
    link = f"{PUBLIC_BASE_URL}/auth/verify?token={token}"
    bg.add_task(
        send_mail, email, "Confirm your XYRON email",
        "Someone registered this email address on XYRON.\n\n"
        f"To confirm it, open this link (valid for 24 hours):\n{link}\n\n"
        "If this wasn't you, ignore this email and nothing will happen.\n",
    )
    return GENERIC


@router.get("/auth/verify", response_class=HTMLResponse)
def verify_form(token: str = ""):
    if not token or len(token) > 100:
        return page("<p>This link is invalid.</p>", 400)
    return page(
        "<h2>Confirm your email</h2>"
        '<form method="post" action="/auth/verify">'
        f'<input type="hidden" name="token" value="{escape(token)}">'
        '<button type="submit">Confirm email</button></form>'
    )


@router.post("/auth/verify", response_class=HTMLResponse)
async def verify(request: Request, bg: BackgroundTasks):
    ip = client_ip(request)
    if sec.over_limit(f"rl:verify:ip:{ip}", 20):
        return page("<p>Too many attempts. Try again later.</p>", 429)
    sec.hit(f"rl:verify:ip:{ip}", 3600)
    raw = (await request.body())[:2048].decode(errors="ignore")
    token = parse_qs(raw).get("token", [""])[0]
    if not token or len(token) > 100:
        return page("<p>This link is invalid or has expired.</p>", 400)

    with get_conn() as conn:
        row = conn.execute(
            "UPDATE email_tokens SET used_at = now() WHERE token_hash = %s AND purpose = 'verify' "
            "AND used_at IS NULL AND expires_at > now() RETURNING user_id",
            (_hash(token),),
        ).fetchone()
        if not row:
            return page("<p>This link is invalid or has expired.</p>", 400)
        user = conn.execute(
            "UPDATE users SET email_verified = true WHERE id = %s "
            "RETURNING id, email, totp_secret_enc, totp_shown",
            (row["user_id"],),
        ).fetchone()
        show = not user["totp_shown"]
        if show:
            conn.execute("UPDATE users SET totp_shown = true WHERE id = %s", (user["id"],))

    audit("email_verified", user_id=user["id"], ip=ip)
    bg.add_task(
        send_mail, OWNER_NOTIFY_EMAIL, "XYRON: new registration awaiting approval",
        "A new user confirmed their email and is waiting for approval.\n\n"
        f"Email: {user['email']}\n\n"
        f"Sign in to the XYRON admin to review: {PUBLIC_BASE_URL}/admin\n",
    )
    if not show:
        return page("<h2>Email confirmed</h2><p>Your registration is waiting for approval.</p>")
    secret = sec.decrypt_secret(user["totp_secret_enc"])
    return page(
        "<h2>Email confirmed</h2>"
        "<p>Your registration is now waiting for approval by the XYRON owner.</p>"
        "<p><b>Set up two-factor authentication now.</b> In your authenticator app choose "
        "&ldquo;enter a setup key&rdquo; and add:</p>"
        f"<p>Account: <code>{escape(user['email'])}</code></p>"
        f"<p>Key: <code>{escape(secret)}</code></p>"
        "<p>This key is shown only once. You need a 6-digit code from the app every time you sign in.</p>"
    )


# ---------- admin ----------

class RoleIn(BaseModel):
    role: str = Field(default="viewer", pattern=ASSIGNABLE)


def _target(conn, uid: int):
    t = conn.execute(
        "SELECT id, email, role, status, email_verified FROM users WHERE id = %s", (uid,)
    ).fetchone()
    if not t:
        raise HTTPException(404, "User not found")
    return t


def _check(actor, t, new_role=None):
    if t["role"] == "owner" or t["id"] == actor["id"]:
        raise HTTPException(403, "Forbidden")
    if actor["role"] != "owner" and (t["role"] == "admin" or new_role == "admin"):
        raise HTTPException(403, "Only the owner can manage admins")


@router.get("/admin/users")
def list_users(actor=Depends(require_role("owner", "admin"))):
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, email, role, status, email_verified, created_at, last_login_at "
            "FROM users ORDER BY id"
        ).fetchall()


@router.post("/admin/users/{uid}/approve")
def approve(uid: int, body: RoleIn, request: Request, bg: BackgroundTasks,
            actor=Depends(require_role("owner", "admin"))):
    with get_conn() as conn:
        t = _target(conn, uid)
        _check(actor, t, body.role)
        if t["status"] != "pending" or not t["email_verified"]:
            raise HTTPException(409, "Not a verified pending registration")
        conn.execute("UPDATE users SET status = 'approved', role = %s WHERE id = %s", (body.role, uid))
    audit("user_approved", user_id=actor["id"], ip=client_ip(request), detail={"target": uid, "role": body.role})
    bg.add_task(
        send_mail, t["email"], "Your XYRON account was approved",
        f"Your XYRON account has been approved. You can now sign in at {PUBLIC_BASE_URL}\n",
    )
    return {"ok": True}


@router.post("/admin/users/{uid}/suspend")
def suspend(uid: int, request: Request, actor=Depends(require_role("owner", "admin"))):
    with get_conn() as conn:
        t = _target(conn, uid)
        _check(actor, t)
        if t["status"] not in ("approved", "active"):
            raise HTTPException(409, "User is not active")
        conn.execute("UPDATE users SET status = 'suspended' WHERE id = %s", (uid,))
    audit("user_suspended", user_id=actor["id"], ip=client_ip(request), detail={"target": uid})
    return {"ok": True}


@router.post("/admin/users/{uid}/reactivate")
def reactivate(uid: int, request: Request, actor=Depends(require_role("owner", "admin"))):
    with get_conn() as conn:
        t = _target(conn, uid)
        _check(actor, t)
        if t["status"] != "suspended":
            raise HTTPException(409, "User is not suspended")
        conn.execute("UPDATE users SET status = 'approved' WHERE id = %s", (uid,))
    audit("user_reactivated", user_id=actor["id"], ip=client_ip(request), detail={"target": uid})
    return {"ok": True}


@router.post("/admin/users/{uid}/role")
def set_role(uid: int, body: RoleIn, request: Request, actor=Depends(require_role("owner"))):
    with get_conn() as conn:
        t = _target(conn, uid)
        _check(actor, t, body.role)
        if t["status"] not in ("approved", "active"):
            raise HTTPException(409, "User is not active")
        conn.execute("UPDATE users SET role = %s WHERE id = %s", (body.role, uid))
    audit("role_changed", user_id=actor["id"], ip=client_ip(request), detail={"target": uid, "role": body.role})
    return {"ok": True}
