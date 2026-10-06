// Live ships layer: ship icons that keep moving between updates (dead reckoning), search and filters, hover cards, and a
// detail panel with the path we have recorded and a line to the destination port. It mirrors the aircraft layer.
const DEG = Math.PI / 180;
const EARTH_M = 6371000;
const KT = 0.514444; // metres per second in one knot
const STORE_KEY = 'xyron.layers';
const SIZE_KEY = 'xyron.shipsize';
const REFRESH_MS = 60000;
const TICK_MS = 250;
const LIFT = 1.006;
const HIT_PX = 11;
const MAX_DR_S = 1200; // never guess more than 20 minutes ahead, because ships turn
const R = { mmsi: 0, lat: 1, lon: 2, sog: 3, cog: 4, hdg: 5, type: 6, len: 7, name: 8, nav: 9, t: 10, flag: 11 };

const VERTEX = `
attribute vec3 aDir;
attribute vec3 aColor;
attribute float aSel;
attribute float aShow;
attribute float aIcon;
attribute float aSize;
uniform float uPx;
uniform float uAspect;
uniform float uScale;
varying vec3 vColor;
varying float vAngle;
varying float vSel;
varying float vIcon;
void main() {
  vColor = aColor;
  vSel = aSel;
  vIcon = aIcon;
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
  float size = clamp(0.028 * uPx / -mv.z, 11.0, 38.0) * uScale * aSize;
  gl_PointSize = min(size * (1.0 + 1.3 * aSel), 110.0);
  gl_Position = clipA;
}`;

const FRAGMENT = `
uniform sampler2D uTex;
varying vec3 vColor;
varying float vAngle;
varying float vSel;
varying float vIcon;
void main() {
  vec2 p = vec2(gl_PointCoord.x * 2.0 - 1.0, 1.0 - gl_PointCoord.y * 2.0);
  float c = cos(vAngle);
  float s = sin(vAngle);
  vec2 q = vec2(p.x * c - p.y * s, p.x * s + p.y * c);
  vec2 uv = vec2(q.x * 0.5 + 0.5, q.y * 0.5 + 0.5);
  float inside = step(0.0, uv.x) * step(uv.x, 1.0) * step(0.0, uv.y) * step(uv.y, 1.0);
  vec2 uvc = clamp(uv, 0.002, 0.998);
  float ic = floor(vIcon + 0.5);
  vec2 cell = vec2(mod(ic, 4.0), floor(ic / 4.0));
  vec4 t = texture2D(uTex, vec2((cell.x + uvc.x) / 4.0, (3.0 - cell.y + uvc.y) / 4.0));
  float shape = t.a * inside;
  float shade = t.r;
  float d = length(p);
  float ring = smoothstep(0.78, 0.84, d) * (1.0 - smoothstep(0.93, 0.98, d)) * vSel;
  float a = max(shape, ring);
  if (a < 0.03) discard;
  vec3 col = mix(vColor * (0.32 + 0.68 * shade), vec3(0.55, 0.9, 1.0), vSel);
  gl_FragColor = vec4(col, a);
}`;

