import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"

edits = {
    app / "main.py": [
        ("from . import accounts, events, pages\n",
         "from . import accounts, events, pages, weather\n"),
        ("    task = asyncio.create_task(events.ingest_loop())\n    yield\n    task.cancel()\n",
         "    tasks = [\n        asyncio.create_task(events.ingest_loop()),\n"
         "        asyncio.create_task(weather.ingest_loop()),\n    ]\n    yield\n"
         "    for task in tasks:\n        task.cancel()\n"),
    ],
    app / "events.py": [
        ('{"id": "weather", "label": "Weather", "live": False},',
         '{"id": "weather", "label": "Weather", "live": True},'),
    ],
}

# check everything first, so a mismatch changes nothing
new_text = {}
for path, pairs in edits.items():
    text = path.read_text()
    for old, new in pairs:
        if text.count(old) != 1:
            sys.exit(f"STOPPED, nothing changed. Could not find exactly one match in {path.name} for:\n{old!r}")
        text = text.replace(old, new)
    new_text[path] = text
for path, text in new_text.items():
    path.write_text(text)
    print("patched", path.name)
