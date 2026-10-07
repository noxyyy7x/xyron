import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"

for rel in ("recovery.py", "recovery_cli.py", "static/reset.html", "static/reset.js", "static/login-extra.js", "static/hub/security.js", "static/hub/security.css"):
    if not (app / rel).exists():
        sys.exit(f"STOPPED, nothing changed. {rel} is missing. Unpack xyron-recovery.zip into ~/xyron first.")

RESET_2FA_FN = '''async function reset2fa(u) {
  if (!confirm('Reset the authenticator for ' + u.email + '?\\n\\nThey will be signed out everywhere, their recovery codes stop working, and they are emailed a one-time link to set up a new authenticator.')) return;
  try {
    // not the page's api() helper: that sends any "forbidden" answer to the home page, and here the reason should be shown
    const res = await fetch('/admin/users/' + u.id + '/reset-2fa', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    if (res.status === 401) { location.href = '/login'; return; }
    const r = await res.json().catch(() => ({}));
    if (!res.ok) { show(typeof r.detail === 'string' ? r.detail : 'Request failed', false); return; }
    show(r.emailed ? 'Authenticator reset. A setup link was emailed to ' + u.email + '.' : 'Authenticator reset, but the setup email could not be sent. Check the mail settings.', r.emailed);
    await load();
  } catch (e) {
    show('Could not reach the server.', false);
  }
}

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
    if "recovery.router" in text:
        return text, "already"
    out = add_imports(text, ["recovery"])
    if out is None:
        return None, "could not find the 'from . import ...' line"
    m = re.search(r"^app\.include_router\(accounts\.router\)[ \t]*$", out, re.M)
    if not m:
        return None, "could not find where the account routes are added"
    return out[:m.end()] + "\napp.include_router(recovery.router)" + out[m.end():], "ok"


def patch_globe(text):
    if "hub/security.js" in text:
        return text, "already"
    css = list(re.finditer(r'^[ \t]*<link rel="stylesheet" href="/static/hub/[^"]+\.css">[ \t]*$', text, re.M))
    js = list(re.finditer(r'^[ \t]*<script src="/static/hub/[^"]+\.js" defer></script>[ \t]*$', text, re.M))
    if not css or not js:
        return None, "could not find the hub stylesheet and script tags"
    text = text[:js[-1].end()] + '\n<script src="/static/hub/security.js" defer></script>' + text[js[-1].end():]
    text = text[:css[-1].end()] + '\n<link rel="stylesheet" href="/static/hub/security.css">' + text[css[-1].end():]
    return text, "ok"


def patch_login(text):
    if "login-extra.js" in text:
        return text, "already"
    m = re.search(r'<script src="/static/login\.js"></script>', text)
    if not m:
        return None, "could not find the sign-in script tag"
    return text[:m.start()] + '<script src="/static/login-extra.js"></script>\n' + text[m.start():], "ok"  # ours goes first, so in recovery mode it takes over the submit


def patch_admin(text):
    if "reset-2fa" in text:
        return text, "already"
    fn = re.search(r"^function render\(users\) \{", text, re.M)
    btn = re.search(r"^([ \t]*)actions\.appendChild\(button\('Suspend'[^\n]*\n", text, re.M)
    if not fn or not btn:
        return None, "could not find the user list code"
    text = text[:btn.end()] + f"{btn.group(1)}actions.appendChild(button('Reset 2FA', 'secondary', () => reset2fa(u)));\n" + text[btn.end():]
    return text[:fn.start()] + RESET_2FA_FN + text[fn.start():], "ok"


results = {}
for path, fn, pattern in ((app / "main.py", patch_main, r"^from \.|include_router"), (static / "globe.html", patch_globe, r"/static/hub/"),
                          (static / "login.html", patch_login, r"script"), (static / "admin.js", patch_admin, r"function render|Suspend")):
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
