"""Rebuilds api/app/data/ports.json from the open UN/LOCODE list. Run: python3 tools/gen_ports.py api/app/data/ports.json"""
import csv, io, json, re, sys, urllib.request

URL = "https://raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv"
out = sys.argv[1] if len(sys.argv) > 1 else "ports.json"
rows = csv.DictReader(io.StringIO(urllib.request.urlopen(URL, timeout=120).read().decode("utf-8")))


def coord(c):
    m = re.fullmatch(r"(\d{2})(\d{2})([NS]) (\d{3})(\d{2})([EW])", c.strip())
    if not m:
        return None
    lat, lon = int(m[1]) + int(m[2]) / 60, int(m[4]) + int(m[5]) / 60
    return (round(-lat if m[3] == "S" else lat, 3), round(-lon if m[6] == "W" else lon, 3))


ports = []
for r in rows:
    if not r["Location"] or not r["Function"].startswith("1") or r["Status"] in ("XX", "QQ", "RQ"):
        continue
    c = coord(r["Coordinates"])
    if c:
        ports.append([r["Country"] + r["Location"], (r["NameWoDiacritics"] or r["Name"]).strip(), c[0], c[1]])
with open(out, "w", encoding="ascii") as f:
    json.dump(ports, f, separators=(",", ":"), ensure_ascii=True)
print("ports written:", len(ports))
