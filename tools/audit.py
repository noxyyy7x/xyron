#!/usr/bin/env python3
"""XYRON audit: a read-only health and security check of the Pi and the app. It changes nothing and never prints a secret.

Run it from the project folder:   sudo python3 tools/audit.py
"""
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
REQUIRED_ENV = ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "REDIS_PASSWORD", "SECRET_KEY"]
SENSITIVE = re.compile(r"(PASSWORD|SECRET|KEY|TOKEN)")


class Ctx:
    """Everything the checks touch on the machine, in one place, so the checks can be tested with pretend answers."""

    def __init__(self, project):
        self.project = Path(project)
        self.now = time.time()

    def sh(self, cmd, timeout=25):
        try:
            p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
            return p.returncode, p.stdout or "", p.stderr or ""
        except FileNotFoundError:
            return 127, "", "command not found"
        except subprocess.TimeoutExpired:
            return 124, "", "timed out"

    def read(self, path):
        try:
            return Path(path).read_text(errors="ignore")
        except OSError:
            return None

    def exists(self, path):
        return Path(path).exists()

    def mode(self, path):
        try:
            st = Path(path).stat()
            return stat.S_IMODE(st.st_mode), st.st_uid
        except OSError:
            return None

    def mtime(self, path):
        try:
            return Path(path).stat().st_mtime
        except OSError:
            return None

    def listdir(self, path):
        try:
            return sorted(p.name for p in Path(path).iterdir())
        except OSError:
            return []

    def size(self, path):
        try:
            return Path(path).stat().st_size
        except OSError:
            return None

    def usage(self, path):
        try:
            u = os.statvfs(path)
            return u.f_bavail * u.f_frsize, u.f_blocks * u.f_frsize
        except OSError:
            return None

    def compose(self, *args, timeout=25):
        return self.sh(["docker", "compose", "--project-directory", str(self.project), *args], timeout)

    def psql(self, sql, db=None, timeout=25):
        env = parse_env(self.read(self.project / ".env") or "")
        user, name = env.get("POSTGRES_USER", "xyron"), db or env.get("POSTGRES_DB", "xyron")
        rc, out, err = self.compose("exec", "-T", "db", "psql", "-U", user, "-d", name, "-At", "-F", "|", "-c", sql, timeout=timeout)
        return rc, out.strip(), err.strip()


# ---------- small parsers (tested on their own) ----------
def parse_env(text):
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def env_duplicates(text):
    counts = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k = line.split("=", 1)[0].strip()
            counts[k] = counts.get(k, 0) + 1
    return sorted(k for k, n in counts.items() if n > 1)


def parse_ss(text):
    """(address, port) for every listening TCP socket."""
    out = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3] if parts[0] in ("LISTEN", "UNCONN") else parts[3 if len(parts) > 3 else -1]
        m = re.match(r"^(\[?[^\]]+\]?|\*):(\d+)$", local)
        if m:
            out.append((m.group(1).strip("[]"), int(m.group(2))))
    return out


def public_listeners(sockets, allowed=(22,)):
    return sorted({(a, p) for a, p in sockets if a in ("0.0.0.0", "::", "*") and p not in allowed})


def parse_sshd(text):
    return {l.split(None, 1)[0].lower(): l.split(None, 1)[1].strip().lower() for l in (text or "").splitlines() if len(l.split(None, 1)) == 2}


def decode_throttled(value):
    """vcgencmd get_throttled -> (problems right now, problems since boot)."""
    try:
        n = int(value.strip().split("=")[-1], 16)
    except ValueError:
        return None
    now = [name for bit, name in ((0, "under-voltage"), (1, "frequency capped"), (2, "throttled"), (3, "soft temperature limit")) if n & (1 << bit)]
    past = [name for bit, name in ((16, "under-voltage"), (17, "frequency capped"), (18, "throttled"), (19, "soft temperature limit")) if n & (1 << bit)]
    return now, past