// Top-down ship silhouettes, bow pointing up, on a 128 by 128 grid. Each is a list of simple shapes. White is the hull, greys are
// decks and cabins (the shader darkens them), and the dark outline keeps small ships readable against the globe.
const OUTLINE = '#141414';
function hullPoints(cx, top, bottom, width, bowFrac, sternFrac) {
  const half = width / 2;
  const len = bottom - top;
  const prof = (u) => { // u runs from the bow tip (0) to the stern (1)
    const bow = Math.pow(Math.min(1, u / bowFrac), 0.6);
    const stern = sternFrac ? Math.max(0.6, Math.pow(Math.min(1, (1 - u) / sternFrac), 0.5)) : 1;
    return half * bow * stern;
  };
  const N = 20;
  const pts = [];
  for (let i = 0; i <= N; i++) pts.push([+(cx - prof(i / N)).toFixed(1), +(top + (i / N) * len).toFixed(1)]);
  for (let i = N; i >= 0; i--) pts.push([+(cx + prof(i / N)).toFixed(1), +(top + (i / N) * len).toFixed(1)]);
  return pts;
}
const hull = (cx, top, bottom, width, bowFrac, sternFrac, fill = '#ffffff') => ({ t: 'poly', f: fill, s: true, p: hullPoints(cx, top, bottom, width, bowFrac, sternFrac) });
const box = (x, y, w, h, fill = '#d6d6d6', s = true) => ({ t: 'rect', f: fill, s, x, y, w, h });
const dot = (x, y, r, fill = '#8a8a8a', s = true) => ({ t: 'circ', f: fill, s, x, y, r });
const bar = (x1, y1, x2, y2, w = 3, c = '#7a7a7a') => ({ t: 'line', c, w, p: [[x1, y1], [x2, y2]] });
const containers = [];
for (const y of [34, 52, 70, 88]) for (const dx of [-15, -5, 5]) containers.push(box(64 + dx - 0.5, y, 10, 15, '#8d8d8d', false));
export const ICON_DEFS = [
  // 0 cargo and container ships: stacks of boxes and a bridge at the stern
  [hull(64, 4, 124, 40, 0.2, 0.06), ...containers, box(48, 102, 32, 17, '#dcdcdc')],
  // 1 tankers: a long flat deck with a pipe run and manifolds, bridge aft
  [hull(64, 4, 124, 42, 0.15, 0.05), bar(64, 20, 64, 98, 3), bar(52, 40, 76, 40, 2), bar(52, 54, 76, 54, 2), bar(52, 68, 76, 68, 2), bar(52, 82, 76, 82, 2), box(47, 102, 34, 17, '#dcdcdc'), dot(64, 28, 3, '#bdbdbd', false)],
  // 2 passenger ships and ferries: wide hull, tiers of decks, funnel
  [hull(64, 6, 122, 50, 0.2, 0.08), box(46, 30, 36, 78, '#dedede'), box(50, 36, 28, 9, '#9a9a9a', false), box(50, 52, 28, 9, '#9a9a9a', false), box(50, 68, 28, 9, '#9a9a9a', false), box(50, 84, 28, 9, '#9a9a9a', false), dot(64, 98, 6, '#f2f2f2')],
  // 3 fishing vessels: small, wheelhouse forward, gear aft
  [hull(64, 18, 114, 32, 0.3, 0.1), box(54, 36, 20, 22, '#dcdcdc'), bar(64, 60, 64, 104, 3), bar(50, 70, 78, 70, 2), bar(52, 90, 76, 90, 2)],
  // 4 tugs and service vessels: short and stubby, wheelhouse and funnel
  [hull(64, 30, 108, 42, 0.34, 0.12), box(53, 44, 22, 24, '#dcdcdc'), dot(64, 78, 5, '#bdbdbd'), dot(64, 95, 3, '#8a8a8a', false)],
  // 5 sailing and pleasure craft: slim hull with sails
  [hull(64, 12, 114, 22, 0.3, 0.1), { t: 'poly', f: '#ececec', s: true, p: [[64, 18], [90, 88], [64, 88]] }, { t: 'poly', f: '#d0d0d0', s: true, p: [[61, 26], [44, 80], [61, 80]] }, bar(64, 16, 64, 96, 2, '#555555')],
  // 6 high-speed craft: twin slim hulls joined by a deck
  [hull(49, 6, 122, 14, 0.3, 0.05), hull(79, 6, 122, 14, 0.3, 0.05), box(44, 52, 40, 36, '#dcdcdc'), box(52, 58, 24, 12, '#9a9a9a', false)],
  // 7 military and law enforcement: sleek hull, gun forward, superstructure and helipad
  [hull(64, 3, 125, 30, 0.34, 0.05), dot(64, 34, 6, '#bdbdbd'), bar(64, 34, 64, 12, 3, '#5a5a5a'), box(55, 52, 18, 30, '#dcdcdc'), dot(64, 104, 9, '#c8c8c8')],
  // 8 anything else
  [hull(64, 8, 120, 36, 0.24, 0.06), box(52, 86, 24, 22, '#dcdcdc')],
];
export const ICON_INDEX = { cargo: 0, tanker: 1, passenger: 2, fishing: 3, service: 4, pleasure: 5, highspeed: 6, military: 7, other: 8 };

