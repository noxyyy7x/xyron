import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
api = root / "api"
app = api / "app"
static = app / "static"

for rel in ("ships.py", "ships_data.py", "data/ports.json", "static/ships.js", "static/hub/ships.css"):
    if not (app / rel).exists():
        sys.exit(f"STOPPED, nothing changed. {rel} is missing. Unpack xyron-ships.zip into ~/xyron first.")
if "ships.router" in (app / "main.py").read_text():
    sys.exit("STOPPED, nothing changed. This patch has already been applied.")

STYLE_STUB = '''  ships: {
    pulse: 0,
    color: () => [0.31, 0.49, 1.0],
    size: () => 0.02,
    rank: () => 0,
    tip: (e) => [e.title, ''],
    rows: () => [],
    source: null,
    summary: (n, l) => 'Ships \\u00b7 ' + ((l && l.count) || 0).toLocaleString() + ' vessels (AISstream)',
  },
'''
SHIP_IMPORT = '''  console.error('Aviation layer failed to load', e);
}
try {
  const mod = await import('/static/ships.js');
  shipHooks = mod.init({
    THREE, globe, camera, renderer, canvas,
    deselect: () => select(-1), flyTo, openPanel,
  }) || {};
} catch (e) {
  console.error('Ships layer failed to load', e);
}
'''

edits = {
    app / "main.py": [
        ("from . import accounts, aviation, events, football, markets, news, pages, sports, weather\n",
         "from . import accounts, aviation, events, football, markets, news, pages, ships, sports, weather\n"),
        ("        asyncio.create_task(markets.ingest_loop()),\n    ]\n",
         "        asyncio.create_task(markets.ingest_loop()),\n        asyncio.create_task(ships.ingest_loop()),\n    ]\n"),
        ("app.include_router(markets.router)\n", "app.include_router(markets.router)\napp.include_router(ships.router)\n"),
    ],
    app / "events.py": [
        ('{"id": "markets", "label": "Markets", "live": True},\n',
         '{"id": "markets", "label": "Markets", "live": True},\n    {"id": "ships", "label": "Ships", "live": True},\n'),
    ],
    static / "globe.html": [
        ('<link rel="stylesheet" href="/static/hub/markets.css">\n',
         '<link rel="stylesheet" href="/static/hub/markets.css">\n<link rel="stylesheet" href="/static/hub/ships.css">\n'),
    ],
    static / "globe.js": [
        ("let aviationHooks = {};\n", "let aviationHooks = {};\nlet shipHooks = {};\n"),
        ("  if (aviationHooks.clear) aviationHooks.clear();\n", "  if (aviationHooks.clear) aviationHooks.clear();\n  if (shipHooks.clear) shipHooks.clear();\n"),
        ("    if (aviationHooks.onClick && aviationHooks.onClick(e.clientX, e.clientY)) return; // an aircraft was tapped\n",
         "    if (aviationHooks.onClick && aviationHooks.onClick(e.clientX, e.clientY)) return; // an aircraft was tapped\n"
         "    if (shipHooks.onClick && shipHooks.onClick(e.clientX, e.clientY)) return; // a ship was tapped\n"),
        ("  console.error('Aviation layer failed to load', e);\n}\n", SHIP_IMPORT),
        ("    const overPlane = !overMarker && aviationHooks.onHover ? aviationHooks.onHover(pendingHover[0], pendingHover[1]) : false;\n"
         "    const overEvent = overMarker || overPlane;\n",
         "    const overPlane = !overMarker && aviationHooks.onHover ? aviationHooks.onHover(pendingHover[0], pendingHover[1]) : false;\n"
         "    const overShip = !overMarker && !overPlane && shipHooks.onHover ? shipHooks.onHover(pendingHover[0], pendingHover[1]) : false;\n"
         "    const overEvent = overMarker || overPlane || overShip;\n"),
        ("  if (aviationHooks.onFrame) aviationHooks.onFrame(now, dt);\n", "  if (aviationHooks.onFrame) aviationHooks.onFrame(now, dt);\n  if (shipHooks.onFrame) shipHooks.onFrame(now, dt);\n"),
    ],
    static / "layers.js": [
        ("football: '#2ee57a', markets: '#ff5fd2',\n};\n", "football: '#2ee57a', markets: '#ff5fd2', ships: '#4f7cff',\n};\n"),
        ("  markets: { d: ['M3 17l6-6 4 4 8-8', 'M15 7h6v6'] },\n",
         "  markets: { d: ['M3 17l6-6 4 4 8-8', 'M15 7h6v6'] },\n  ships: { d: ['M3 16h18l-2.5 4h-13z', 'M6 16v-5h12v5', 'M12 11V6', 'M9 6h6'] },\n"),
        ("  markets: marketStyle,\n", "  markets: marketStyle,\n" + STYLE_STUB),
    ],
}

new_text = {}
for path, pairs in edits.items():
    text = path.read_text()
    for old, new in pairs:
        if text.count(old) != 1:
            sys.exit(f"STOPPED, nothing changed. Could not find exactly one match in {path.name} for:\n{old[:200]!r}")
        text = text.replace(old, new)
    new_text[path] = text

# the websocket library that talks to AISstream
req = api / "requirements.txt"
if req.exists() and not any(line.strip().lower().startswith("websockets") for line in req.read_text().splitlines()):
    body = req.read_text()
    new_text[req] = body + ("" if body.endswith("\n") else "\n") + "websockets>=12\n"

for path, text in new_text.items():
    path.write_text(text)
    print("patched", path.name if path.name != "requirements.txt" else "requirements.txt (added websockets)")
