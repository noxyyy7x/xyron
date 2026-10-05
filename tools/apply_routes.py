import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"

BACKEND_NEW = '''@router.get("/api/flights")
def flights(user=Depends(current_user)):
    return Response(content=_snapshot["body"], media_type="application/json")


# ---------- route and aircraft details for one selected plane (adsbdb.com, free, no key) ----------
_detail_cache = {}
_ICAO24_RE = re.compile(r"^[0-9a-fA-F]{6}$")
_CALLSIGN_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


def _adsbdb(path):
    req = urllib.request.Request(
        "https://api.adsbdb.com/v0/" + path, headers={"User-Agent": "XYRON/1.0 (private dashboard)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"response": "unknown"}
        raise


def _airport(a):
    if not isinstance(a, dict):
        return None
    lat, lon = a.get("latitude"), a.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {
        "name": a.get("name"), "city": a.get("municipality"), "country": a.get("country_name"),
        "iata": a.get("iata_code"), "icao": a.get("icao_code"), "lat": lat, "lon": lon,
    }


def clean_route(j):
    resp = (j or {}).get("response")
    fr = resp.get("flightroute") if isinstance(resp, dict) else None
    if not isinstance(fr, dict):
        return None
    origin, dest = _airport(fr.get("origin")), _airport(fr.get("destination"))
    if not origin or not dest:
        return None
    al = fr.get("airline") if isinstance(fr.get("airline"), dict) else None
    return {
        "callsign": fr.get("callsign"),
        "airline": {k: al.get(k) for k in ("name", "icao", "iata", "country")} if al else None,
        "origin": origin, "destination": dest, "via": _airport(fr.get("midpoint")),
    }


def clean_aircraft(j):
    resp = (j or {}).get("response")
    ac = resp.get("aircraft") if isinstance(resp, dict) else None
    if not isinstance(ac, dict):
        return None
    photo = ac.get("url_photo")
    return {
        "type": ac.get("type"), "icao_type": ac.get("icao_type"), "manufacturer": ac.get("manufacturer"),
        "registration": ac.get("registration"), "owner": ac.get("registered_owner"),
        "country": ac.get("registered_owner_country_name"),
        "photo": photo if isinstance(photo, str) and photo.startswith("https://") else None,
    }


@router.get("/api/flight/{icao24}")
def flight_detail(icao24: str, callsign: str = "", user=Depends(current_user)):
    if not _ICAO24_RE.match(icao24):
        raise HTTPException(400, "Invalid transponder code")
    callsign = callsign.strip().upper()
    if callsign and not _CALLSIGN_RE.match(callsign):
        raise HTTPException(400, "Invalid callsign")
    key = (icao24.lower(), callsign)
    now = time.time()
    cached = _detail_cache.get(key)
    if cached and now < cached[0]:
        return cached[1]
    result = {"route": None, "aircraft": None}
    ok = True
    if callsign:
        try:
            result["route"] = clean_route(_adsbdb("callsign/" + urllib.parse.quote(callsign)))
        except Exception as e:
            ok = False
            log.warning("route lookup failed: %s", type(e).__name__)
    try:
        result["aircraft"] = clean_aircraft(_adsbdb("aircraft/" + icao24.lower()))
    except Exception as e:
        ok = False
        log.warning("aircraft lookup failed: %s", type(e).__name__)
    ttl = (12 * 3600 if (result["route"] or result["aircraft"]) else 1800) if ok else 60
    if len(_detail_cache) > 5000:
        _detail_cache.clear()
    _detail_cache[key] = (now + ttl, result)
    return result
'''

