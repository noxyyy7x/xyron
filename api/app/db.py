import logging
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import DB_URL

log = logging.getLogger("xyron.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  totp_secret_enc TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'pending'
    CHECK (role IN ('owner','admin','analyst','viewer','pending')),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','active','suspended')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  event TEXT NOT NULL,
  ip TEXT,
  detail JSONB NOT NULL DEFAULT '{}'
);
"""


@contextmanager
def get_conn():
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        yield conn


def init_schema():
    with get_conn() as conn:
        conn.execute(SCHEMA)


def audit(event, user_id=None, ip=None, detail=None):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO audit_log (event, user_id, ip, detail) VALUES (%s,%s,%s,%s)",
                (event, user_id, ip, Jsonb(detail or {})),
            )
    except Exception:
        log.exception("audit write failed")
