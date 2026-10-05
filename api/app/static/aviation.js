// Live aircraft layer: plane icons that keep moving between OpenSky updates (dead reckoning),
// search and filters, hover cards and a detail panel. Routes and arcs come in the next step.
const DEG = Math.PI / 180;
const EARTH_M = 6371000;
const STORE_KEY = 'xyron.layers';
const SIZE_KEY = 'xyron.planesize';
const REFRESH_MS = 120000;
const TICK_MS = 100;
const LIFT = 1.012;
const HIT_PX = 12;
const FT = 3.28084;
const KT = 1.94384;

const VERTEX = `
attribute vec3 aDir;
attribute vec3 aColor;
attribute float aSel;
attribute float aShow;
uniform float uPx;
uniform float uAspect;
uniform float uScale;
varying vec3 vColor;
varying float vAngle;
varying float vSel;
void main() {
  vColor = aColor;
  vSel = aSel;
  vAngle = 0.0;
  if (aShow < 0.5) {
    gl_PointSize = 0.0;
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    return;
  }
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vec4 clipA = projectionMatrix * mv;
  vec4 clipB = projectionMatrix * (modelViewMatrix * vec4(position + aDir * 0.02, 1.0));
  vec2 a = clipA.xy / clipA.w;
  vec2 b = clipB.xy / clipB.w;
  vec2 d = vec2((b.x - a.x) * uAspect, b.y - a.y);
  vAngle = atan(d.x, d.y);
  float size = clamp(0.03 * uPx / -mv.z, 12.0, 30.0) * uScale;
  gl_PointSize = size * (1.0 + 1.2 * aSel);
  gl_Position = clipA;
}`;

const FRAGMENT = `
uniform sampler2D uTex;
varying vec3 vColor;
varying float vAngle;
varying float vSel;
void main() {
  vec2 p = vec2(gl_PointCoord.x * 2.0 - 1.0, 1.0 - gl_PointCoord.y * 2.0);
  float c = cos(vAngle);
  float s = sin(vAngle);
  vec2 q = vec2(p.x * c - p.y * s, p.x * s + p.y * c);
  vec2 uv = vec2(q.x * 0.5 + 0.5, q.y * 0.5 + 0.5);
  float shape = 0.0;
  if (uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0) {
    shape = texture2D(uTex, uv).a;
  }
  float d = length(p);
  float ring = smoothstep(0.78, 0.84, d) * (1.0 - smoothstep(0.93, 0.98, d)) * vSel;
  float a = max(shape, ring);
  if (a < 0.03) discard;
  vec3 col = mix(vColor, vec3(1.0, 0.78, 0.28), vSel);
  gl_FragColor = vec4(col, a);
}`;

// A top-down airliner silhouette, nose pointing up, drawn once into a texture.
function planeTexture(THREE) {
  const S = 128;
  const c = document.createElement('canvas');
  c.width = c.height = S;
  const g = c.getContext('2d');
  const half = [[32, 2], [34.6, 6], [35.6, 15], [35.6, 25], [61, 41], [61, 46.5], [35.6, 40.5], [35.2, 52], [46, 58.5], [46, 62.5], [33, 60], [32, 62.5]];
  const pts = half.concat(half.slice(1, -1).reverse().map(([x, y]) => [64 - x, y]));
  g.beginPath();
  pts.forEach(([x, y], i) => (i ? g.lineTo(x * 2, y * 2) : g.moveTo(x * 2, y * 2)));
  g.closePath();
  g.fillStyle = '#fff';
  g.fill();
  const t = new THREE.CanvasTexture(c);
  t.generateMipmaps = true;
  return t;
}

// Where an aircraft is after flying distRad radians along a great circle on a fixed track.
export function advance(latRad, lonRad, trackRad, distRad) {
  const sinLat = Math.sin(latRad);
  const cosLat = Math.cos(latRad);
  const sinD = Math.sin(distRad);
  const cosD = Math.cos(distRad);
  const lat2 = Math.asin(sinLat * cosD + cosLat * sinD * Math.cos(trackRad));
  const lon2 = lonRad + Math.atan2(Math.sin(trackRad) * sinD * cosLat, cosD - sinLat * Math.sin(lat2));
  return [lat2, lon2];
}

