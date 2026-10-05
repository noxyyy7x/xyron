import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"

edits = {
    app / "main.py": [
        ("from contextlib import asynccontextmanager\n",
         "import asyncio\nfrom contextlib import asynccontextmanager\n"),
        ("from . import accounts, pages\n",
         "from . import accounts, events, pages\n"),
        ("async def lifespan(app: FastAPI):\n    init_schema()\n    yield\n",
         "async def lifespan(app: FastAPI):\n    init_schema()\n    events.init_schema()\n"
         "    task = asyncio.create_task(events.ingest_loop())\n    yield\n    task.cancel()\n"),
        ("app.include_router(accounts.router)\n",
         "app.include_router(accounts.router)\napp.include_router(events.router)\n"),
        ('if request.url.path.startswith(("/auth", "/admin")):',
         'if request.url.path.startswith(("/auth", "/admin", "/api")):'),
    ],
    static / "globe.js": [
        ("let hoverC = -1;\n", "let layerHooks = {};\nlet hoverC = -1;\n"),
        ("  if (ci < 0) { hidePanel(); return; }\n  showPanel(ci);\n",
         "  if (ci < 0) { hidePanel(); if (layerHooks.onSelect) layerHooks.onSelect(-1); return; }\n"
         "  showPanel(ci);\n  if (layerHooks.onSelect) layerHooks.onSelect(ci);\n"),
        ("// ---------- render loop ----------\n",
         "// ---------- live layers (layers.js) ----------\n"
         "function nearestCountry(lat, lon) {\n"
         "  const la = lat * DEG;\n  const lo = lon * DEG;\n"
         "  const x = Math.cos(la) * Math.sin(lo);\n  const y = Math.sin(la);\n  const z = Math.cos(la) * Math.cos(lo);\n"
         "  let best = -1;\n  let bestDot = 0.99; // within about 8 degrees of land\n"
         "  for (let i = 0; i < n; i++) {\n"
         "    const d = pos[3 * i] * x + pos[3 * i + 1] * y + pos[3 * i + 2] * z;\n"
         "    if (d > bestDot) { bestDot = d; best = i; }\n  }\n"
         "  return best < 0 ? -1 : data.c[best];\n}\n"
         "try {\n  const mod = await import('/static/layers.js');\n"
         "  layerHooks = mod.init({ THREE, globe, camera, renderer, nearestCountry }) || {};\n"
         "} catch (e) {\n  console.error('Live layers failed to load', e);\n}\n\n"
         "// ---------- render loop ----------\n"),
        ("  pendingHover = null;\n",
         "  pendingHover = null;\n  if (layerHooks.onFrame) layerHooks.onFrame(now, dt);\n"),
    ],
    static / "globe.html": [
        ('<canvas id="globe"></canvas>\n',
         '<canvas id="globe"></canvas>\n<div id="layers"></div>\n<p id="status"></p>\n'),
        ('<p class="muted">No live feeds connected yet. They will appear here as they are added.</p>',
         '<div id="pevents"></div>'),
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
