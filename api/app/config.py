import os

DB_URL = (
    f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@db:5432/{os.environ['POSTGRES_DB']}"
)
REDIS_PASSWORD = os.environ["REDIS_PASSWORD"]
SECRET_KEY = os.environ["SECRET_KEY"]
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
SESSION_TTL = 12 * 3600