// Which plane (index) is under the pointer, or -1. Hidden planes and planes on the far side never match.
export function hitPlanes(THREE, pos, n, globe, camera, rect, x, y, maxPx, show) {
  globe.updateWorldMatrix(true, false);
  camera.updateMatrixWorld();
  const center = globe.getWorldPosition(new THREE.Vector3());
  const camPos = camera.position;
  const v = new THREE.Vector3();
  const nrm = new THREE.Vector3();
  const toCam = new THREE.Vector3();
  let best = -1;
  let bestD = maxPx;
  for (let i = 0; i < n; i++) {
    if (show && !show[i]) continue;
    v.set(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]).applyMatrix4(globe.matrixWorld);
    nrm.copy(v).sub(center);
    toCam.copy(camPos).sub(v);
    if (nrm.dot(toCam) <= 0) continue;
    v.project(camera);
    const dx = rect.left + ((v.x + 1) / 2) * rect.width - x;
    const dy = rect.top + ((1 - v.y) / 2) * rect.height - y;
    const d = Math.hypot(dx, dy);
    if (d < bestD) { bestD = d; best = i; }
  }
  return best;
}

// ----- airlines, search and filters (pure functions, so they can be tested) -----
export function buildAirlines(list) {
  const byIcao = new Map();
  const byIata = new Map();
  for (const [icao, name, iata, country] of list || []) {
    byIcao.set(icao, { icao, name, iata, country });
    if (iata && !byIata.has(iata)) byIata.set(iata, icao);
  }
  return { byIcao, byIata };
}
export function airlineOf(callsign, air) {
  const m = /^([A-Z]{3})\d/.exec(callsign || '');
  return m ? air.byIcao.get(m[1]) || null : null;
}
export function normCall(c) { return (c || '').replace(/^([A-Z]{3})0+(?=\d)/, '$1'); }
export function haystack(f, air) {
  const a = airlineOf(f[1], air);
  return (f[1] + ' ' + f[0] + ' ' + (a ? a.name + ' ' + a.icao + ' ' + a.iata + ' ' + a.country : '') + ' ' + f[9]).toLowerCase();
}
export function matchesQuery(query, f, hay, air) {
  const q = (query || '').trim();
  if (!q) return true;
  if (q.toLowerCase().split(/\s+/).every((t) => hay.includes(t))) return true;
  // an airline flight number such as EK203 also matches the callsign UAE203
  const m = /^([A-Z0-9]{2})\s?(\d{1,4}[A-Z]?)$/.exec(q.toUpperCase());
  if (m) {
    const icao = air.byIata.get(m[1]);
    if (icao) return normCall(f[1]) === icao + m[2].replace(/^0+(?=\d)/, '');
  }
  return false;
}
export const DEFAULT_FILTERS = {
  q: '', airline: '', country: '', alt: 'any', speed: 'any', vrate: 'any', cls: 'any', airlineOnly: false, emergencyOnly: false,
};
export function passesFilters(f, s, air) {
  const alt = f[4];
  const spd = f[5];
  const vr = f[7];
  const cat = f[8];
  if (s.alt === 'low' && !(alt < 3048)) return false;
  if (s.alt === 'mid' && !(alt >= 3048 && alt < 7925)) return false;
  if (s.alt === 'high' && !(alt >= 7925)) return false;
  if (s.speed === 'slow' && !(spd < 77)) return false;
  if (s.speed === 'mid' && !(spd >= 77 && spd < 231)) return false;
  if (s.speed === 'fast' && !(spd >= 231)) return false;
  if (s.vrate === 'climb' && !(vr > 2.5)) return false;
  if (s.vrate === 'descend' && !(vr < -2.5)) return false;
  if (s.vrate === 'level' && !(Math.abs(vr) <= 2.5)) return false;
  if (s.cls === 'large' && !(cat >= 3 && cat <= 6)) return false;
  if (s.cls === 'light' && cat !== 2) return false;
  if (s.cls === 'heli' && cat !== 8) return false;
  if (s.cls === 'other' && !(cat === 7 || (cat >= 9 && cat <= 15))) return false;
  if (s.cls === 'unknown' && !(cat === 0 || cat === 1)) return false;
  if (s.country && f[9] !== s.country) return false;
  if (s.emergencyOnly && !['7500', '7600', '7700'].includes(f[11])) return false;
  if (s.airline || s.airlineOnly) {
    const a = airlineOf(f[1], air);
    if (!a) return false;
    if (s.airline && a.icao !== s.airline) return false;
  }
  return true;
}

