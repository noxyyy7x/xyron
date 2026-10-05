import os

import psycopg
import redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# API docs are hidden until we deliberately expose them
app = FastAPI(title="XYRON API", docs_url=None, redoc_url=None, openapi_url=None)


def check_db() -> bool:
    try:
        url = (
            f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
            f"@db:5432/{os.environ['POSTGRES_DB']}"
        )
        with psycopg.connect(url, connect_timeout=3) as conn:
            conn.execute("select 1")
        return True
    except Exception:
        return False


def check_redis() -> bool:
    try:
        r = redis.Redis(host="redis", password=os.environ["REDIS_PASSWORD"], socket_timeout=3)
        return bool(r.ping())
    except Exception:
        return False


@app.get("/health")
def health():
    checks = {"database": check_db(), "redis": check_redis()}
    ok = all(checks.values())
    return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)
