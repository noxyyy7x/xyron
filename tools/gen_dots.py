import json
import sys
import urllib.request

import numpy as np
import shapely
from shapely.geometry import shape

URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
OUT = sys.argv[1] if len(sys.argv) > 1 else "dots.json"
N = 110000  # sample points over the whole sphere

print("Downloading country outlines...")
with urllib.request.urlopen(URL, timeout=60) as r:
    data = json.load(r)

# evenly spaced points on a sphere (Fibonacci lattice)
i = np.arange(N) + 0.5
lat = np.degrees(np.arcsin(1 - 2 * i / N))
lon = (np.degrees(np.pi * (1 + 5 ** 0.5) * i) + 180) % 360 - 180

assigned = np.full(N, -1, dtype=np.int32)
countries = []
for feat in data["features"]:
    p = feat["properties"]
    geom = shape(feat["geometry"])
    if geom.is_empty:
        continue
    if not geom.is_valid:
        geom = geom.buffer(0)
    idx = len(countries)
    minx, miny, maxx, maxy = geom.bounds
    cand = np.where((lon >= minx) & (lon <= maxx) & (lat >= miny) & (lat <= maxy) & (assigned < 0))[0]
    if len(cand):
        hit = shapely.contains_xy(geom, lon[cand], lat[cand])
        assigned[cand[hit]] = idx
    rep = geom.representative_point()
    iso = p.get("ISO_A3")
    if not iso or iso == "-99":
        iso = p.get("ADM0_A3") or "---"
    countries.append({
        "name": p.get("NAME") or p.get("ADMIN") or "Unknown",
        "iso": iso,
        "continent": p.get("CONTINENT") or "",
        "region": p.get("SUBREGION") or "",
        "pop": int(p.get("POP_EST") or 0),
        "lat": round(rep.y, 3),
        "lon": round(rep.x, 3),
    })

land = np.where(assigned >= 0)[0]
# tiny countries get no dots from the sphere grid; give each one a dot at its centre
have = set(int(x) for x in np.unique(assigned[land]))
extra_lat, extra_lon, extra_c = [], [], []
for idx, c in enumerate(countries):
    if idx not in have:
        extra_lat.append(c["lat"]); extra_lon.append(c["lon"]); extra_c.append(idx)

out = {
    "spacing": round((4 * 3.141592653589793 / N) ** 0.5, 5),
    "countries": countries,
    "lat": [round(float(x), 2) for x in lat[land]] + [round(x, 2) for x in extra_lat],
    "lon": [round(float(x), 2) for x in lon[land]] + [round(x, 2) for x in extra_lon],
    "c": [int(x) for x in assigned[land]] + extra_c,
}
with open(OUT, "w") as f:
    json.dump(out, f, separators=(",", ":"))
print("countries:", len(countries), "dots:", len(out["c"]), "tiny countries added:", len(extra_c))