export function drawIcon(g, def) {
  for (const sh of def) {
    g.beginPath();
    if (sh.t === 'poly') sh.p.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
    else if (sh.t === 'rect') g.rect(sh.x, sh.y, sh.w, sh.h);
    else if (sh.t === 'circ') g.arc(sh.x, sh.y, sh.r, 0, Math.PI * 2);
    else if (sh.t === 'line') { g.moveTo(sh.p[0][0], sh.p[0][1]); g.lineTo(sh.p[1][0], sh.p[1][1]); }
    if (sh.t === 'poly') g.closePath();
    if (sh.t === 'line') { g.strokeStyle = sh.c; g.lineWidth = sh.w; g.lineCap = 'round'; g.stroke(); continue; }
    g.fillStyle = sh.f;
    g.fill();
    if (sh.s) { g.strokeStyle = OUTLINE; g.lineWidth = 3.2; g.lineJoin = 'round'; g.stroke(); }
  }
}
// all the icons in one 4 by 4 picture, so one texture serves every ship
function shipAtlas(THREE) {
  const c = document.createElement('canvas');
  c.width = c.height = 512;
  const g = c.getContext('2d');
  ICON_DEFS.forEach((def, i) => {
    g.save();
    g.translate((i % 4) * 128, Math.floor(i / 4) * 128);
    drawIcon(g, def);
    g.restore();
  });
  const t = new THREE.CanvasTexture(c);
  t.generateMipmaps = true;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.magFilter = THREE.LinearFilter;
  return t;
}
// bigger ships are drawn a little bigger; ships that have not reported a length get an average size
export const sizeFactor = (len) => (len > 0 ? 0.8 + 0.5 * Math.min(len, 330) / 330 : 0.9);

// ----- ship kinds (the same table the server uses) -----
export const CATEGORY_LABEL = {
  cargo: 'Cargo ships', tanker: 'Tankers', passenger: 'Passenger ships', fishing: 'Fishing', service: 'Tugs and service vessels',
  pleasure: 'Sailing and pleasure craft', highspeed: 'High-speed craft', military: 'Military and law enforcement', other: 'Other',
};
const COLORS = {
  cargo: [0.31, 0.62, 1.0], tanker: [1.0, 0.54, 0.24], passenger: [0.82, 0.48, 1.0], fishing: [0.32, 0.88, 0.48], service: [1.0, 0.82, 0.25],
  pleasure: [0.9, 0.95, 1.0], highspeed: [0.24, 0.9, 1.0], military: [1.0, 0.3, 0.37], other: [0.62, 0.69, 0.78],
};
const SPECIAL = { 30: 'fishing', 31: 'service', 32: 'service', 33: 'service', 34: 'service', 35: 'military', 36: 'pleasure', 37: 'pleasure', 50: 'service', 51: 'service', 52: 'service', 53: 'service', 54: 'service', 55: 'military', 58: 'service', 59: 'service' };
export function category(code) {
  code = Number(code) || 0;
  if (SPECIAL[code]) return SPECIAL[code];
  if (code >= 60 && code <= 69) return 'passenger';
  if (code >= 70 && code <= 79) return 'cargo';
  if (code >= 80 && code <= 89) return 'tanker';
  if ((code >= 20 && code <= 29) || (code >= 40 && code <= 49)) return 'highspeed';
  return 'other';
}
export const colorOf = (code) => COLORS[category(code)];

// ----- geometry (pure functions, so they can be tested) -----
export function advance(latRad, lonRad, trackRad, distRad) {
  const sinLat = Math.sin(latRad);
  const cosLat = Math.cos(latRad);
  const sinD = Math.sin(distRad);
  const cosD = Math.cos(distRad);
  const lat2 = Math.asin(sinLat * cosD + cosLat * sinD * Math.cos(trackRad));
  const lon2 = lonRad + Math.atan2(Math.sin(trackRad) * sinD * cosLat, cosD - sinLat * Math.sin(lat2));
  return [lat2, lon2];
}
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
export function fillArc(out, a, b, steps, lift) {
  for (let i = 0; i <= steps; i++) {
    const p = slerp(a, b, i / steps);
    const h = lift + 0.006 * Math.sin(Math.PI * (i / steps));
    out[3 * i] = p[0] * h; out[3 * i + 1] = p[1] * h; out[3 * i + 2] = p[2] * h;
  }
}
// Which ship (index) is under the pointer, or -1. Hidden ships and ships on the far side never match.
export function hitShips(THREE, pos, n, globe, camera, rect, x, y, maxPx, show) {
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
    const d = Math.hypot(rect.left + ((v.x + 1) / 2) * rect.width - x, rect.top + ((1 - v.y) / 2) * rect.height - y);
    if (d < bestD) { bestD = d; best = i; }
  }
  return best;
}

