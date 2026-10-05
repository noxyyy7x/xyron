import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
layers_js = root / "api" / "app" / "static" / "layers.js"

edits = [
    # refresh can now be asked to update only some layers
    ("  async function refresh() {\n"
     "    try {\n"
     "      layers = await getJSON('/api/layers');\n"
     "      const live = layers.filter((l) => l.live).map((l) => l.id).join(',');\n"
     "      const raw = live ? await getJSON('/api/events?hours=24&layers=' + live) : [];\n"
     "      events = raw.map((r) => {\n",
     "  async function refresh(only) {\n"
     "    try {\n"
     "      const subset = Array.isArray(only) ? only : null;\n"
     "      layers = await getJSON('/api/layers');\n"
     "      const live = layers.filter((l) => l.live && (!subset || subset.includes(l.id))).map((l) => l.id).join(',');\n"
     "      const raw = live ? await getJSON('/api/events?hours=24&layers=' + live) : [];\n"
     "      const fresh = raw.map((r) => {\n"),
    ("        e.color = st.color(e);\n        return e;\n      });\n",
     "        e.color = st.color(e);\n        return e;\n      });\n"
     "      events = subset ? events.filter((e) => !subset.includes(e.layer)).concat(fresh) : fresh;\n"),
    # everything every 5 minutes, but while a game is on, only the match layers every 20 seconds
    ("  setInterval(refresh, 300000);\n",
     "  setInterval(() => refresh(), 300000);\n"
     "  setInterval(() => {\n"
     "    const ids = ['football', 'sports'].filter((id) => enabled.has(id));\n"
     "    const gameOn = events.some((e) => ids.includes(e.layer) && e.detail && e.detail.state === 'in');\n"
     "    if (gameOn && !document.hidden) refresh(ids);\n"
     "  }, 20000);\n"),
]

text = layers_js.read_text()
for old, new in edits:
    if text.count(old) != 1:
        sys.exit(f"STOPPED, nothing changed. Could not find exactly one match in layers.js for:\n{old[:200]!r}")
    text = text.replace(old, new)
layers_js.write_text(text)
print("patched layers.js")
