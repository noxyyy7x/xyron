import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"

if not (app / "hardening.py").exists():
    sys.exit("STOPPED, nothing changed. api/app/hardening.py is missing. Unpack xyron-safety.zip into ~/xyron first.")
if "hardening" in (app / "main.py").read_text():
    sys.exit("STOPPED, nothing changed. This patch has already been applied.")

edits = {
    app / "main.py": [
        ("from . import accounts, aviation, events, football, hazards, markets, news, pages, search, ships, sports, weather\n",
         "from . import accounts, aviation, events, football, hardening, hazards, markets, news, pages, search, ships, sports, weather\n"),
        ("app.include_router(accounts.router)\n",
         "app.include_router(accounts.router)\n"
         "app.middleware(\"http\")(hardening.extra_headers)\n"
         "app.middleware(\"http\")(hardening.body_limit)\n"
         "app.middleware(\"http\")(hardening.origin_guard)\n"
         "app.middleware(\"http\")(hardening.host_guard)\n"),
    ],
    app / "deps.py": [
        ("from . import security as sec\n", "from . import hardening\nfrom . import security as sec\n"),
        ('    return request.client.host if request.client else "unknown"\n', "    return hardening.client_ip(request)\n"),
    ],
}
new_text = {}
for path, pairs in edits.items():
    text = path.read_text()
    for old, new in pairs:
        if text.count(old) != 1:
            sys.exit(f"STOPPED, nothing changed. Could not find exactly one match in {path.name} for:\n{old[:160]!r}")
        text = text.replace(old, new)
    new_text[path] = text
for path, text in new_text.items():
    path.write_text(text)
    print("patched", path.name)