FRONT_PURE = '''// ----- great-circle maths for routes (pure functions, so they can be tested) -----
export function toUnit(latDeg, lonDeg) {
  const la = latDeg * DEG;
  const lo = lonDeg * DEG;
  return [Math.cos(la) * Math.sin(lo), Math.sin(la), Math.cos(la) * Math.cos(lo)];
}
export function angleBetween(a, b) {
  return Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2])));
}
export function distanceKm(latA, lonA, latB, lonB) {
  return (angleBetween(toUnit(latA, lonA), toUnit(latB, lonB)) * EARTH_M) / 1000;
}
export function slerp(a, b, t) {
  const w = angleBetween(a, b);
  const s = Math.sin(w);
  if (s < 1e-6) return a.slice();
  const k1 = Math.sin((1 - t) * w) / s;
  const k2 = Math.sin(t * w) / s;
  return [k1 * a[0] + k2 * b[0], k1 * a[1] + k2 * b[1], k1 * a[2] + k2 * b[2]];
}
// how far above the surface the route line sits at fraction s (0..1) of the whole journey
export function arcHeight(s, span) {
  return 1.01 + 0.012 * Math.sin(Math.PI * s) * Math.min(1, span / 1.2);
}
export function fillArc(out, a, b, s0, s1, span, steps) {
  for (let i = 0; i <= steps; i++) {
    const u = i / steps;
    const p = slerp(a, b, u);
    const h = arcHeight(s0 + (s1 - s0) * u, span);
    out[3 * i] = p[0] * h;
    out[3 * i + 1] = p[1] * h;
    out[3 * i + 2] = p[2] * h;
  }
}
// progress along the route, and a rough time left at the current ground speed
export function routeProgress(o, d, p, speedMs) {
  const flown = (angleBetween(o, p) * EARTH_M) / 1000;
  const remaining = (angleBetween(p, d) * EARTH_M) / 1000;
  const total = flown + remaining;
  return {
    flownKm: flown,
    remainingKm: remaining,
    fraction: total > 0 ? flown / total : 0,
    etaMin: speedMs > 50 ? (remaining * 1000) / speedMs / 60 : null,
  };
}

'''

FRONT_STATE = '''  let lastDetail = 0;
  const filters = { ...DEFAULT_FILTERS };

  // ----- route arcs for the selected plane -----
  const ARC_STEPS = 48;
  const flownPos = new Float32Array((ARC_STEPS + 1) * 3);
  const remainPos = new Float32Array((ARC_STEPS + 1) * 3);
  const flownGeo = new THREE.BufferGeometry();
  flownGeo.setAttribute('position', new THREE.BufferAttribute(flownPos, 3));
  const remainGeo = new THREE.BufferGeometry();
  remainGeo.setAttribute('position', new THREE.BufferAttribute(remainPos, 3));
  const flownLine = new THREE.Line(flownGeo, new THREE.LineBasicMaterial({ color: 0xffc847, transparent: true, opacity: 0.95, depthWrite: false }));
  const remainLine = new THREE.Line(remainGeo, new THREE.LineDashedMaterial({ color: 0x8ce0ff, dashSize: 0.012, gapSize: 0.012, transparent: true, opacity: 0.85, depthWrite: false }));
  const apPos = new Float32Array(6);
  const apColor = new Float32Array([0.4, 0.9, 0.6, 1.0, 0.4, 0.4]);
  const apGeo = new THREE.BufferGeometry();
  apGeo.setAttribute('position', new THREE.BufferAttribute(apPos, 3));
  apGeo.setAttribute('color', new THREE.BufferAttribute(apColor, 3));
  const dotCanvas = document.createElement('canvas');
  dotCanvas.width = dotCanvas.height = 32;
  const dctx = dotCanvas.getContext('2d');
  dctx.beginPath();
  dctx.arc(16, 16, 14, 0, Math.PI * 2);
  dctx.fillStyle = '#fff';
  dctx.fill();
  const apPoints = new THREE.Points(apGeo, new THREE.PointsMaterial({
    size: 0.03, vertexColors: true, map: new THREE.CanvasTexture(dotCanvas), sizeAttenuation: true, transparent: true, depthWrite: false, alphaTest: 0.1,
  }));
  for (const o of [flownLine, remainLine, apPoints]) { o.visible = false; o.frustumCulled = false; globe.add(o); }
  let routeInfo = null; // null, or { state: 'loading' | 'ok' | 'none' | 'error', route, aircraft }
'''

