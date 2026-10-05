import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"

WEATHER_NEW = '''def _seconds_until_due():
    """Seconds until the next refresh is due, so a restart does not re-fetch data that is still fresh."""
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT max(fetched_at) AS t FROM events WHERE source = 'open-meteo'").fetchone()
    except Exception:
        return 0
    if not row or not row["t"]:
        return 0
    age = (datetime.now(timezone.utc) - row["t"]).total_seconds()
    return max(0, int(POLL_SECONDS - age))


async def ingest_loop():
    await asyncio.sleep(12)
    cities = load_cities()
    wait = await asyncio.to_thread(_seconds_until_due)
    if wait > 0:
        log.info("weather data is still fresh, next refresh in %d s", wait)
        await asyncio.sleep(wait)
'''

edits = {
    app / "main.py": [
        ("app.include_router(aviation.router)\n",
         "app.include_router(aviation.router)\napp.include_router(news.router)\n"),
    ],
    app / "weather.py": [
        ("async def ingest_loop():\n    await asyncio.sleep(12)\n    cities = load_cities()\n", WEATHER_NEW),
    ],
    static / "layers.js": [
        ("' mentions in 24 h'", "' headlines in 24 h'"),
        ("['Mentions in the last 24 hours', ", "['Headlines in the last 24 hours', "),
        (r"""    name: 'Coverage mapped by the GDELT Project (gdeltproject.org). A location is where GDELT placed a mention in the news, not necessarily where something happened.',
    linkLabel: 'GDELT Project',
    prefix: 'https://www.gdeltproject.org/',
""", r"""    name: 'Headlines from BBC News, Al Jazeera, The Guardian and France 24 feeds, placed on the map by the city or country named in each one. Placement is approximate and can be wrong.',
    linkLabel: 'News feeds',
    prefix: 'about:none',
"""),
        ("' places (GDELT)'", "' places (news feeds)'"),
    ],
}

# check everything first, so a mismatch changes nothing
new_text = {}
for path, pairs in edits.items():
    text = path.read_text()
    for old, new in pairs:
        if text.count(old) != 1:
            sys.exit(f"STOPPED, nothing changed. Could not find exactly one match in {path.name} for:\n{old[:200]!r}")
        text = text.replace(old, new)
    new_text[path] = text
for path, text in new_text.items():
    path.write_text(text)
    print("patched", path.name)