def parse_meminfo(text):
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"(\w+):\s+(\d+)", line)
        if m:
            out[m.group(1)] = int(m.group(2)) * 1024
    return out


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def age_text(seconds):
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"


# ---------- the checks ----------
def check_system(c):
    out = []
    rc, o, _ = c.sh("cat /etc/os-release | grep PRETTY_NAME")
    rc2, up, _ = c.sh("uptime -p")
    out.append((INFO, "System", (o.split("=", 1)[-1].strip().strip('"') + ", " + up.strip()).strip(", ")))
    rc, o, _ = c.sh("apt list --upgradable 2>/dev/null")
    n = max(0, len([l for l in o.splitlines() if "/" in l]))
    out.append((PASS if n == 0 else WARN if n <= 25 else FAIL, "Waiting software updates", f"{n} package(s)" + ("" if n == 0 else ". Run: sudo apt update && sudo apt upgrade")))
    rc, o, _ = c.sh("systemctl is-enabled apt-daily-upgrade.timer")
    rc2, o2, _ = c.sh("systemctl is-active unattended-upgrades")
    ok = o.strip() == "enabled" and o2.strip() in ("active", "inactive")
    out.append((PASS if ok else WARN, "Automatic security updates", "on" if ok else "not enabled. Run: sudo dpkg-reconfigure -plow unattended-upgrades"))
    if c.exists("/var/run/reboot-required"):
        out.append((WARN, "Reboot needed", "an update is waiting for a restart"))
    rc, o, _ = c.sh("timedatectl show -p NTPSynchronized --value")
    out.append((PASS if o.strip() == "yes" else WARN, "Clock is synchronised", o.strip() or "unknown"))
    return out


def check_hardware(c):
    out = []
    t = c.read("/sys/class/thermal/thermal_zone0/temp")
    if t and t.strip().isdigit():
        deg = int(t.strip()) / 1000
        out.append((PASS if deg < 70 else WARN if deg < 80 else FAIL, "Temperature", f"{deg:.1f} \u00b0C" + ("" if deg < 70 else ". Check the case, fan and airflow")))
    rc, o, _ = c.sh("vcgencmd get_throttled")
    d = decode_throttled(o) if rc == 0 else None
    if d is None:
        out.append((INFO, "Power and throttling", "not available on this system"))
    elif d[0]:
        out.append((FAIL, "Power and throttling", "happening NOW: " + ", ".join(d[0]) + ". Use the official power supply and check the cable"))
    elif d[1]:
        out.append((WARN, "Power and throttling", "happened since boot: " + ", ".join(d[1]) + ". Check the power supply"))
    else:
        out.append((PASS, "Power and throttling", "no under-voltage or throttling since boot"))
    mi = parse_meminfo(c.read("/proc/meminfo"))
    if mi.get("MemTotal"):
        avail = mi.get("MemAvailable", 0)
        out.append((PASS if avail > 600e6 else WARN if avail > 250e6 else FAIL, "Free memory", f"{human(avail)} available of {human(mi['MemTotal'])}"))
        if mi.get("SwapTotal"):
            used = mi["SwapTotal"] - mi.get("SwapFree", 0)
            out.append((PASS if used < 0.5 * mi["SwapTotal"] else WARN, "Swap in use", f"{human(used)} of {human(mi['SwapTotal'])}"))
    la = (c.read("/proc/loadavg") or "").split()
    if la:
        v = float(la[1])
        out.append((PASS if v < 3 else WARN if v < 4.5 else FAIL, "Load (5 min average, 4 cores)", f"{v:.2f}"))
    for path, label in (("/", "Disk space on the main drive"), ("/mnt/backup", "Disk space on the backup drive")):
        u = c.usage(path)
        if u is None:
            out.append((WARN if path == "/mnt/backup" else FAIL, label, "not found or not mounted"))
            continue
        free, total = u
        pct = 100 * free / total if total else 0
        out.append((PASS if pct > 20 else WARN if pct > 10 else FAIL, label, f"{human(free)} free ({pct:.0f}%)"))
    return out


