import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from . import security as sec
from .config import COOKIE_SECURE, DB_URL, SESSION_TTL
from .db import audit, get_conn, init_schema

log = logging.getLogger("xyron")
COOKIE = "xyron_session"
LOGIN_OK_STATUS = ("approved", "active")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_schema()
    yield


app = FastAPI(title="XYRON API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith(("/auth", "/admin")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@app.get("/health")
def health():
    checks = {"database": False, "redis": False}
    try:
        with psycopg.connect(DB_URL, connect_timeout=3) as conn:
            conn.execute("select 1")
        checks["database"] = True
    except Exception:
        pass
    try:
        checks["redis"] = bool(sec.r.ping())
    except Exception:
        pass
    ok = all(checks.values())
    return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(pattern=r"^\d{6}$")


@app.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    ip = _ip(request)
    email = body.email.lower()
    acct_key, ip_key = f"rl:login:acct:{email}", f"rl:login:ip:{ip}"

    if sec.over_limit(acct_key, 5) or sec.over_limit(ip_key, 20):
        audit("login_blocked", ip=ip, detail={"email": email})
        raise HTTPException(429, "Too many attempts. Try again later.")

    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()

    # always run the password check so timing doesn't reveal whether the account exists
    pw_ok = sec.verify_password(user["password_hash"] if user else sec.DUMMY_HASH, body.password)
    ok = bool(user and pw_ok and user["status"] in LOGIN_OK_STATUS)
    if ok:
        secret = sec.decrypt_secret(user["totp_secret_enc"])
        ok = sec.verify_totp(user["id"], secret, body.code)

    if not ok:
        sec.hit(acct_key, 900)
        sec.hit(ip_key, 900)
        audit("login_failed", user_id=user["id"] if user else None, ip=ip, detail={"email": email})
        raise HTTPException(401, "Invalid credentials")

    sec.r.delete(acct_key)
    token = sec.create_session(user["id"])
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_login_at = now(), status = 'active' WHERE id = %s", (user["id"],)
        )
    audit("login_ok", user_id=user["id"], ip=ip)
    response.set_cookie(
        COOKIE, token, max_age=SESSION_TTL, httponly=True,
        secure=COOKIE_SECURE, samesite="strict", path="/",
    )
    return {"email": user["email"], "role": user["role"]}


def current_user(xyron_session: str | None = Cookie(default=None)):
    if not xyron_session:
        raise HTTPException(401, "Not authenticated")
    uid = sec.session_user_id(xyron_session)
    if uid is None:
        raise HTTPException(401, "Not authenticated")
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id, email, role, status FROM users WHERE id = %s", (uid,)
        ).fetchone()
    if not user or user["status"] not in LOGIN_OK_STATUS:
        raise HTTPException(401, "Not authenticated")
    return user


def require_role(*roles: str):
    def checker(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "Forbidden")
        return user
    return checker


@app.get("/auth/me")
def me(user=Depends(current_user)):
    return {"email": user["email"], "role": user["role"], "status": user["status"]}


@app.post("/auth/logout")
def logout(request: Request, response: Response, user=Depends(current_user),
           xyron_session: str | None = Cookie(default=None)):
    if xyron_session:
        sec.destroy_session(xyron_session)
    audit("logout", user_id=user["id"], ip=_ip(request))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/admin/users")
def list_users(user=Depends(require_role("owner", "admin"))):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, email, role, status, created_at, last_login_at FROM users ORDER BY id"
        ).fetchall()
    return rows