function altColor(m) {
  if (m < 1000) return [1.0, 0.7, 0.3];
  if (m < 6000) return [0.4, 0.9, 0.6];
  if (m < 10000) return [0.4, 0.8, 1.0];
  return [0.78, 0.72, 1.0];
}
const CATEGORY = {
  1: 'Unknown type', 2: 'Light aircraft', 3: 'Small aircraft', 4: 'Large airliner', 5: 'Large airliner (high vortex)',
  6: 'Heavy aircraft', 7: 'High-performance', 8: 'Helicopter', 9: 'Glider', 10: 'Balloon / airship',
  11: 'Skydiver', 12: 'Ultralight', 14: 'Drone',
};
const EMERGENCY = { 7500: 'hijack', 7600: 'radio failure', 7700: 'general emergency' };

const ALT_OPTS = [['any', 'Any altitude'], ['low', 'Below 10,000 ft'], ['mid', '10,000 \u2013 26,000 ft'], ['high', 'Above 26,000 ft']];
const SPEED_OPTS = [['any', 'Any speed'], ['slow', 'Slow (under 150 kt)'], ['mid', '150 \u2013 450 kt'], ['fast', 'Fast (over 450 kt)']];
const VRATE_OPTS = [['any', 'Any'], ['climb', 'Climbing'], ['descend', 'Descending'], ['level', 'Level']];
const CLASS_OPTS = [['any', 'Any type'], ['large', 'Airliners and large aircraft'], ['light', 'Light aircraft'], ['heli', 'Helicopters'], ['other', 'Gliders, balloons, drones, other'], ['unknown', 'Type not reported']];
const SIZE_OPTS = [['0.7', 'Small'], ['1', 'Medium'], ['1.4', 'Large']];

function readEnabled() {
  try {
    const v = JSON.parse(localStorage.getItem(STORE_KEY));
    if (Array.isArray(v)) return new Set(v);
  } catch (e) { /* storage unavailable */ }
  return new Set(['earthquakes']);
}
function readSize() {
  try {
    const v = localStorage.getItem(SIZE_KEY);
    if (v && SIZE_OPTS.some((o) => o[0] === v)) return v;
  } catch (e) { /* ignore */ }
  return '1';
}

function el(tag, props, ...kids) {
  const e = document.createElement(tag);
  Object.assign(e, props || {});
  for (const k of kids) e.append(k);
  return e;
}