def check_network(c):
    out = []
    rc, o, e = c.sh("sshd -T")
    cfg = parse_sshd(o) if rc == 0 else {}
    if not cfg:
        out.append((WARN, "SSH settings", "could not be read (run with sudo)"))
    else:
        out.append((PASS if cfg.get("passwordauthentication") == "no" else FAIL, "SSH passwords are off (keys only)", "passwordauthentication " + cfg.get("passwordauthentication", "?")))
        out.append((PASS if cfg.get("permitrootlogin") in ("no", "prohibit-password", "without-password") else FAIL, "SSH root login", cfg.get("permitrootlogin", "?")))
        out.append((PASS if cfg.get("permitemptypasswords", "no") == "no" else FAIL, "SSH empty passwords", cfg.get("permitemptypasswords", "no")))
        out.append((PASS if int(cfg.get("maxauthtries", "6") or 6) <= 4 else INFO, "SSH tries per connection", cfg.get("maxauthtries", "?")))
    rc, o, e = c.sh("ufw status verbose")
    if rc != 0:
        out.append((WARN, "Firewall (ufw)", "could not be read (run with sudo)"))
    else:
        active = "status: active" in o.lower()
        deny = "deny (incoming)" in o.lower()
        ports = sorted(set(re.findall(r"^(\d+)(?:/tcp)?\s+ALLOW", o, re.M)))
        out.append((PASS if active and deny else FAIL, "Firewall is on and blocks incoming by default", "active" if active else "NOT active"))
        extra = [p for p in ports if p != "22"]
        out.append((PASS if not extra else INFO, "Ports the firewall allows in", ", ".join(ports) or "none" + ("" if not extra else "  (80/443 are expected once the domain is set up)")))
    rc, o, e = c.sh("fail2ban-client status sshd")
    if rc != 0:
        out.append((WARN, "fail2ban (SSH protection)", "not running or not readable"))
    else:
        failed = re.search(r"Currently failed:\s+(\d+)", o)
        banned = re.search(r"Currently banned:\s+(\d+)", o)
        out.append((PASS, "fail2ban (SSH protection)", f"running; banned now {banned.group(1) if banned else '?'}, failing now {failed.group(1) if failed else '?'}"))
    rc, o, _ = c.sh("ss -H -tln")
    pub = public_listeners(parse_ss(o))
    out.append((PASS if not pub else FAIL, "Nothing listens to the network except SSH", "ok" if not pub else "open to the network: " + ", ".join(f"{a}:{p}" for a, p in pub)))
    rc, o, _ = c.sh(["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"])
    if rc == 0:
        bad = [l.split("\t")[0] for l in o.splitlines() if "\t" in l and re.search(r"(^|, )(0\.0\.0\.0:\d+|:::\d+|\[::\]:\d+)->", l.split("\t", 1)[1])]
        out.append((PASS if not bad else FAIL, "Docker only publishes ports on this machine itself", "ok" if not bad else "published to the network: " + ", ".join(bad)))
    rc, o, _ = c.sh("hostname -I")
    ip = next((x for x in o.split() if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", x)), None)
    if ip:
        rc, o, _ = c.sh(["curl", "-s", "-m", "3", f"http://{ip}:8000/health"])
        out.append((PASS if rc != 0 or not o.strip() else FAIL, "The app is not reachable from the local network", "ok" if rc != 0 or not o.strip() else f"answers on {ip}:8000"))
    rc, o, _ = c.sh("systemctl is-enabled docker")
    out.append((PASS if o.strip() == "enabled" else FAIL, "Docker starts at boot", o.strip() or "unknown"))
    return out


def check_containers(c):
    out = []
    rc, o, _ = c.sh(["docker", "ps", "-a", "--format", "{{.Names}}"])
    names = o.split()
    if rc != 0 or not names:
        return [(FAIL, "Containers", "none found (is Docker running?)")]
    for n in names:
        rc, o, _ = c.sh(["docker", "inspect", "-f", "{{.HostConfig.RestartPolicy.Name}} {{.State.Status}} {{.RestartCount}}", n])
        pol, status, restarts = (o.split() + ["", "", "0"])[:3]
        good = pol in ("unless-stopped", "always")
        out.append((PASS if good and status == "running" else FAIL if status != "running" else WARN, f"Container {n}", f"{status}, restarts itself: {pol or 'never'}, restarts so far {restarts}"
                    + ("" if good else ". Add 'restart: unless-stopped' to docker-compose.yml")))
    return out


def check_secrets(c):
    out = []
    env_path = c.project / ".env"
    text = c.read(env_path)
    if text is None:
        return [(FAIL, ".env file", "not found")]
    m = c.mode(env_path)
    out.append((PASS if m and m[0] & 0o077 == 0 else FAIL, ".env is private to its owner", f"mode {oct(m[0])[2:]}" if m else "unknown"))
    env = parse_env(text)
    missing = [k for k in REQUIRED_ENV if not env.get(k)]
    out.append((PASS if not missing else FAIL, "Required settings are present", "all set" if not missing else "missing or empty: " + ", ".join(missing)))
    out.append((PASS if len(env.get("SECRET_KEY", "")) >= 32 else FAIL, "SECRET_KEY is long enough", f"{len(env.get('SECRET_KEY', ''))} characters"))
    dups = env_duplicates(text)
    out.append((PASS if not dups else WARN, "No setting appears twice in .env", "ok" if not dups else "repeated: " + ", ".join(dups) + " (the last one wins)"))
    for k in ("AISSTREAM_API_KEY", "FINNHUB_API_KEY"):
        if k in env:
            n = len(env[k])
            rep = n % 3 == 0 and n >= 6 and env[k][: n // 3] * 3 == env[k]
            out.append((FAIL if rep else INFO, f"{k}", f"{n} characters" + (", the same text repeated 3 times: re-enter it once" if rep else "")))
    out.append((INFO, "Cookie and address settings", f"COOKIE_SECURE={env.get('COOKIE_SECURE', '(default true)')}, PUBLIC_BASE_URL={env.get('PUBLIC_BASE_URL', '(default http://localhost:8000)')}"))
    git = ["git", "-C", str(c.project)]
    rc, o, _ = c.sh(git + ["ls-files", "--error-unmatch", ".env"])
    out.append((PASS if rc != 0 else FAIL, ".env is not tracked by git", "ok" if rc != 0 else "it IS tracked! Run: git rm --cached .env"))
    rc, o, _ = c.sh(git + ["log", "--all", "--oneline", "--", ".env"])
    out.append((PASS if not o.strip() else FAIL, ".env has never been committed", "ok" if not o.strip() else "it appears in the history; the secrets in it must be changed"))
    rc, o, _ = c.sh(git + ["grep", "-I", "-n", "-E", r"(API_KEY|SECRET|PASSWORD|PASSWD|TOKEN)[A-Za-z_]*[[:space:]]*[=:][[:space:]]*[\"']?[A-Za-z0-9/+_.-]{20,}", "--", ".", ":!api/app/static/vendor", ":!*.json", ":!*.lock"])
    hits = sorted({":".join(l.split(":", 2)[:2]) for l in o.splitlines() if l.strip()})
    out.append((PASS if not hits else FAIL, "No keys or passwords written into the code", "ok" if not hits else "look at: " + ", ".join(hits[:6])))
    rc, o, _ = c.sh(git + ["status", "--porcelain"])
    n = len([l for l in o.splitlines() if l.strip()])
    out.append((PASS if n == 0 else WARN, "Everything is saved in git", "clean" if n == 0 else f"{n} change(s) not committed. Run: git add -A && git commit -m ... && git push"))
    rc, o, _ = c.sh(git + ["rev-list", "--count", "@{u}..HEAD"])
    out.append((PASS if rc != 0 or o.strip() == "0" else WARN, "Everything is pushed to GitHub", "up to date" if rc != 0 or o.strip() == "0" else f"{o.strip()} commit(s) not pushed"))
    return out


def check_backups(c):
    out = []
    rc, o, _ = c.sh("systemctl is-enabled xyron-backup.timer")
    out.append((PASS if o.strip() == "enabled" else FAIL, "Nightly backup is scheduled", o.strip() or "not found"))
    rc, o, _ = c.sh("systemctl show xyron-backup.service -p Result --value")
    out.append((PASS if o.strip() in ("success", "") else FAIL, "The last backup run", o.strip() or "no result yet"))
    d = "/mnt/backup/pi"
    files = c.listdir(d)
    for prefix, label in (("db-xyron_", "database dump"), ("pi-config_", "system and project archive")):
        mine = sorted(f for f in files if f.startswith(prefix))
        if not mine:
            out.append((FAIL, f"Newest {label}", "none found"))
            continue
        newest = mine[-1]
        t, sz = c.mtime(f"{d}/{newest}"), c.size(f"{d}/{newest}")
        age = c.now - t if t else None
        ok = age is not None and age < 36 * 3600 and (sz or 0) > (200 if prefix == "db-xyron_" else 1_000_000)
        out.append((PASS if ok else WARN, f"Newest {label}", f"{newest}, {human(sz or 0)}, {age_text(age) if age is not None else '?'} old"))
        m = c.mode(f"{d}/{newest}")
        if m and m[0] & 0o077:
            out.append((FAIL, f"{label} is private", f"mode {oct(m[0])[2:]}: anyone on the Pi could read it"))
    out.append((INFO, "Backups kept", f"{len([f for f in files if f.startswith('db-xyron_')])} database dumps, {len([f for f in files if f.startswith('pi-config_')])} archives"))
    return out


def check_app(c):
    out = []
    rc, o, _ = c.sh(["curl", "-s", "-m", "5", "http://127.0.0.1:8000/health"])
    out.append((PASS if '"status":"ok"' in o.replace(" ", "") else FAIL, "The app answers its health check", o.strip()[:90] or "no answer"))
    rc, o, _ = c.sh(["curl", "-s", "-I", "-m", "5", "http://127.0.0.1:8000/login"])
    low = o.lower()
    need = {"x-content-type-options": "nosniff", "x-frame-options": "deny", "referrer-policy": "no-referrer", "content-security-policy": "default-src"}
    miss = [h for h, v in need.items() if h + ":" not in low or v not in low]
    out.append((PASS if not miss else WARN, "Security headers on pages", "ok" if not miss else "missing or weak: " + ", ".join(miss)))
    extra = [h for h in ("permissions-policy", "cross-origin-opener-policy") if h + ":" not in low]
    out.append((PASS if not extra else INFO, "Extra hardening headers", "present" if not extra else "not yet: " + ", ".join(extra) + " (xyron-safety adds them)"))
    rc, o, _ = c.compose("exec", "-T", "redis", "redis-cli", "ping")
    out.append((PASS if "NOAUTH" in o + _ else FAIL, "Redis refuses connections without a password", "ok" if "NOAUTH" in o + _ else (o + _).strip()[:80]))
    rc, o, e = c.psql("select role, status, count(*) from users group by 1, 2 order by 1, 2")
    if rc == 0:
        owner = "owner|active" in o
        out.append((PASS if owner else FAIL, "An active owner account exists", o.replace("\n", "; ") or "no users"))
    rc, o, e = c.psql("select count(*) from audit_log where event = 'login_failed' and ts > now() - interval '24 hours'")
    if rc == 0 and o.isdigit():
        n = int(o)
        out.append((PASS if n < 10 else WARN if n < 50 else FAIL, "Failed sign-in attempts in the last 24 hours", f"{n}"))
    rc, o, e = c.psql("select count(*) from audit_log where event = 'login_blocked' and ts > now() - interval '24 hours'")
    if rc == 0 and o.isdigit() and int(o):
        out.append((WARN, "Sign-ins blocked by the rate limit in the last 24 hours", o))
    return out


def check_data(c):
    out = []
    rc, o, e = c.psql("select pg_size_pretty(pg_database_size(current_database()))")
    if rc != 0:
        return [(FAIL, "Database", "could not be read: " + e[:80])]
    out.append((INFO, "Database size", o))
    rc, o, _ = c.psql("select relname, pg_size_pretty(pg_total_relation_size(c.oid)), reltuples::bigint from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                      "where n.nspname = 'public' and relkind = 'r' order by pg_total_relation_size(c.oid) desc limit 6")
    if rc == 0 and o:
        out.append((INFO, "Biggest tables", "; ".join(f"{r.split('|')[0]} {r.split('|')[1]} (~{int(float(r.split('|')[2])):,} rows)" for r in o.splitlines() if r.count("|") == 2)))
        big = [r.split("|")[0] for r in o.splitlines() if r.count("|") == 2 and float(r.split("|")[2]) > 8_000_000]
        out.append((PASS if not big else WARN, "No table is growing out of hand", "ok" if not big else "over 8 million rows: " + ", ".join(big)))
    rc, o, _ = c.psql("select count(*) from pg_stat_activity where datname = current_database()")
    if rc == 0 and o.isdigit():
        out.append((PASS if int(o) < 40 else WARN, "Database connections", o))
    rc, o, _ = c.compose("logs", "--since", "24h", "api", timeout=40)
    lines = o.splitlines()
    tb = len([l for l in lines if "Traceback (most recent call last)" in l])
    out.append((PASS if tb == 0 else WARN if tb < 5 else FAIL, "Crashes (tracebacks) in the app log, last 24 hours", str(tb)))
    errs = sorted({re.sub(r"^api-1\s+\|\s+", "", l)[:110] for l in lines if re.search(r"\b(ERROR|CRITICAL)\b", l)})
    if errs:
        out.append((WARN, "Errors logged in the last 24 hours", "; ".join(errs[:3])))
    return out


SECTIONS = [("THIS COMPUTER", [check_system, check_hardware]), ("NETWORK AND ACCESS", [check_network]), ("CONTAINERS", [check_containers]),
            ("SECRETS AND CODE", [check_secrets]), ("BACKUPS", [check_backups]), ("THE APP", [check_app, check_data])]


def run_all(c, color=False):
    paint = (lambda s, code: f"\033[{code}m{s}\033[0m") if color else (lambda s, code: s)
    codes = {PASS: "32", WARN: "33", FAIL: "31", INFO: "36"}
    lines, results = [], []
    for title, fns in SECTIONS:
        lines.append("")
        lines.append(paint(f"== {title} ==", "1"))
        for fn in fns:
            try:
                rows = fn(c)
            except Exception as e:  # one broken check must not hide the rest
                rows = [(WARN, fn.__name__, f"the check itself failed: {type(e).__name__}: {str(e)[:80]}")]
            for level, name, detail in rows:
                results.append((level, name, detail))
                lines.append(f"{paint('[' + level + ']', codes[level])} {name}" + (f": {detail}" if detail else ""))
    n = {k: sum(1 for r in results if r[0] == k) for k in (PASS, WARN, FAIL, INFO)}
    lines += ["", paint(f"SUMMARY: {n[PASS]} passed, {n[WARN]} to look at, {n[FAIL]} to fix", "1")]
    todo = [r for r in results if r[0] == FAIL] + [r for r in results if r[0] == WARN]
    if todo:
        lines.append("Fix first:")
        lines += [f"  - {name}: {detail}" if detail else f"  - {name}" for _l, name, detail in todo[:8]]
    return "\n".join(lines), results


if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent
    project = os.environ.get("XYRON_DIR", str(here))
    if os.geteuid() != 0:
        print("Run this with sudo, or several checks cannot be read:  sudo python3 tools/audit.py")
    text, results = run_all(Ctx(project), color=sys.stdout.isatty())
    print(text)
    sys.exit(1 if any(r[0] == FAIL for r in results) else 0)
