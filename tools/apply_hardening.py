import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"

if not (app / "hardening.py").exists():
    sys.exit("STOPPED, nothing changed. api/app/hardening.py is missing. Unpack xyron-safety.zip into ~/xyron first.")

MIDDLEWARE = ('app.middleware("http")(hardening.extra_headers)\n'
              'app.middleware("http")(hardening.body_limit)\n'
              'app.middleware("http")(hardening.origin_guard)\n'
              'app.middleware("http")(hardening.host_guard)\n')


def show(text, pattern, label):
    lines = [f"  {i + 1}: {l}" for i, l in enumerate(text.splitlines()) if re.search(pattern, l)]
    return f"{label}:\n" + ("\n".join(lines[:8]) if lines else "  (none found)")


def add_import(text):
    """Add 'hardening' to the app's own 'from . import a, b, c' line, whatever else is on it."""
    m = re.search(r"^from \. import \(([^)]*)\)[ \t]*$", text, re.M) or re.search(r"^from \. import ([^(\n]*,[^\n]*|[A-Za-z_]+)[ \t]*$", text, re.M)
    if not m:
        return None
    names = [n.strip() for n in m.group(1).replace("\n", " ").split(",") if n.strip()]
    if "hardening" in names:
        return text
    names = sorted(set(names) | {"hardening"})
    new = "from . import (" + ", ".join(names) + ")" if m.group(0).rstrip().endswith(")") else "from . import " + ", ".join(names)
    return text[:m.start()] + new + text[m.end():]


def patch_main(text):
    if "hardening.origin_guard" in text:
        return text, "already"
    out = add_import(text)
    if out is None:
        return None, "could not find the 'from . import ...' line"
    m = re.search(r"^app\.include_router\(accounts\.router\)[ \t]*$", out, re.M)
    if m:
        return out[:m.end() + 1] + MIDDLEWARE + out[m.end() + 1:], "ok"
    m = re.search(r'^@app\.middleware\("http"\)', out, re.M)
    if m:
        return out[:m.start()] + MIDDLEWARE + "\n" + out[m.start():], "ok"
    return None, "could not find where the app is set up"


def patch_deps(text):
    if "hardening.client_ip" in text:
        return text, "already"
    m = re.search(r"^from \. import [^\n]+$", text, re.M) or re.search(r"^from \.[A-Za-z_. ]* import [^\n]+$", text, re.M)
    if not m:
        return None, "could not find the imports"
    text = text[:m.start()] + "from . import hardening\n" + text[m.start():]
    f = re.search(r"^def client_ip\(([^)]*)\)[^\n]*:\n(?:[ \t]+[^\n]*\n|\n(?=[ \t]))+", text, re.M)
    if not f:
        return None, "could not find the client_ip function"
    arg = f.group(1).split(":")[0].strip() or "request"
    return text[:f.start()] + f"def client_ip({arg}: Request) -> str:\n    return hardening.client_ip({arg})\n" + text[f.end():], "ok"


results = {}
for name, fn in (("main.py", patch_main), ("deps.py", patch_deps)):
    path = app / name
    if not path.exists():
        sys.exit(f"STOPPED, nothing changed. {path} is missing.")
    old = path.read_text()
    new, why = fn(old)
    if new is None:
        print(f"STOPPED, nothing changed. {name}: {why}.")
        print(show(old, r"^from \.|include_router|app\.middleware|def client_ip|request\.client", f"What {name} contains"))
        print("Send me the lines above and I will adjust the patch.")
        sys.exit(1)
    results[path] = (new, why)
if all(why == "already" for _n, why in results.values()):
    sys.exit("STOPPED, nothing changed. This patch has already been applied.")
for path, (new, why) in results.items():
    if why != "already":
        path.write_text(new)
    print(("patched " if why != "already" else "already patched: ") + path.name)
