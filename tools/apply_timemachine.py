import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"

for rel in ("timemachine.py", "static/hub/timemachine.js", "static/hub/timemachine.css"):
    if not (app / rel).exists():
        sys.exit(f"STOPPED, nothing changed. {rel} is missing. Unpack xyron-timemachine.zip into ~/xyron first.")


def show(text, pattern, label):
    lines = [f"  {i + 1}: {l}" for i, l in enumerate(text.splitlines()) if re.search(pattern, l)]
    return f"{label}:\n" + ("\n".join(lines[:8]) if lines else "  (none found)")


def add_imports(text, new):
    m = re.search(r"^from \. import \(([^)]*)\)[ \t]*$", text, re.M) or re.search(r"^from \. import ([^(\n]*,[^\n]*|[A-Za-z_]+)[ \t]*$", text, re.M)
    if not m:
        return None
    names = [n.strip() for n in m.group(1).replace("\n", " ").split(",") if n.strip()]
    names = sorted(set(names) | set(new))
    line = "from . import (" + ", ".join(names) + ")" if m.group(0).rstrip().endswith(")") else "from . import " + ", ".join(names)
    return text[:m.start()] + line + text[m.end():]


def patch_main(text):
    if "timemachine.router" in text:
        return text, "already"
    out = add_imports(text, ["timemachine"])
    if out is None:
        return None, "could not find the 'from . import ...' line"
    tasks = list(re.finditer(r"^([ \t]+)asyncio\.create_task\([A-Za-z_]+\.ingest_loop\(\)\),[ \t]*$", out, re.M))
    if not tasks:
        return None, "could not find the list of background tasks"
    out = out[:tasks[-1].end()] + f"\n{tasks[-1].group(1)}asyncio.create_task(timemachine.ingest_loop())," + out[tasks[-1].end():]
    routers = list(re.finditer(r"^app\.include_router\([^\n]*\)[ \t]*$", out, re.M))
    if not routers:
        return None, "could not find where the routes are added"
    return out[:routers[-1].end()] + "\napp.include_router(timemachine.router)" + out[routers[-1].end():], "ok"


def patch_html(text):
    if "hub/timemachine.js" in text:
        return text, "already"
    css = list(re.finditer(r'^[ \t]*<link rel="stylesheet" href="/static/hub/[^"]+\.css">[ \t]*$', text, re.M))
    js = list(re.finditer(r'^[ \t]*<script src="/static/hub/[^"]+\.js" defer></script>[ \t]*$', text, re.M))
    if not css or not js:
        return None, "could not find the hub stylesheet and script tags"
    text = text[:js[-1].end()] + '\n<script src="/static/hub/timemachine.js" defer></script>' + text[js[-1].end():]
    text = text[:css[-1].end()] + '\n<link rel="stylesheet" href="/static/hub/timemachine.css">' + text[css[-1].end():]
    return text, "ok"


GLOBE_HOOK = """// the time machine draws on this same globe
window.xyronGlobe = { THREE, globe, camera, renderer, canvas, flyTo };
window.dispatchEvent(new CustomEvent('xyron-globe-ready'));

"""


def patch_globe(text):
    if "window.xyronGlobe" in text:
        return text, "already"
    m = re.search(r"^// -+ render loop -+[ \t]*$", text, re.M)
    if not m:
        return None, "could not find the start of the render loop"
    return text[:m.start()] + GLOBE_HOOK + text[m.start():], "ok"


def patch_ships(text):
    if "TRACK_HISTORY_HOURS" in text:
        return text, "already"
    a = re.search(r"^TRACK_KEEP_HOURS = \d+[^\n]*$", text, re.M)
    b = re.search(r'(conn\.execute\("DELETE FROM vessel_track WHERE ts < now\(\) - make_interval\(hours => %s\)", \()TRACK_KEEP_HOURS(,\)\))', text)
    if not a or not b:
        return None, "could not find the ship track settings"
    text = text[:b.start()] + b.group(1) + "max(TRACK_KEEP_HOURS, TRACK_HISTORY_HOURS)" + b.group(2) + text[b.end():]
    return text[:a.end()] + "\nTRACK_HISTORY_HOURS = 192   # tracks are kept 8 days for the time machine; the trail shown on a ship stays as it was" + text[a.end():], "ok"


results = {}
for path, fn, pattern in ((app / "main.py", patch_main, r"^from \.|create_task|include_router"), (static / "globe.html", patch_html, r"/static/hub/"),
                          (static / "globe.js", patch_globe, r"render loop"), (app / "ships.py", patch_ships, r"TRACK_KEEP_HOURS|DELETE FROM vessel_track")):
    if not path.exists():
        sys.exit(f"STOPPED, nothing changed. {path} is missing.")
    old = path.read_text()
    new, why = fn(old)
    if new is None:
        print(f"STOPPED, nothing changed. {path.name}: {why}.")
        print(show(old, pattern, f"What {path.name} contains"))
        print("Send me the lines above and I will adjust the patch.")
        sys.exit(1)
    results[path] = (new, why)
if all(why == "already" for _n, why in results.values()):
    sys.exit("STOPPED, nothing changed. This patch has already been applied.")
for path, (new, why) in results.items():
    if why != "already":
        path.write_text(new)
    print(("patched " if why != "already" else "already patched: ") + path.name)