export function init(ctx) {
  const { THREE, globe, camera, renderer, canvas, deselect, flyTo, openPanel } = ctx;
  const tipEl = document.getElementById('tip');
  const bufSize = new THREE.Vector2();
  const material = new THREE.ShaderMaterial({
    uniforms: {
      uPx: { value: 600 }, uAspect: { value: 1 }, uScale: { value: Number(readSize()) }, uTex: { value: planeTexture(THREE) },
    },
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    transparent: true,
    depthWrite: false,
  });

  let air = buildAirlines([]);
  let enabled = false;
  let timer = null;
  let n = 0;
  let meta = [];
  let hay = [];
  let t0 = new Float64Array(0);
  let lat0 = new Float32Array(0);
  let lon0 = new Float32Array(0);
  let trk = new Float32Array(0);
  let vel = new Float32Array(0);
  let curLat = new Float32Array(0);
  let curLon = new Float32Array(0);
  let pos = new Float32Array(0);
  let dir = new Float32Array(0);
  let sel = new Float32Array(0);
  let show = new Float32Array(0);
  let points = null;
  let selected = -1;
  let selectedIcao = null;
  let lastTick = 0;
  let lastDetail = 0;
  const filters = { ...DEFAULT_FILTERS };

  // ----- filter panel -----
  const stage = document.getElementById('stage');
  const btn = el('button', { id: 'filterbtn', className: 'chip', type: 'button', hidden: true, textContent: 'Filters' });
  const panel = el('div', { id: 'avfilters', className: 'avpanel', hidden: true });
  const qInput = el('input', { type: 'search', id: 'avq', placeholder: 'Flight, airline, country\u2026', autocomplete: 'off' });
  const results = el('div', { className: 'avresults' });
  const airlineSel = el('select', { id: 'avairline' });
  const countrySel = el('select', { id: 'avcountry' });
  const mkSelect = (id, opts) => {
    const s = el('select', { id });
    for (const [v, t] of opts) s.append(el('option', { value: v, textContent: t }));
    return s;
  };
  const altSel = mkSelect('avalt', ALT_OPTS);
  const speedSel = mkSelect('avspeed', SPEED_OPTS);
  const vrateSel = mkSelect('avvrate', VRATE_OPTS);
  const classSel = mkSelect('avclass', CLASS_OPTS);
  const sizeSel = mkSelect('avsize', SIZE_OPTS);
  sizeSel.value = readSize();
  const airOnly = el('input', { type: 'checkbox', id: 'avaironly' });
  const emOnly = el('input', { type: 'checkbox', id: 'avem' });
  const countEl = el('div', { className: 'avcount' });
  const resetBtn = el('button', { type: 'button', className: 'small secondary', textContent: 'Reset filters' });
  const closeBtn = el('button', { type: 'button', className: 'avx', textContent: '\u00d7' });
  closeBtn.setAttribute('aria-label', 'Close filters');
  const field = (label, control) => el('div', { className: 'avfield' }, el('label', { htmlFor: control.id, textContent: label }), control);
  const check = (control, text) => el('label', { className: 'check' }, control, text);
  panel.append(
    el('div', { className: 'avhead' }, el('strong', { textContent: 'Aircraft filters' }), closeBtn),
    field('Search', qInput), results,
    field('Airline', airlineSel), field('Registered in', countrySel),
    field('Altitude', altSel), field('Speed', speedSel), field('Climb / descent', vrateSel), field('Aircraft class', classSel),
    check(airOnly, ' Airline flights only'), check(emOnly, ' Emergency squawks only'),
    field('Plane icon size', sizeSel), countEl, resetBtn,
  );
  stage.append(btn, panel);

  function activeCount() {
    let c = 0;
    if (filters.q.trim()) c++;
    for (const k of ['airline', 'country']) if (filters[k]) c++;
    for (const k of ['alt', 'speed', 'vrate', 'cls']) if (filters[k] !== 'any') c++;
    if (filters.airlineOnly) c++;
    if (filters.emergencyOnly) c++;
    return c;
  }

  function applyFilters() {
    if (!n) { countEl.textContent = ''; results.replaceChildren(); return; }
    const matches = [];
    let shown = 0;
    for (let i = 0; i < n; i++) {
      const f = meta[i];
      const ok = passesFilters(f, filters, air) && matchesQuery(filters.q, f, hay[i], air);
      show[i] = ok ? 1 : 0;
      if (ok) { shown++; if (filters.q.trim()) matches.push(i); }
    }
    if (points) points.geometry.attributes.aShow.needsUpdate = true;
    const act = activeCount();
    countEl.textContent = 'Showing ' + shown.toLocaleString() + ' of ' + n.toLocaleString() + ' aircraft';
    btn.textContent = act ? 'Filters (' + act + ')' : 'Filters';
    btn.classList.toggle('on', act > 0);
    // best matches first: exact callsign, then callsign prefix, then the rest by altitude
    const q = filters.q.trim().toUpperCase();
    const rank = (i) => (meta[i][1] === q ? 0 : meta[i][1].startsWith(q) ? 1 : 2);
    matches.sort((a, b) => rank(a) - rank(b) || meta[b][4] - meta[a][4]);
    results.replaceChildren();
    for (const i of matches.slice(0, 12)) {
      const f = meta[i];
      const a = airlineOf(f[1], air);
      const row = el('div', { className: 'row' });
      row.append(el('strong', { textContent: f[1] || f[0].toUpperCase() }), (a ? ' \u00b7 ' + a.name : '') + ' \u00b7 ' + Math.round(f[4] * FT).toLocaleString() + ' ft');
      row.addEventListener('click', () => select(i));
      results.append(row);
    }
    if (matches.length > 12) results.append(el('div', { className: 'more', textContent: '+ ' + (matches.length - 12).toLocaleString() + ' more shown on the globe' }));
    if (filters.q.trim() && !matches.length) results.append(el('div', { className: 'more', textContent: 'No aircraft match that search right now' }));
  }

  function fillSelect(sel, items, current) {
    sel.replaceChildren();
    for (const [v, t] of items) sel.append(el('option', { value: v, textContent: t }));
    sel.value = items.some((i) => i[0] === current) ? current : '';
  }
  function rebuildDropdowns() {
    const byAir = new Map();
    const byCountry = new Map();
    for (const f of meta) {
      const a = airlineOf(f[1], air);
      if (a) byAir.set(a.icao, (byAir.get(a.icao) || 0) + 1);
      if (f[9]) byCountry.set(f[9], (byCountry.get(f[9]) || 0) + 1);
    }
    const top = (m, k) => [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, k);
    fillSelect(airlineSel, [['', 'All airlines']].concat(top(byAir, 80).map(([code, c]) => [code, air.byIcao.get(code).name + ' (' + c + ')'])), filters.airline);
    fillSelect(countrySel, [['', 'All countries']].concat(top(byCountry, 60).map(([name, c]) => [name, name + ' (' + c + ')'])), filters.country);
    filters.airline = airlineSel.value;
    filters.country = countrySel.value;
  }

  let qTimer = null;
  qInput.addEventListener('input', () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { filters.q = qInput.value; applyFilters(); }, 120);
  });
  const bind = (sel, key) => sel.addEventListener('change', () => { filters[key] = sel.value; applyFilters(); });
  bind(airlineSel, 'airline'); bind(countrySel, 'country'); bind(altSel, 'alt');
  bind(speedSel, 'speed'); bind(vrateSel, 'vrate'); bind(classSel, 'cls');
  airOnly.addEventListener('change', () => { filters.airlineOnly = airOnly.checked; applyFilters(); });
  emOnly.addEventListener('change', () => { filters.emergencyOnly = emOnly.checked; applyFilters(); });
  sizeSel.addEventListener('change', () => {
    material.uniforms.uScale.value = Number(sizeSel.value);
    try { localStorage.setItem(SIZE_KEY, sizeSel.value); } catch (e) { /* ignore */ }
  });
  resetBtn.addEventListener('click', () => {
    Object.assign(filters, DEFAULT_FILTERS);
    qInput.value = '';
    for (const s of [altSel, speedSel, vrateSel, classSel]) s.value = s.options[0].value;
    airlineSel.value = ''; countrySel.value = '';
    airOnly.checked = false; emOnly.checked = false;
    applyFilters();
  });
  btn.addEventListener('click', () => { panel.hidden = !panel.hidden; });
  closeBtn.addEventListener('click', () => { panel.hidden = true; });

  // ----- plane data -----
  function build(flights) {
    if (points) { globe.remove(points); points.geometry.dispose(); points = null; }
    meta = flights;
    n = flights.length;
    t0 = new Float64Array(n); lat0 = new Float32Array(n); lon0 = new Float32Array(n);
    trk = new Float32Array(n); vel = new Float32Array(n);
    curLat = new Float32Array(n); curLon = new Float32Array(n);
    pos = new Float32Array(n * 3); dir = new Float32Array(n * 3);
    sel = new Float32Array(n); show = new Float32Array(n).fill(1);
    const color = new Float32Array(n * 3);
    hay = new Array(n);
    selected = -1;
    for (let i = 0; i < n; i++) {
      const f = flights[i];
      lat0[i] = f[2] * DEG; lon0[i] = f[3] * DEG;
      vel[i] = f[5]; trk[i] = f[6] * DEG; t0[i] = f[10] * 1000;
      const c = altColor(f[4]);
      color[3 * i] = c[0]; color[3 * i + 1] = c[1]; color[3 * i + 2] = c[2];
      hay[i] = haystack(f, air);
      if (selectedIcao && f[0] === selectedIcao) selected = i;
    }
    if (selected >= 0) sel[selected] = 1;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('aDir', new THREE.BufferAttribute(dir, 3));
    g.setAttribute('aColor', new THREE.BufferAttribute(color, 3));
    g.setAttribute('aSel', new THREE.BufferAttribute(sel, 1));
    g.setAttribute('aShow', new THREE.BufferAttribute(show, 1));
    points = new THREE.Points(g, material);
    points.frustumCulled = false;
    points.visible = enabled;
    globe.add(points);
    tick(Date.now());
    rebuildDropdowns();
    applyFilters();
    if (selectedIcao && selected < 0) { selectedIcao = null; deselect(); } // the selected flight has landed or dropped off
  }

  // move every plane to where it should be right now
  function tick(nowMs) {
    for (let i = 0; i < n; i++) {
      const dt = Math.min(Math.max((nowMs - t0[i]) / 1000, 0), 600);
      const [la, lo] = advance(lat0[i], lon0[i], trk[i], (vel[i] * dt) / EARTH_M);
      curLat[i] = la; curLon[i] = lo;
      const cLa = Math.cos(la);
      const sLa = Math.sin(la);
      const cLo = Math.cos(lo);
      const sLo = Math.sin(lo);
      pos[3 * i] = LIFT * cLa * sLo;
      pos[3 * i + 1] = LIFT * sLa;
      pos[3 * i + 2] = LIFT * cLa * cLo;
      // direction of travel: north and east at this spot, mixed by the track
      const cT = Math.cos(trk[i]);
      const sT = Math.sin(trk[i]);
      dir[3 * i] = cT * (-sLa * sLo) + sT * cLo;
      dir[3 * i + 1] = cT * cLa;
      dir[3 * i + 2] = cT * (-sLa * cLo) - sT * sLo;
    }
    if (points) {
      points.geometry.attributes.position.needsUpdate = true;
      points.geometry.attributes.aDir.needsUpdate = true;
    }
  }

  async function fetchFlights() {
    try {
      const r = await fetch('/api/flights', { credentials: 'same-origin' });
      if (r.status === 401) { location.href = '/login'; return; }
      if (!r.ok) return;
      const snap = await r.json();
      build(snap.flights || []);
    } catch (e) { /* try again at the next refresh */ }
  }

  async function loadAirlines() {
    try {
      const r = await fetch('/static/globe/airlines.json');
      if (!r.ok) return;
      air = buildAirlines(await r.json());
      if (n) { hay = meta.map((f) => haystack(f, air)); rebuildDropdowns(); applyFilters(); }
    } catch (e) { /* airline names are optional */ }
  }
  loadAirlines();

  function setEnabled(on) {
    if (on === enabled) return;
    enabled = on;
    btn.hidden = !on;
    if (on) {
      fetchFlights();
      timer = setInterval(fetchFlights, REFRESH_MS);
    } else {
      clearInterval(timer);
      timer = null;
      panel.hidden = true;
      clearSelection();
      tipEl.hidden = true;
    }
    if (points) points.visible = on;
  }
  window.addEventListener('xyron-layers', (ev) => setEnabled(Array.isArray(ev.detail) && ev.detail.includes('aviation')));
  setEnabled(readEnabled().has('aviation'));

  // ----- hover card and details -----
  function name(i) { return meta[i][1] || meta[i][0].toUpperCase(); }

  function showTip(i, x, y) {
    const f = meta[i];
    const a = airlineOf(f[1], air);
    tipEl.replaceChildren();
    tipEl.append(
      el('div', { className: 'tip-title', textContent: name(i) + (a ? ' \u00b7 ' + a.name : '') }),
      el('div', { textContent: Math.round(f[4] * FT).toLocaleString() + ' ft \u00b7 ' + Math.round(f[5] * KT) + ' kt \u00b7 heading ' + Math.round(f[6]) + '\u00b0' }),
      el('div', { className: 'tip-hint', textContent: 'Click for details' }),
    );
    tipEl.hidden = false;
    const w = tipEl.offsetWidth;
    const h = tipEl.offsetHeight;
    tipEl.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x + 16)) + 'px';
    tipEl.style.top = Math.max(8, Math.min(window.innerHeight - h - 8, y + 16)) + 'px';
  }

  function dlRow(dl, label, value) {
    dl.append(el('dt', { textContent: label }), el('dd', { textContent: value }));
  }

  function renderDetail() {
    if (selected < 0) return;
    const f = meta[selected];
    const a = airlineOf(f[1], air);
    document.getElementById('pname').textContent = name(selected);
    const dl = document.getElementById('pinfo');
    dl.replaceChildren();
    if (a) dlRow(dl, 'Airline', a.name + (a.country ? ' (' + a.country + ')' : ''));
    if (f[1]) dlRow(dl, 'Callsign', f[1]);
    if (a && a.iata) dlRow(dl, 'Flight number', a.iata + f[1].slice(3));
    dlRow(dl, 'Transponder (ICAO24)', f[0].toUpperCase());
    if (f[9]) dlRow(dl, 'Registered in', f[9]);
    dlRow(dl, 'Aircraft type class', CATEGORY[f[8]] || 'Not reported');
    dlRow(dl, 'Altitude', Math.round(f[4] * FT).toLocaleString() + ' ft (' + Math.round(f[4]).toLocaleString() + ' m)');
    dlRow(dl, 'Ground speed', Math.round(f[5] * KT) + ' kt (' + Math.round(f[5] * 3.6) + ' km/h)');
    dlRow(dl, 'Heading', Math.round(f[6]) + '\u00b0');
    dlRow(dl, 'Climb / descent', Math.round(f[7] * FT * 60).toLocaleString() + ' ft/min');
    if (f[11]) dlRow(dl, 'Squawk', f[11] + (EMERGENCY[f[11]] ? ' \u2014 EMERGENCY: ' + EMERGENCY[f[11]] : ''));
    dlRow(dl, 'Position now', (curLat[selected] / DEG).toFixed(2) + '\u00b0, ' + (curLon[selected] / DEG).toFixed(2) + '\u00b0');
    const title = document.getElementById('pevtitle');
    const list = document.getElementById('pevents');
    title.hidden = false;
    title.textContent = 'Source';
    list.replaceChildren(el('div', {
      className: 'ev',
      textContent: 'Positions from The OpenSky Network (opensky-network.org); between updates they are estimated from speed and heading. Airline names from the OpenFlights database, which is community-maintained and may be out of date.',
    }));
  }

  function select(i) {
    deselect(); // clears any selected country dot or event and closes the panel
    selected = i;
    selectedIcao = meta[i][0];
    sel[i] = 1;
    points.geometry.attributes.aSel.needsUpdate = true;
    renderDetail();
    openPanel();
    flyTo(curLat[i] / DEG, curLon[i] / DEG, 2.4);
  }

  function clearSelection() {
    if (selected >= 0 && points) {
      sel[selected] = 0;
      points.geometry.attributes.aSel.needsUpdate = true;
    }
    selected = -1;
    selectedIcao = null;
  }

  function hit(x, y) {
    if (!enabled || !n) return -1;
    return hitPlanes(THREE, pos, n, globe, camera, canvas.getBoundingClientRect(), x, y, HIT_PX, show);
  }

  return {
    onHover(x, y) {
      if (x < 0) return false;
      const i = hit(x, y);
      if (i < 0) return false;
      showTip(i, x, y);
      return true;
    },
    onClick(x, y) {
      const i = hit(x, y);
      if (i < 0) return false;
      select(i);
      return true;
    },
    clear: clearSelection,
    onFrame(now) {
      if (!enabled || !points) return;
      renderer.getDrawingBufferSize(bufSize);
      material.uniforms.uPx.value = bufSize.y / (2 * Math.tan((camera.fov * DEG) / 2));
      material.uniforms.uAspect.value = camera.aspect;
      if (now - lastTick >= TICK_MS) { lastTick = now; tick(Date.now()); }
      if (selected >= 0 && now - lastDetail >= 1000) { lastDetail = now; renderDetail(); }
    },
  };
}
