#!/usr/bin/env python3
"""Proves that your newest database backup really restores.

It loads the backup into a scratch database, compares every table with the live one, then deletes the scratch database.
The live database is only read, never changed.   Run it from the project folder:   sudo python3 tools/restore_test.py
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit import Ctx, age_text, human, parse_env  # noqa: E402

BACKUP_DIR = "/mnt/backup/pi"
SCRATCH = "xyron_restore_test"
PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"


def newest_dump(names):
    mine = sorted(n for n in names if re.fullmatch(r"db-xyron_\d{4}-\d{2}-\d{2}_\d{4}\.sql\.gz", n))
    return mine[-1] if mine else None


def compare_counts(live, restored):
    """live and restored map table -> row count. Returns (level, table, detail) rows."""
    rows = []
    for table in sorted(live):
        if table not in restored:
            rows.append((FAIL, table, "missing from the restored copy"))
        elif restored[table] > live[table]:
            rows.append((WARN, table, f"the copy has MORE rows than live ({restored[table]:,} vs {live[table]:,}); worth a look"))
        elif restored[table] < live[table]:
            rows.append((INFO, table, f"{restored[table]:,} rows in the backup; live has {live[table] - restored[table]:,} newer ones, which is normal"))
        else:
            rows.append((PASS, table, f"{restored[table]:,} rows, identical"))
    for table in sorted(set(restored) - set(live)):
        rows.append((INFO, table, "only in the backup (a table that no longer exists live)"))
    return rows


class RestoreCtx(Ctx):
    def restore(self, dump, db, user):
        """gunzip the dump into the scratch database. Returns (ok, message)."""
        gz = subprocess.Popen(["gunzip", "-c", dump], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ps = subprocess.Popen(["docker", "compose", "--project-directory", str(self.project), "exec", "-T", "db", "psql", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-q"],
                              stdin=gz.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        gz.stdout.close()
        try:
            _out, err = ps.communicate(timeout=3600)
        except subprocess.TimeoutExpired:
            ps.kill()
            return False, "timed out after an hour"
        gz_err = gz.stderr.read().decode(errors="ignore")
        gz.wait()
        if ps.returncode != 0 or gz.returncode != 0:
            return False, (err.decode(errors="ignore") + gz_err).strip()[-300:]
        return True, ""


def run(c, report):
    """report(level, title, detail). Returns True if the backup restores."""
    started = time.time()
    env = parse_env(c.read(c.project / ".env") or "")
    user, live_db = env.get("POSTGRES_USER", "xyron"), env.get("POSTGRES_DB", "xyron")
    name = newest_dump(c.listdir(BACKUP_DIR))
    if not name:
        report(FAIL, "Newest database backup", f"none found in {BACKUP_DIR}")
        return False
    dump = f"{BACKUP_DIR}/{name}"
    t, sz = c.mtime(dump), c.size(dump)
    age = c.now - t if t else None
    report(PASS if age is not None and age < 36 * 3600 else WARN, "Newest database backup", f"{name}, {human(sz or 0)}, {age_text(age) if age is not None else '?'} old")
    rc, o, e = c.sh(["gzip", "-t", dump])
    report(PASS if rc == 0 else FAIL, "The backup file is not damaged", "gzip test ok" if rc == 0 else (e or o)[:120])
    if rc != 0:
        return False
    good = False
    try:
        c.psql(f'DROP DATABASE IF EXISTS "{SCRATCH}"', db="postgres")
        rc, o, e = c.psql(f'CREATE DATABASE "{SCRATCH}"', db="postgres")
        if rc != 0:
            report(FAIL, "A scratch database could be created", e[:150])
            return False
        ok, msg = c.restore(dump, SCRATCH, user)
        report(PASS if ok else FAIL, "The backup loads into a fresh database", f"done in {time.time() - started:.0f} s" if ok else msg)
        if not ok:
            return False
        rc, o, e = c.psql("select tablename from pg_tables where schemaname = 'public' order by 1", db=live_db)
        tables = [t for t in o.splitlines() if re.fullmatch(r"[A-Za-z0-9_]+", t)]
        live, restored = {}, {}
        for t in tables:
            for db, store in ((live_db, live), (SCRATCH, restored)):
                rc, o, e = c.psql(f'select count(*) from "{t}"', db=db, timeout=120)
                if rc == 0 and o.isdigit():
                    store[t] = int(o)
        rows = compare_counts(live, restored)
        for level, table, detail in rows:
            report(level, f"Table {table}", detail)
        rc, o, e = c.psql("select count(*) from users where role = 'owner'", db=SCRATCH)
        report(PASS if rc == 0 and o.isdigit() and int(o) >= 1 else FAIL, "The owner account is in the restored copy", o or e[:80])
        good = not any(r[0] == FAIL for r in rows) and rc == 0 and o.isdigit() and int(o) >= 1
    finally:
        rc, o, e = c.psql(f'DROP DATABASE IF EXISTS "{SCRATCH}"', db="postgres")
        report(PASS if rc == 0 else WARN, "The scratch database was removed", "ok" if rc == 0 else "remove it by hand: " + e[:100])
    return good


RECIPE = """
If you ever need to restore for real (after a failure), the steps are:
  1. cd ~/xyron && sudo docker compose up -d db          # only the database
  2. sudo docker compose exec -T db psql -U xyron -d postgres -c 'DROP DATABASE IF EXISTS xyron' -c 'CREATE DATABASE xyron'
  3. sudo gunzip -c /mnt/backup/pi/<the dump file> | sudo docker compose exec -T db psql -U xyron -d xyron -v ON_ERROR_STOP=1 -q
  4. sudo docker compose up -d                            # everything else
"""

if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent
    if os.geteuid() != 0:
        print("Run this with sudo (the backups are readable only by root):  sudo python3 tools/restore_test.py")
        sys.exit(2)
    colors = {PASS: "32", WARN: "33", FAIL: "31", INFO: "36"}
    paint = (lambda s, k: f"\033[{colors[k]}m{s}\033[0m") if sys.stdout.isatty() else (lambda s, k: s)
    log = []

    def report(level, title, detail=""):
        log.append(level)
        print(f"{paint('[' + level + ']', level)} {title}" + (f": {detail}" if detail else ""), flush=True)
    good = run(RestoreCtx(os.environ.get("XYRON_DIR", str(here))), report)
    print("\nRESTORE TEST " + ("PASSED: your backup really restores." if good else "FAILED: do not rely on this backup until it is fixed."))
    print(RECIPE)
    sys.exit(0 if good else 1)
