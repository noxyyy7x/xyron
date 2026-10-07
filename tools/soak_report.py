#!/usr/bin/env python3
"""Summarises the soak log: is the Pi stable over time? Run: sudo python3 tools/soak_report.py [path-to-csv]"""
import csv
import os
import sys
from datetime import datetime

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
GAP = 12 * 60  # a gap longer than this between samples means the Pi or the logger was down


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["_t"] = datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").timestamp()
    rows.sort(key=lambda r: r["_t"])
    return rows


def series(rows, key):
    return [(r["_t"], num(r.get(key))) for r in rows if num(r.get(key)) is not None]


def stats(vals):
    v = [x for _t, x in vals]
    return (min(v), sum(v) / len(v), max(v)) if v else None


def trend_per_hour(vals):
    """Average of the last tenth minus the first tenth, per hour. Smooths out spikes."""
    if len(vals) < 20:
        return None
    k = max(3, len(vals) // 10)
    a, b = vals[:k], vals[-k:]
    ta, tb = sum(t for t, _ in a) / k, sum(t for t, _ in b) / k
    va, vb = sum(v for _, v in a) / k, sum(v for _, v in b) / k
    hours = (tb - ta) / 3600
    return (vb - va) / hours if hours > 0 else None


def analyse(rows):
    out = []
    if len(rows) < 3:
        return [(WARN, "Not enough data yet", f"{len(rows)} sample(s); let it run for at least a few hours")]
    span = (rows[-1]["_t"] - rows[0]["_t"]) / 3600
    out.append((PASS if span >= 20 else WARN if span >= 6 else FAIL, "How long it ran", f"{span:.1f} hours, {len(rows)} samples" + ("" if span >= 20 else ". A full day gives the best picture")))
    gaps = [(a["_t"], b["_t"]) for a, b in zip(rows, rows[1:]) if b["_t"] - a["_t"] > GAP]
    out.append((PASS if not gaps else WARN, "Gaps in the log (Pi or logger was down)", "none" if not gaps else f"{len(gaps)}: " + "; ".join(f"{datetime.fromtimestamp(a).strftime('%d %b %H:%M')} to {datetime.fromtimestamp(b).strftime('%H:%M')}" for a, b in gaps[:4])))
    h = [r for r in rows if r.get("health_ok") not in ("", None)]
    bad = [r for r in h if r["health_ok"] in ("0", 0)]
    out.append((PASS if not bad else FAIL if len(bad) > 2 else WARN, "The app's health check", "answered every time" if not bad else f"failed {len(bad)} of {len(h)} times"))
    r0, r1 = num(rows[0].get("restarts")), num(rows[-1].get("restarts"))
    if r0 is not None and r1 is not None:
        out.append((PASS if r1 <= r0 else FAIL, "Containers restarting by themselves", "none" if r1 <= r0 else f"{int(r1 - r0)} restart(s) during the run: look at 'docker compose logs api'"))
    tb = sum(int(num(r.get("tracebacks")) or 0) for r in rows)
    out.append((PASS if tb == 0 else WARN if tb < 5 else FAIL, "Crashes (tracebacks) in the app log", str(tb)))
    t = stats(series(rows, "temp_c"))
    if t:
        out.append((PASS if t[2] < 70 else WARN if t[2] < 80 else FAIL, "Temperature", f"lowest {t[0]:.0f}, average {t[1]:.0f}, highest {t[2]:.0f} \u00b0C"))
    now_flags = sorted({f for r in rows for f in (r.get("throttled_now") or "").split("|") if f})
    past_flags = sorted({f for r in rows for f in (r.get("throttled_past") or "").split("|") if f})
    out.append((PASS if not past_flags and not now_flags else FAIL if now_flags else WARN, "Power and throttling", "clean" if not past_flags and not now_flags else "seen: " + ", ".join(now_flags or past_flags) + ". Check the power supply"))
    l = stats(series(rows, "load5"))
    if l:
        out.append((PASS if l[2] < 3 else WARN if l[2] < 4.5 else FAIL, "Load (5 min average, 4 cores)", f"average {l[1]:.2f}, highest {l[2]:.2f}"))
    m = series(rows, "mem_avail_mb")
    if m:
        s = stats(m)
        out.append((PASS if s[0] > 600 else WARN if s[0] > 250 else FAIL, "Free memory", f"lowest {s[0]:.0f} MB, average {s[1]:.0f} MB"))
    for key, label in (("api_mem_mb", "App memory"), ("db_mem_mb", "Database memory")):
        v = series(rows, key)
        if not v:
            continue
        tr, s = trend_per_hour(v), stats(v)
        growth = (v[-1][1] - v[0][1])
        leak = tr is not None and tr > 15 and growth > 150
        out.append((WARN if leak else PASS, label, f"average {s[1]:.0f} MB, highest {s[2]:.0f} MB" + (f", growing about {tr:.0f} MB per hour: a possible leak" if leak else (", steady" if tr is not None else ""))))
    for key, label, unit, warn_per_day in (("db_size_mb", "Database size", "MB", None), ("disk_free_gb", "Free disk space", "GB", None)):
        v = series(rows, key)
        if not v:
            continue
        tr = trend_per_hour(v)
        if key == "db_size_mb" and tr is not None:
            out.append((INFO, label, f"{v[-1][1]:.0f} MB now, growing about {tr * 24:.0f} MB per day"))
        elif key == "disk_free_gb" and tr is not None:
            per_day = -tr * 24
            days = v[-1][1] / per_day if per_day > 0.01 else None
            out.append((PASS if days is None or days > 60 else WARN if days > 14 else FAIL, label, f"{v[-1][1]:.0f} GB free" + (", not shrinking" if days is None else f", shrinking {per_day:.1f} GB per day: about {days:.0f} days until full")))
    return out


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("XYRON_SOAK_CSV", "/var/log/xyron-soak.csv")
    if not os.path.exists(path):
        print(f"No log at {path}. Start the logger first (see the instructions).")
        sys.exit(2)
    codes = {PASS: "32", WARN: "33", FAIL: "31", INFO: "36"}
    paint = (lambda s, k: f"\033[{codes[k]}m{s}\033[0m") if sys.stdout.isatty() else (lambda s, k: s)
    res = analyse(load(path))
    for level, title, detail in res:
        print(f"{paint('[' + level + ']', level)} {title}" + (f": {detail}" if detail else ""))
    n = {k: sum(1 for r in res if r[0] == k) for k in (PASS, WARN, FAIL)}
    print(f"\nSUMMARY: {n[PASS]} fine, {n[WARN]} to look at, {n[FAIL]} to fix")
    sys.exit(1 if n[FAIL] else 0)