FRONT_FUNCS = '''  // ----- route and aircraft details for the selected plane -----
  function routeAirline() {
    const a = routeInfo && routeInfo.route && routeInfo.route.airline;
    return a && a.name ? { icao: a.icao || '', name: a.name, iata: a.iata || '', country: a.country || '' } : null;
  }

  function hideArcs() {
    flownLine.visible = false;
    remainLine.visible = false;
    apPoints.visible = false;
  }

  function currentProgress() {
    const r = routeInfo.route;
    const o = toUnit(r.origin.lat, r.origin.lon);
    const d = toUnit(r.destination.lat, r.destination.lon);
    const p = [pos[3 * selected] / LIFT, pos[3 * selected + 1] / LIFT, pos[3 * selected + 2] / LIFT];
    return { o, d, p, prog: routeProgress(o, d, p, vel[selected]) };
  }

  function updateArcs() {
    if (selected < 0 || !routeInfo || routeInfo.state !== 'ok') { hideArcs(); return; }
    const { o, d, p, prog } = currentProgress();
    const span = angleBetween(o, d);
    const f = prog.fraction;
    fillArc(flownPos, o, p, 0, f, span, ARC_STEPS);
    fillArc(remainPos, p, d, f, 1, span, ARC_STEPS);
    const ho = arcHeight(0, span);
    const hd = arcHeight(1, span);
    apPos.set([o[0] * ho, o[1] * ho, o[2] * ho, d[0] * hd, d[1] * hd, d[2] * hd]);
    flownGeo.attributes.position.needsUpdate = true;
    remainGeo.attributes.position.needsUpdate = true;
    apGeo.attributes.position.needsUpdate = true;
    remainLine.computeLineDistances();
    flownLine.visible = true;
    remainLine.visible = true;
    apPoints.visible = true;
  }

  async function loadRoute(i) {
    const f = meta[i];
    const icao = f[0];
    routeInfo = { state: 'loading' };
    renderDetail();
    try {
      const r = await fetch('/api/flight/' + encodeURIComponent(icao) + (f[1] ? '?callsign=' + encodeURIComponent(f[1]) : ''), { credentials: 'same-origin' });
      if (selectedIcao !== icao) return; // the user has moved on
      if (!r.ok) { routeInfo = { state: 'error' }; renderDetail(); return; }
      const j = await r.json();
      if (selectedIcao !== icao) return;
      routeInfo = { state: j.route ? 'ok' : 'none', route: j.route, aircraft: j.aircraft };
      updateArcs();
      renderDetail();
    } catch (e) {
      if (selectedIcao === icao) { routeInfo = { state: 'error' }; renderDetail(); }
    }
  }

  function place(p) {
    return (p.name || p.icao || 'Unknown airport') + ' (' + (p.city ? p.city + ', ' : '') + (p.country || '') + ')';
  }
  function routeRows(dl) {
    if (!routeInfo) return;
    if (routeInfo.state === 'loading') { dlRow(dl, 'Route', 'Looking up\\u2026'); return; }
    if (routeInfo.state === 'error') { dlRow(dl, 'Route', 'Lookup failed, try again later'); return; }
    if (routeInfo.state === 'none') { dlRow(dl, 'Route', 'Not available for this callsign (private, military and unscheduled flights often have none)'); return; }
    const r = routeInfo.route;
    dlRow(dl, 'Route', (r.origin.iata || r.origin.icao || '?') + ' \\u2192 ' + (r.destination.iata || r.destination.icao || '?'));
    dlRow(dl, 'From', place(r.origin));
    dlRow(dl, 'To', place(r.destination));
    if (r.via) dlRow(dl, 'Via', place(r.via));
    const { prog } = currentProgress();
    dlRow(dl, 'Progress', Math.round(prog.fraction * 100) + '% \\u2014 ' + Math.round(prog.flownKm).toLocaleString() + ' km flown, ' + Math.round(prog.remainingKm).toLocaleString() + ' km to go');
    if (prog.etaMin !== null) {
      const m = Math.round(prog.etaMin);
      dlRow(dl, 'Estimated time left', (m >= 60 ? Math.floor(m / 60) + ' h ' : '') + (m % 60) + ' min (rough estimate)');
    }
  }
  function aircraftRows(dl) {
    const ac = routeInfo && routeInfo.aircraft;
    if (!ac) return;
    const kind = [ac.manufacturer, ac.type].filter(Boolean).join(' ');
    if (kind) dlRow(dl, 'Aircraft', kind + (ac.icao_type ? ' (' + ac.icao_type + ')' : ''));
    if (ac.registration) dlRow(dl, 'Registration', ac.registration);
    if (ac.owner) dlRow(dl, 'Operator / owner', ac.owner);
  }

'''