// ----- filters (pure) -----
export const DEFAULT_FILTERS = { q: '', cat: 'any', flag: '', moving: false };
export function passesFilters(s, f) {
  if (f.cat !== 'any' && category(s[R.type]) !== f.cat) return false;
  if (f.flag && s[R.flag] !== f.flag) return false;
  if (f.moving && !(s[R.sog] >= 0.5)) return false;
  const q = f.q.trim().toUpperCase();
  if (q && !(String(s[R.name]).toUpperCase().includes(q) || String(s[R.mmsi]).includes(q))) return false;
  return true;
}
export function durationText(hours) {
  if (!isFinite(hours) || hours < 0) return '';
  const m = Math.round(hours * 60);
  if (m < 60) return m + ' min';
  if (m < 2880) return Math.floor(m / 60) + ' h ' + (m % 60) + ' min';
  return Math.floor(m / 1440) + ' d ' + Math.round((m % 1440) / 60) + ' h';
}
export function ageText(sec) {
  if (sec === null || sec === undefined) return '';
  if (sec < 90) return sec + ' s ago';
  if (sec < 5400) return Math.round(sec / 60) + ' min ago';
  return Math.round(sec / 3600) + ' h ago';
}

function el(tag, props, ...kids) {
  const e = document.createElement(tag);
  if (props) Object.assign(e, props);
  for (const k of kids) if (k) e.append(k);
  return e;
}
function readEnabled() {
  try {
    const v = JSON.parse(localStorage.getItem(STORE_KEY));
    if (Array.isArray(v)) return new Set(v);
  } catch (e) { /* storage unavailable */ }
  return new Set();
}
function readSize() {
  try { return localStorage.getItem(SIZE_KEY) || '1'; } catch (e) { return '1'; }
}
const SIZE_OPTS = [['0.7', 'Small'], ['1', 'Normal'], ['1.4', 'Large'], ['1.9', 'Extra large']];

