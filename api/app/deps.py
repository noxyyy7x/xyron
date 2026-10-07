from fastapi import Cookie, Depends, HTTPException, Request

from . import hardening
from . import security as sec
from .db import get_conn

LOGIN_OK_STATUS = ("approved", "active")


def client_ip(request: Request) -> str:
    return hardening.client_ip(request)


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
