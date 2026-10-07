#!/usr/bin/env python3
"""Soak logger: writes one line of health numbers every 5 minutes, so a day or two of running can be summarised afterwards.

Start:   sudo systemd-run --unit=xyron-soak --working-directory=/home/xyron/xyron python3 tools/soak.py
Stop:    sudo systemctl stop xyron-soak
Report:  sudo python3 tools/soak_report.py
"""
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit import Ctx, decode_throttled, parse_meminfo  # noqa: E402

CSV_PATH = os.environ.get("XYRON_SOAK_CSV", "/var/log/xyron-soak.csv")
EVERY = 300
FIELDS = ["ts", "load5", "temp_c", "throttled_now", "throttled_past", "mem_avail_mb", "swap_used_mb", "disk_free_gb", "api_cpu", "api_mem_mb", "db_cpu", "db_mem_mb",
          "redis_mem_mb", "restarts", "db_size_mb", "tracebacks", "warnings", "errors", "health_ok"]


def mib(text):
    m = re.match(r"([\d.]+)\s*([KMG]i?B)", text.strip())
    if not m:
        return 0.0
    return float(m.group(1)) * {"KB": 1 / 1024, "KIB": 1 / 1024, "MB": 1, "MIB": 1, "GB": 1024, "GIB": 1024}[m.group(2).upper()]


def parse_stats(text):
    """docker stats lines 'name|cpu%|used / limit' -> {role: (cpu, mem_mb)}."""
    out = {}
    for line in (text or "").splitlines():
        p = line.split("|")
        if len(p) < 3:
            continue
        role = "api" if "api" in p[0] else "db" if "db" in p[0] else "redis" if "redis" in p[0] else None
        if role:
            out[role] = (float(p[1].strip().rstrip("%") or 0), mib(p[2].split("/")[0]))
    return out


def collect(c):
    row = dict.fromkeys(FIELDS, "")
    row["ts"] = datetime.fromtimestamp(c.now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    la = (c.read("/proc/loadavg") or "").split()
    row["load5"] = la[1] if len(la) > 1 else ""
    t = c.read("/sys/class/thermal/thermal_zone0/temp")
    row["temp_c"] = f"{int(t.strip()) / 1000:.1f}" if t and t.strip().isdigit() else ""
    rc, o, _ = c.sh("vcgencmd get_throttled")
    d = decode_throttled(o) if rc == 0 else None
    row["throttled_now"], row["throttled_past"] = ("|".join(d[0]), "|".join(d[1])) if d else ("", "")
    mi = parse_meminfo(c.read("/proc/meminfo"))
    row["mem_avail_mb"] = f"{mi.get('MemAvailable', 0) / 1048576:.0f}" if mi else ""
    row["swap_used_mb"] = f"{(mi.get('SwapTotal', 0) - mi.get('SwapFree', 0)) / 1048576:.0f}" if mi else ""
    u = c.usage("/")
    row["disk_free_gb"] = f"{u[0] / 1e9:.1f}" if u else ""
    rc, o, _ = c.sh(["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"], timeout=40)
    st = parse_stats(o) if rc == 0 else {}
    for role in ("api", "db"):
        if role in st:
            row[f"{role}_cpu"], row[f"{role}_mem_mb"] = f"{st[role][0]:.1f}", f"{st[role][1]:.0f}"
    if "redis" in st:
        row["redis_mem_mb"] = f"{st['redis'][1]:.0f}"
    rc, o, _ = c.sh(["docker", "ps", "-a", "--format", "{{.Names}}"])
    total = 0
    for n in o.split():
        rc2, o2, _ = c.sh(["docker", "inspect", "-f", "{{.RestartCount}}", n])
        total += int(o2.strip() or 0) if o2.strip().isdigit() else 0
    row["restarts"] = total
    rc, o, _ = c.psql("select pg_database_size(current_database()) / 1048576")
    row["db_size_mb"] = o if rc == 0 and o.isdigit() else ""
    rc, o, _ = c.compose("logs", "--since", "5m", "api", timeout=40)
    lines = o.splitlines()
    row["tracebacks"] = len([l for l in lines if "Traceback (most recent call last)" in l])
    row["warnings"] = len([l for l in lines if re.search(r"\bWARNING\b", l)])
    row["errors"] = len([l for l in lines if re.search(r"\b(ERROR|CRITICAL)\b", l)])
    rc, o, _ = c.sh(["curl", "-s", "-m", "5", "http://127.0.0.1:8000/health"])
    row["health_ok"] = 1 if '"status":"ok"' in o.replace(" ", "") else 0
    return row


def append(path, row):
    new = not Path(path).exists() or Path(path).stat().st_size == 0
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent
    ctx = Ctx(os.environ.get("XYRON_DIR", str(here)))
    if "--once" in sys.argv:
        ctx.now = time.time()
        print(collect(ctx))
        sys.exit(0)
    print(f"soak logger started, writing to {CSV_PATH} every {EVERY} s", flush=True)
    while True:
        ctx.now = time.time()
        try:
            append(CSV_PATH, collect(ctx))
        except Exception as e:  # keep logging through any hiccup
            print("sample failed:", type(e).__name__, e, flush=True)
        time.sleep(EVERY)
