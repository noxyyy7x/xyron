import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
weather = root / "api" / "app" / "weather.py"

DROP_FN = '''def _drop_stale(since):
    """After a full refresh, remove places that are no longer on the list (they were not refreshed)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM events WHERE source = 'open-meteo' AND fetched_at < %s", (since,))


def _seconds_until_due():
'''

edits = {
    weather: [
        ("POLL_SECONDS = 14400\n", "POLL_SECONDS = 7200\n"),
        ("def _seconds_until_due():\n", DROP_FN),
        ("            total = 0\n", "            total = 0\n            cycle_start = datetime.now(timezone.utc)\n"),
        ('            feed_status["weather"] = {"last_ok": datetime.now(timezone.utc), "error": None}\n',
         '            await asyncio.to_thread(_drop_stale, cycle_start)\n'
         '            feed_status["weather"] = {"last_ok": datetime.now(timezone.utc), "error": None}\n'),
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
