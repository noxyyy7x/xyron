import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"

for rel in ("football.py", "sports.py", "static/hub/football.js", "static/hub/football.css"):
    if not (app / rel).exists():
        sys.exit(f"STOPPED, nothing changed. {rel} is missing. Unpack xyron-football.zip into ~/xyron first.")
if "def build_feeds" not in (app / "sports.py").read_text():
    sys.exit("STOPPED, nothing changed. api/app/sports.py is still the old version; unpack the zip over it first.")

MORE_COLORS = ("  rugby: [0.6, 0.9, 0.4], volleyball: [1.0, 0.85, 0.3],\n"
               "  'rugby-league': [0.5, 0.85, 0.35], tennis: [0.8, 1.0, 0.3], golf: [0.35, 0.9, 0.55], lacrosse: [0.9, 0.55, 0.8],\n"
               "  'australian-football': [1.0, 0.7, 0.3], 'field-hockey': [0.5, 0.8, 1.0], 'water-polo': [0.3, 0.7, 1.0],\n};\n")
FLY = ("  const { THREE, globe, camera, renderer, canvas, nearestCountry, countries, deselect, flyTo, openPanel } = ctx;\n"
       "  // the football hub asks the globe to fly to a stadium\n"
       "  window.addEventListener('xyron-flyto', (ev) => {\n"
       "    const d = ev.detail || {};\n"
       "    if (typeof d.lat === 'number' && typeof d.lon === 'number') flyTo(d.lat, d.lon, 2.2);\n"
       "  });\n")

edits = {
    app / "main.py": [
        ("from . import accounts, aviation, events, news, pages, sports, weather\n",
         "from . import accounts, aviation, events, football, news, pages, sports, weather\n"),
        ("app.include_router(sports.router)\n", "app.include_router(sports.router)\napp.include_router(football.router)\n"),
    ],
    static / "globe.html": [
        ('<link rel="stylesheet" href="/static/brand/theme.css">\n',
         '<link rel="stylesheet" href="/static/brand/theme.css">\n<link rel="stylesheet" href="/static/hub/football.css">\n'),
        ('<script src="/static/brand/theme.js" defer></script>\n',
         '<script src="/static/brand/theme.js" defer></script>\n<script src="/static/hub/football.js" defer></script>\n'),
    ],
    static / "layers.js": [
        ("  rugby: [0.6, 0.9, 0.4], volleyball: [1.0, 0.85, 0.3],\n};\n", MORE_COLORS),
        ("  const { THREE, globe, camera, renderer, canvas, nearestCountry, countries, deselect, flyTo, openPanel } = ctx;\n", FLY),
    ],
}

if "football.router" in (app / "main.py").read_text():
    sys.exit("STOPPED, nothing changed. This patch has already been applied.")
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
