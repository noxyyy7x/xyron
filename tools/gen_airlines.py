import csv
import io
import json
import sys
import urllib.request

URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"
OUT = sys.argv[1] if len(sys.argv) > 1 else "airlines.json"

with urllib.request.urlopen(URL, timeout=60) as r:
    text = r.read().decode("utf-8")

seen = set()
out = []
for row in csv.reader(io.StringIO(text)):
    if len(row) < 8:
        continue
    _id, name, _alias, iata, icao, _callsign, country, active = row[:8]
    if active != "Y" or len(icao) != 3 or not icao.isalpha() or not name.strip():
        continue
    icao = icao.upper()
    if icao in seen:  # a few codes are shared; keep the first entry
        continue
    seen.add(icao)
    iata = iata.upper() if len(iata) == 2 and iata.replace("-", "") else ""
    out.append([icao, name.strip(), iata, country.strip()])
out.sort(key=lambda a: a[1].lower())
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
print("airlines:", len(out), "| with an IATA code:", sum(1 for a in out if a[2]))
