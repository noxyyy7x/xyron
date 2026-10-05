import json
import sys
import urllib.request

URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_populated_places_simple.geojson"
OUT = sys.argv[1] if len(sys.argv) > 1 else "cities.json"
TARGET = 5000

with urllib.request.urlopen(URL, timeout=60) as r:
    feats = json.load(r)["features"]

places = []
for f in feats:
    p = f["properties"]
    if p.get("featurecla") == "Scientific station":
        continue
    places.append({
        "name": p.get("nameascii") or p.get("name"),
        "country": p.get("adm0name") or "",
        "lat": round(float(p["latitude"]), 3),
        "lon": round(float(p["longitude"]), 3),
        "pop": int(p.get("pop_max") or 0),
        "capital": p.get("featurecla") == "Admin-0 capital",
    })

# every national capital, then the biggest remaining cities, up to the target
chosen = [c for c in places if c["capital"]]
seen = {(c["name"], c["country"]) for c in chosen}
for c in sorted(places, key=lambda c: -c["pop"]):
    if len(chosen) >= TARGET:
        break
    if (c["name"], c["country"]) not in seen:
        chosen.append(c)
        seen.add((c["name"], c["country"]))
chosen.sort(key=lambda c: (c["country"], c["name"]))
with open(OUT, "w") as fh:
    json.dump(chosen, fh, separators=(",", ":"), ensure_ascii=False)
print("cities:", len(chosen), "capitals:", sum(c["capital"] for c in chosen))
