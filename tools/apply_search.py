import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"

for rel in ("search.py", "static/hub/search.js", "static/hub/search.css"):
    if not (app / rel).exists():
        sys.exit(f"STOPPED, nothing changed. {rel} is missing. Unpack xyron-search.zip into ~/xyron first.")

LAYER_LISTENER = '''  chipsEl.after(sportRow);

  // the search bar can switch a layer on, so a result is never invisible
  window.addEventListener('xyron-enable-layer', (ev) => {
    const id = ev.detail;
    if (typeof id !== 'string' || enabled.has(id) || !layers.some((l) => l.id === id && l.live)) return;
    enabled.add(id);
    saveEnabled(enabled);
    broadcast();
    renderChips();
    renderSportChips();
    rebuildMarkers();
    renderList();
    renderStatus();
  });
'''
FLIGHT_LISTENER = '''  setEnabled(readEnabled().has('aviation'));

  // the search bar asks for an aircraft by its ICAO24 address
  window.addEventListener('xyron-select-flight', (ev) => {
    const d = ev.detail || {};
    const go = () => {
      const i = meta.findIndex((f) => f[0] === d.icao24);
      if (i < 0) return false;
      select(i);
      return true;
    };
    if (go()) return;
    if (typeof d.lat === 'number' && typeof d.lon === 'number') flyTo(d.lat, d.lon, 2.4);
    let tries = 0; // the layer may only just have been switched on, so wait for its first data
    const t = setInterval(() => { if (go() || ++tries > 24) clearInterval(t); }, 500);
  });
'''



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
    if "search.router" in text:
        return text, "already"
    out = add_imports(text, ["search"])
    if out is None:
        return None, "could not find the 'from . import ...' line"
    m = re.search(r"^app\.include_router\(ships\.router\)[ \t]*$", out, re.M)
    if not m:
        routers = list(re.finditer(r"^app\.include_router\([^\n]*\)[ \t]*$", out, re.M))
        if not routers:
            return None, "could not find where the routes are added"
        m = routers[-1]
    return out[:m.end()] + "\napp.include_router(search.router)" + out[m.end():], "ok"


def patch_html(text):
    if "hub/search.js" in text:
        return text, "already"
    css = list(re.finditer(r'^[ \t]*<link rel="stylesheet" href="/static/hub/[^"]+\.css">[ \t]*$', text, re.M))
    mk = re.search(r'^[ \t]*<script src="/static/hub/markets\.js" defer></script>[ \t]*$', text, re.M)
    js = [mk] if mk else list(re.finditer(r'^[ \t]*<script src="/static/hub/[^"]+\.js" defer></script>[ \t]*$', text, re.M))[-1:]
    if not css or not js:
        return None, "could not find the hub stylesheet and script tags"
    text = text[:js[-1].end()] + '\n<script src="/static/hub/search.js" defer></script>' + text[js[-1].end():]
    text = text[:css[-1].end()] + '\n<link rel="stylesheet" href="/static/hub/search.css">' + text[css[-1].end():]
    return text, "ok"


def exact(pairs, marker):
    """The two script files are patched at exact spots (they have not changed shape), skipped if already done."""
    def fn(text):
        if marker in text:
            return text, "already"
        for old, new in pairs:
            if text.count(old) != 1:
                return None, f"could not find exactly one match for {old.strip()[:70]!r}"
            text = text.replace(old, new)
        return text, "ok"
    return fn


layers_fn = exact([
    ("  chipsEl.after(sportRow);\n", LAYER_LISTENER),
    ("    if (typeof d.lat === 'number' && typeof d.lon === 'number') flyTo(d.lat, d.lon, 2.2);\n",
     "    if (typeof d.lat === 'number' && typeof d.lon === 'number') flyTo(d.lat, d.lon, typeof d.zoom === 'number' ? d.zoom : 2.2);\n"),
], "xyron-enable-layer")
aviation_fn = exact([("  setEnabled(readEnabled().has('aviation'));\n", FLIGHT_LISTENER)], "xyron-select-flight")

results = {}
for path, fn, pattern in ((app / "main.py", patch_main, r"^from \.|include_router"), (static / "globe.html", patch_html, r"/static/hub/"),
                          (static / "layers.js", layers_fn, r"sportRow|flyTo\(d\.lat"), (static / "aviation.js", aviation_fn, r"setEnabled\(readEnabled")):
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
