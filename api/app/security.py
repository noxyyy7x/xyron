import base64
import hashlib
import secrets

import pyotp
import redis
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet

from .config import REDIS_PASSWORD, SECRET_KEY, SESSION_TTL

r = redis.Redis(host="redis", password=REDIS_PASSWORD, decode_responses=True, socket_timeout=3)
ph = PasswordHasher()
DUMMY_HASH = ph.hash("dummy-password-for-constant-timing")
_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()))


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(pw_hash: str, password: str) -> bool:
    try:
        return ph.verify(pw_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def encrypt_secret(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet.decrypt(value.encode()).decode()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(user_id: int, secret: str, code: str) -> bool:
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        return False
    # a code can only be used once
    return bool(r.set(f"totp_used:{user_id}:{code}", "1", nx=True, ex=90))


def over_limit(key: str, limit: int) -> bool:
    return int(r.get(key) or 0) >= limit


def hit(key: str, window: int) -> None:
    if r.incr(key) == 1:
        r.expire(key, window)


def _skey(token: str) -> str:
    return "session:" + hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    r.setex(_skey(token), SESSION_TTL, str(user_id))
    return token


def session_user_id(token: str):
    key = _skey(token)
    value = r.get(key)
    if value:
        r.expire(key, SESSION_TTL)
        return int(value)
    return None


def destroy_session(token: str) -> None:
    r.delete(_skey(token))