NO_MATCH = '''    if (filters.q.trim() && !matches.length) {
      const others = activeCount() - 1;
      results.append(el('div', {
        className: 'more',
        textContent: others > 0
          ? 'No aircraft match. ' + others + (others > 1 ? ' other filters are' : ' other filter is') + ' also active; try Reset filters.'
          : 'No aircraft match right now. That airline may have nothing in the air, or may not be in our airline list. Try its 3-letter callsign code (like UAE) or a flight number (like EK203).',
      }));
    }
'''

edits = {
    app / "aviation.py": [
        ("import os\nimport time\n", "import os\nimport re\nimport time\n"),
        ("from fastapi import APIRouter, Depends\n", "from fastapi import APIRouter, Depends, HTTPException\n"),
        ('@router.get("/api/flights")\ndef flights(user=Depends(current_user)):\n    return Response(content=_snapshot["body"], media_type="application/json")\n',
         BACKEND_NEW),
    ],
    static / "aviation.js": [
        ("// Which plane (index) is under the pointer, or -1. Hidden planes and planes on the far side never match.\n",
         FRONT_PURE + "// Which plane (index) is under the pointer, or -1. Hidden planes and planes on the far side never match.\n"),
        ("  let lastDetail = 0;\n  const filters = { ...DEFAULT_FILTERS };\n", FRONT_STATE),
        ("    if (filters.q.trim() && !matches.length) results.append(el('div', { className: 'more', textContent: 'No aircraft match that search right now' }));\n",
         NO_MATCH),
        ("    const a = airlineOf(f[1], air);\n    document.getElementById('pname').textContent = name(selected);\n",
         "    const a = airlineOf(f[1], air) || routeAirline();\n    document.getElementById('pname').textContent = name(selected);\n"),
        ("    if (a && a.iata) dlRow(dl, 'Flight number', a.iata + f[1].slice(3));\n",
         "    if (a && a.iata) dlRow(dl, 'Flight number', a.iata + f[1].slice(3));\n    routeRows(dl);\n"),
        ("    if (f[9]) dlRow(dl, 'Registered in', f[9]);\n",
         "    if (f[9]) dlRow(dl, 'Registered in', f[9]);\n    aircraftRows(dl);\n"),
        ("      textContent: 'Positions from The OpenSky Network (opensky-network.org); between updates they are estimated from speed and heading. Airline names from the OpenFlights database, which is community-maintained and may be out of date.',\n",
         "      textContent: 'Positions from The OpenSky Network (opensky-network.org); between updates they are estimated from speed and heading. Routes and aircraft details come from adsbdb.com, matched by callsign, and can be wrong or out of date. Airline names from the community-maintained OpenFlights database.',\n"),
        ("  function select(i) {\n    deselect(); // clears any selected country dot or event and closes the panel\n",
         FRONT_FUNCS + "  function select(i) {\n    deselect(); // clears any selected country dot or event and closes the panel\n"),
        ("    renderDetail();\n    openPanel();\n    flyTo(curLat[i] / DEG, curLon[i] / DEG, 2.4);\n  }\n",
         "    routeInfo = null;\n    renderDetail();\n    openPanel();\n    flyTo(curLat[i] / DEG, curLon[i] / DEG, 2.4);\n    loadRoute(i);\n  }\n"),
        ("    selected = -1;\n    selectedIcao = null;\n  }\n\n  function hit(x, y) {\n",
         "    selected = -1;\n    selectedIcao = null;\n    routeInfo = null;\n    hideArcs();\n  }\n\n  function hit(x, y) {\n"),
        ("      if (selected >= 0 && now - lastDetail >= 1000) { lastDetail = now; renderDetail(); }\n",
         "      if (selected >= 0 && now - lastDetail >= 1000) { lastDetail = now; updateArcs(); renderDetail(); }\n"),
    ],
}

# check everything first, so a mismatch changes nothing
new_text = {}
for path, pairs in edits.items():
    text = path.read_text()
    for old, new in pairs:
        if text.count(old) != 1:
            sys.exit(f"STOPPED, nothing changed. Could not find exactly one match in {path.name} for:\n{old[:200]!r}")
        text = text.replace(old, new)
    new_text[path] = text
for path, text in new_text.items():
    path.write_text(text)
    print("patched", path.name)