export function init(ctx) {
  const { THREE, globe, camera, canvas, deselect, flyTo, openPanel } = ctx;
  const tipEl = document.getElementById('tip');
  const material = new THREE.ShaderMaterial({
    uniforms: { uPx: { value: 600 }, uAspect: { value: 1 }, uScale: { value: Number(readSize()) }, uTex: { value: shipAtlas(THREE) } },
    vertexShader: VERTEX, fragmentShader: FRAGMENT, transparent: true, depthWrite: false,
  });

  let enabled = false;
  let timer = null;
  let n = 0;
  let meta = [];
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
  let selectedMmsi = null;
  let lastTick = 0;
  let lastDetail = 0;
  let info = null; // null, or { state: 'loading' | 'ok' | 'error', d }
  const filters = { ...DEFAULT_FILTERS };
  const bufSize = new THREE.Vector2();

  // ----- filter panel -----
  const stage = document.getElementById('stage');
  const btn = el('button', { id: 'shipfilterbtn', className: 'chip', type: 'button', hidden: true, textContent: 'Ship filters' });
  const panel = el('div', { id: 'shipfilters', className: 'avpanel', hidden: true });
  const qInput = el('input', { type: 'search', id: 'shq', placeholder: 'Ship name or MMSI\u2026', autocomplete: 'off' });
  const catSel = el('select', { id: 'shcat' });
  const flagSel = el('select', { id: 'shflag' });
  const sizeSel = el('select', { id: 'shsize' });
  for (const [v, t] of SIZE_OPTS) sizeSel.append(el('option', { value: v, textContent: t }));
  sizeSel.value = readSize();
  const movingOnly = el('input', { type: 'checkbox', id: 'shmoving' });
  const countEl = el('div', { className: 'avcount' });
  const resetBtn = el('button', { type: 'button', className: 'small secondary', textContent: 'Reset filters' });
  const closeBtn = el('button', { type: 'button', className: 'avx', textContent: '\u00d7' });
  closeBtn.setAttribute('aria-label', 'Close ship filters');
  const field = (label, control) => el('div', { className: 'avfield' }, el('label', { htmlFor: control.id, textContent: label }), control);
  panel.append(
    el('div', { className: 'avhead' }, el('strong', { textContent: 'Ship filters' }), closeBtn),
    field('Search', qInput), field('Kind of ship', catSel), field('Flag', flagSel),
    el('label', { className: 'check' }, movingOnly, ' Moving ships only'),
    field('Ship icon size', sizeSel), countEl, resetBtn,
  );
  stage.append(btn, panel);

  function activeCount() {
    return (filters.q.trim() ? 1 : 0) + (filters.cat !== 'any' ? 1 : 0) + (filters.flag ? 1 : 0) + (filters.moving ? 1 : 0);
  }
  function rebuildDropdowns() {
    const cats = {};
    const flags = {};
    for (const s of meta) {
      const c = category(s[R.type]);
      cats[c] = (cats[c] || 0) + 1;
      if (s[R.flag]) flags[s[R.flag]] = (flags[s[R.flag]] || 0) + 1;
    }
    catSel.replaceChildren(el('option', { value: 'any', textContent: 'All kinds' }));
    for (const c of Object.keys(CATEGORY_LABEL)) if (cats[c]) catSel.append(el('option', { value: c, textContent: CATEGORY_LABEL[c] + ' (' + cats[c].toLocaleString() + ')' }));
    flagSel.replaceChildren(el('option', { value: '', textContent: 'All flags' }));
    for (const f of Object.keys(flags).sort((a, b) => flags[b] - flags[a]).slice(0, 80)) flagSel.append(el('option', { value: f, textContent: f + ' (' + flags[f].toLocaleString() + ')' }));
    catSel.value = filters.cat; flagSel.value = filters.flag;
  }
  function applyFilters() {
    if (!n) { countEl.textContent = ''; return; }
    let shown = 0;
    for (let i = 0; i < n; i++) {
      const ok = passesFilters(meta[i], filters);
      show[i] = ok ? 1 : 0;
      if (ok) shown++;
    }
    if (points) points.geometry.attributes.aShow.needsUpdate = true;
    const act = activeCount();
    countEl.textContent = 'Showing ' + shown.toLocaleString() + ' of ' + n.toLocaleString() + ' ships';
    btn.textContent = act ? 'Ship filters (' + act + ')' : 'Ship filters';
    btn.classList.toggle('on', act > 0);
  }
  let qTimer = null;
  qInput.addEventListener('input', () => { clearTimeout(qTimer); qTimer = setTimeout(() => { filters.q = qInput.value; applyFilters(); }, 150); });
  catSel.addEventListener('change', () => { filters.cat = catSel.value; applyFilters(); });
  flagSel.addEventListener('change', () => { filters.flag = flagSel.value; applyFilters(); });
  movingOnly.addEventListener('change', () => { filters.moving = movingOnly.checked; applyFilters(); });
  sizeSel.addEventListener('change', () => {
    material.uniforms.uScale.value = Number(sizeSel.value);
    try { localStorage.setItem(SIZE_KEY, sizeSel.value); } catch (e) { /* ignore */ }
  });
  resetBtn.addEventListener('click', () => {
    Object.assign(filters, DEFAULT_FILTERS);
    qInput.value = ''; catSel.value = 'any'; flagSel.value = ''; movingOnly.checked = false;
    applyFilters();
  });
  btn.addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) { const av = document.getElementById('avfilters'); if (av) av.hidden = true; }
  });
  closeBtn.addEventListener('click', () => { panel.hidden = true; });
  const avBtn = document.getElementById('filterbtn');
  if (avBtn) avBtn.addEventListener('click', () => { panel.hidden = true; });

  // ----- the lines for the selected ship: the path we recorded, and the way to the destination port -----
  const TRAIL_MAX = 200;
  const ARC_STEPS = 48;
  const trailPos = new Float32Array(TRAIL_MAX * 3);
  const trailGeo = new THREE.BufferGeometry();
  trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPos, 3));
  trailGeo.setDrawRange(0, 0);
  const trailLine = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0xffc847, transparent: true, opacity: 0.95, depthWrite: false }));
  const aheadPos = new Float32Array((ARC_STEPS + 1) * 3);
  const aheadGeo = new THREE.BufferGeometry();
  aheadGeo.setAttribute('position', new THREE.BufferAttribute(aheadPos, 3));
  const aheadLine = new THREE.Line(aheadGeo, new THREE.LineDashedMaterial({ color: 0x8ce0ff, dashSize: 0.012, gapSize: 0.012, transparent: true, opacity: 0.85, depthWrite: false }));
  const portPos = new Float32Array(3);
  const portGeo = new THREE.BufferGeometry();
  portGeo.setAttribute('position', new THREE.BufferAttribute(portPos, 3));
  portGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array([0.4, 0.95, 0.6]), 3));
  const dotCanvas = document.createElement('canvas');
  dotCanvas.width = dotCanvas.height = 32;
  const dctx = dotCanvas.getContext('2d');
  dctx.beginPath(); dctx.arc(16, 16, 14, 0, Math.PI * 2); dctx.fillStyle = '#fff'; dctx.fill();
  const portDot = new THREE.Points(portGeo, new THREE.PointsMaterial({ size: 0.03, vertexColors: true, map: new THREE.CanvasTexture(dotCanvas), sizeAttenuation: true, transparent: true, depthWrite: false, alphaTest: 0.1 }));
  for (const o of [trailLine, aheadLine, portDot]) { o.visible = false; o.frustumCulled = false; globe.add(o); }
  let trailCount = 0;

  function hideLines() { trailLine.visible = false; aheadLine.visible = false; portDot.visible = false; }
  function updateLines() {
    if (selected < 0 || !info || info.state !== 'ok') { hideLines(); return; }
    const d = info.d;
    const trail = (d.trail || []).slice(-(TRAIL_MAX - 1));
    let c = 0;
    for (const [, la, lo] of trail) {
      const u = toUnit(la, lo);
      trailPos[3 * c] = u[0] * 1.004; trailPos[3 * c + 1] = u[1] * 1.004; trailPos[3 * c + 2] = u[2] * 1.004;
      c++;
    }
    trailPos[3 * c] = pos[3 * selected] * 1.004 / LIFT; trailPos[3 * c + 1] = pos[3 * selected + 1] * 1.004 / LIFT; trailPos[3 * c + 2] = pos[3 * selected + 2] * 1.004 / LIFT;
    c++;
    trailCount = c;
    trailGeo.setDrawRange(0, c);
    trailGeo.attributes.position.needsUpdate = true;
    trailLine.visible = c >= 2;
    if (d.port) {
      const here = [pos[3 * selected] / LIFT, pos[3 * selected + 1] / LIFT, pos[3 * selected + 2] / LIFT];
      const there = toUnit(d.port.lat, d.port.lon);
      fillArc(aheadPos, here, there, ARC_STEPS, 1.005);
      aheadGeo.attributes.position.needsUpdate = true;
      aheadLine.computeLineDistances();
      aheadLine.visible = true;
      portPos.set([there[0] * 1.006, there[1] * 1.006, there[2] * 1.006]);
      portGeo.attributes.position.needsUpdate = true;
      portDot.visible = true;
    } else { aheadLine.visible = false; portDot.visible = false; }
  }

  // ----- ship data -----
  function build(rows) {
    if (points) { globe.remove(points); points.geometry.dispose(); points = null; }
    meta = rows;
    n = rows.length;
    t0 = new Float64Array(n); lat0 = new Float32Array(n); lon0 = new Float32Array(n);
    trk = new Float32Array(n); vel = new Float32Array(n);
    curLat = new Float32Array(n); curLon = new Float32Array(n);
    pos = new Float32Array(n * 3); dir = new Float32Array(n * 3);
    sel = new Float32Array(n); show = new Float32Array(n).fill(1);
    const color = new Float32Array(n * 3);
    const icon = new Float32Array(n);
    const size = new Float32Array(n);
    selected = -1;
    for (let i = 0; i < n; i++) {
      const s = rows[i];
      lat0[i] = s[R.lat] * DEG; lon0[i] = s[R.lon] * DEG;
      t0[i] = s[R.t] * 1000;
      const moving = s[R.sog] >= 0.5 && s[R.cog] >= 0;
      vel[i] = moving ? s[R.sog] * KT : 0;
      trk[i] = (s[R.hdg] >= 0 ? s[R.hdg] : s[R.cog] >= 0 ? s[R.cog] : 0) * DEG; // the way the icon points
      const c = colorOf(s[R.type]);
      color[3 * i] = c[0]; color[3 * i + 1] = c[1]; color[3 * i + 2] = c[2];
      icon[i] = ICON_INDEX[category(s[R.type])];
      size[i] = sizeFactor(s[R.len]);
      if (selectedMmsi !== null && s[R.mmsi] === selectedMmsi) selected = i;
    }
    if (selected >= 0) sel[selected] = 1;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('aDir', new THREE.BufferAttribute(dir, 3));
    g.setAttribute('aColor', new THREE.BufferAttribute(color, 3));
    g.setAttribute('aSel', new THREE.BufferAttribute(sel, 1));
    g.setAttribute('aShow', new THREE.BufferAttribute(show, 1));
    g.setAttribute('aIcon', new THREE.BufferAttribute(icon, 1));
    g.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
    points = new THREE.Points(g, material);
    points.frustumCulled = false;
    points.visible = enabled;
    globe.add(points);
    tick(Date.now());
    rebuildDropdowns();
    applyFilters();
    if (selectedMmsi !== null && selected < 0) { selectedMmsi = null; hideLines(); deselect(); } // that ship has gone quiet
  }

  // move every ship to where it should be right now (the course over ground is used to move, the heading to point)
  function tick(nowMs) {
    for (let i = 0; i < n; i++) {
      const dt = Math.min(Math.max((nowMs - t0[i]) / 1000, 0), MAX_DR_S);
      let la = lat0[i];
      let lo = lon0[i];
      const s = meta[i];
      if (vel[i] > 0 && dt > 0) [la, lo] = advance(la, lo, s[R.cog] * DEG, (vel[i] * dt) / EARTH_M);
      curLat[i] = la; curLon[i] = lo;
      const cLa = Math.cos(la), sLa = Math.sin(la), cLo = Math.cos(lo), sLo = Math.sin(lo);
      pos[3 * i] = LIFT * cLa * sLo;
      pos[3 * i + 1] = LIFT * sLa;
      pos[3 * i + 2] = LIFT * cLa * cLo;
      const cT = Math.cos(trk[i]), sT = Math.sin(trk[i]);
      dir[3 * i] = cT * (-sLa * sLo) + sT * cLo;
      dir[3 * i + 1] = cT * cLa;
      dir[3 * i + 2] = cT * (-sLa * cLo) - sT * sLo;
    }
    if (points) {
      points.geometry.attributes.position.needsUpdate = true;
      points.geometry.attributes.aDir.needsUpdate = true;
    }
  }

  async function fetchShips() {
    try {
      const r = await fetch('/api/ships', { credentials: 'same-origin' });
      if (r.status === 401) { location.href = '/login'; return; }
      if (!r.ok) return; // keep showing what we have
      const snap = await r.json();
      build(Array.isArray(snap.ships) ? snap.ships : []);
    } catch (e) { /* try again at the next refresh */ }
  }

  function setEnabled(on) {
    if (on === enabled) return;
    enabled = on;
    btn.hidden = !on;
    if (on) {
      fetchShips();
      timer = setInterval(fetchShips, REFRESH_MS);
    } else {
      clearInterval(timer);
      timer = null;
      panel.hidden = true;
      clearSelection();
      tipEl.hidden = true;
    }
    if (points) points.visible = on;
  }
  window.addEventListener('xyron-layers', (ev) => setEnabled(Array.isArray(ev.detail) && ev.detail.includes('ships')));
  setEnabled(readEnabled().has('ships'));

  // ----- hover card and details -----
  const shipName = (i) => meta[i][R.name] || 'MMSI ' + meta[i][R.mmsi];
  function showTip(i, x, y) {
    const s = meta[i];
    tipEl.replaceChildren(
      el('div', { className: 'tip-title', textContent: shipName(i) }),
      el('div', { textContent: [CATEGORY_LABEL[category(s[R.type])], s[R.flag]].filter(Boolean).join(' \u00b7 ') }),
      el('div', { textContent: s[R.sog] >= 0.5 ? Math.round(s[R.sog]) + ' kn \u00b7 heading ' + (s[R.hdg] >= 0 ? s[R.hdg] : s[R.cog] >= 0 ? s[R.cog] : '?') + '\u00b0' : 'Not moving' }),
      el('div', { className: 'tip-hint', textContent: 'Click for details' }),
    );
    tipEl.hidden = false;
    const w = tipEl.offsetWidth;
    const h = tipEl.offsetHeight;
    tipEl.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x + 16)) + 'px';
    tipEl.style.top = Math.max(8, Math.min(window.innerHeight - h - 8, y + 16)) + 'px';
  }
  const dlRow = (dl, label, value) => { if (value !== null && value !== undefined && value !== '') dl.append(el('dt', { textContent: label }), el('dd', { textContent: String(value) })); };

  function renderDetail() {
    if (selected < 0) return;
    const s = meta[selected];
    const d = info && info.state === 'ok' ? info.d : null;
    document.getElementById('pname').textContent = (d && d.name) || shipName(selected);
    const dl = document.getElementById('pinfo');
    dl.replaceChildren();
    dlRow(dl, 'Flag', s[R.flag] || '(not identified)');
    dlRow(dl, 'Kind of ship', d ? d.type_text : CATEGORY_LABEL[category(s[R.type])]);
    dlRow(dl, 'MMSI', s[R.mmsi]);
    if (d) {
      dlRow(dl, 'IMO number', d.imo);
      dlRow(dl, 'Call sign', d.callsign);
      if (d.length) dlRow(dl, 'Size', d.length + ' m long' + (d.beam ? ', ' + d.beam + ' m wide' : ''));
      if (d.draught) dlRow(dl, 'Draught', d.draught + ' m');
    }
    dlRow(dl, 'Speed', s[R.sog] >= 0.5 ? Math.round(s[R.sog] * 10) / 10 + ' kn (' + Math.round(s[R.sog] * 1.852) + ' km/h)' : 'Not moving');
    if (s[R.cog] >= 0) dlRow(dl, 'Course over ground', Math.round(s[R.cog]) + '\u00b0');
    if (s[R.hdg] >= 0) dlRow(dl, 'Heading', Math.round(s[R.hdg]) + '\u00b0');
    if (d) dlRow(dl, 'Status', d.nav_text);
    if (!info || info.state === 'loading') dlRow(dl, 'Destination', 'Looking up\u2026');
    else if (info.state === 'error') dlRow(dl, 'Destination', 'Lookup failed, try again later');
    else {
      dlRow(dl, 'Destination (as broadcast)', d.destination || 'Not set');
      if (d.port) {
        dlRow(dl, 'Matched port', d.port.name + ' (' + d.port.locode + ', matched by ' + d.port.how + ')');
        const km = distanceKm(curLat[selected] / DEG, curLon[selected] / DEG, d.port.lat, d.port.lon);
        dlRow(dl, 'Distance to it', Math.round(km).toLocaleString() + ' km in a straight line');
        if (s[R.sog] >= 3) dlRow(dl, 'At this speed', durationText(km / (s[R.sog] * 1.852)) + ' (rough, ignores the route)');
      } else if (d.destination) dlRow(dl, 'Matched port', 'None, the text does not name a port we recognise');
      if (d.eta) dlRow(dl, 'ETA (as broadcast)', new Date(d.eta).toLocaleString());
      if (d.trail && d.trail.length > 1) dlRow(dl, 'Path recorded', 'Since ' + new Date(d.trail[0][0] * 1000).toLocaleString() + ' (' + d.trail.length + ' points)');
    }
    dlRow(dl, 'Position now', (curLat[selected] / DEG).toFixed(2) + '\u00b0, ' + (curLon[selected] / DEG).toFixed(2) + '\u00b0');
    dlRow(dl, 'Last report', ageText(Math.max(0, Math.round(Date.now() / 1000 - s[R.t]))));
    const title = document.getElementById('pevtitle');
    const list = document.getElementById('pevents');
    title.hidden = false;
    title.textContent = 'Source';
    list.replaceChildren(el('div', {
      className: 'ev',
      textContent: 'Positions from AISstream (aisstream.io), which gathers ship transponder signals from receivers on land, so coverage is best near coasts. Between reports positions are estimated from speed and course. Ships do not broadcast where they came from, so the gold line is only the path we have recorded; destinations are typed in by crews and can be wrong or out of date.',
    }));
  }

  function select(i) {
    deselect(); // clears any selected country dot, event or aircraft and closes the panel
    selected = i;
    selectedMmsi = meta[i][R.mmsi];
    sel[i] = 1;
    points.geometry.attributes.aSel.needsUpdate = true;
    info = { state: 'loading' };
    renderDetail();
    openPanel();
    flyTo(curLat[i] / DEG, curLon[i] / DEG, 2.2);
    loadDetail(selectedMmsi);
  }
  async function loadDetail(mmsi) {
    try {
      const r = await fetch('/api/ship/' + encodeURIComponent(mmsi), { credentials: 'same-origin' });
      if (selectedMmsi !== mmsi) return; // the user has moved on
      if (!r.ok) { info = { state: 'error' }; renderDetail(); return; }
      const d = await r.json();
      if (selectedMmsi !== mmsi) return;
      info = { state: 'ok', d };
      updateLines();
      renderDetail();
    } catch (e) {
      if (selectedMmsi === mmsi) { info = { state: 'error' }; renderDetail(); }
    }
  }
  function clearSelection() {
    if (selected >= 0 && points) { sel[selected] = 0; points.geometry.attributes.aSel.needsUpdate = true; }
    selected = -1;
    selectedMmsi = null;
    info = null;
    hideLines();
  }
  function hit(x, y) {
    if (!enabled || !n) return -1;
    return hitShips(THREE, pos, n, globe, camera, canvas.getBoundingClientRect(), x, y, HIT_PX, show);
  }

  return {
    onHover(x, y) {
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
      if (!enabled || !n) return;
      renderBuf();
      if (now - lastTick >= TICK_MS) { lastTick = now; tick(Date.now()); }
      if (selected >= 0 && now - lastDetail >= 1000) { lastDetail = now; updateLines(); renderDetail(); }
    },
  };

  function renderBuf() {
    const r = ctx.renderer;
    if (!r) return;
    r.getDrawingBufferSize(bufSize);
    material.uniforms.uPx.value = bufSize.y;
    material.uniforms.uAspect.value = bufSize.x / bufSize.y;
  }
}
