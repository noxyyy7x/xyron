// Live data layers: toggles, glowing event markers, hover cards and event details.
// To add a layer, add an entry to STYLE below and a feed on the server.
const DEG = Math.PI / 180;
const STORE_KEY = 'xyron.layers';

const VERTEX = `
attribute float aSize;
attribute float aPhase;
attribute float aPulse;
attribute vec3 aColor;
uniform float uTime;
uniform float uPx;
varying float vPhase;
varying float vPulse;
varying vec3 vColor;
void main() {
  vPhase = aPhase;
  vPulse = aPulse;
  vColor = aColor;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  float pulse = 1.0 + 0.22 * aPulse * sin(uTime * 2.0 + aPhase * 6.2831);
  gl_PointSize = max(7.0, aSize * pulse * uPx / -mv.z);
  gl_Position = projectionMatrix * mv;
}`;

const FRAGMENT = `
varying float vPhase;
varying float vPulse;
varying vec3 vColor;
uniform float uTime;
void main() {
  float d = length(gl_PointCoord - 0.5) * 2.0;
  if (d > 1.0) discard;
  float core = smoothstep(0.34, 0.0, d);
  float glow = pow(1.0 - d, 2.0) * 0.55;
  float t = fract(uTime * 0.5 + vPhase);
  float ring = smoothstep(0.1, 0.0, abs(d - t)) * (1.0 - t) * vPulse;
  float a = clamp(core + glow + ring * 0.8, 0.0, 1.0);
  gl_FragColor = vec4(vColor, a);
}`;

function ago(ms) {
  const m = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (m < 1) return 'just now';
  if (m < 60) return m + ' min ago';
  const h = Math.floor(m / 60);
  return h + ' h ' + (m % 60) + ' min ago';
}
const num = (v) => typeof v === 'number' && Number.isFinite(v);

function quakeColor(mag) {
  if (mag >= 5.5) return [1.0, 0.25, 0.25];
  if (mag >= 4.0) return [1.0, 0.55, 0.2];
  return [1.0, 0.82, 0.3];
}
function tempColor(t) {
  if (t < 0) return [0.7, 0.85, 1.0];
  if (t < 10) return [0.35, 0.8, 1.0];
  if (t < 20) return [0.4, 0.9, 0.55];
  if (t < 30) return [1.0, 0.85, 0.3];
  return [1.0, 0.4, 0.25];
}

const placeStyle = (color, summaryLabel) => ({
  pulse: 0,
  color: () => color,
  size: (e) => Math.min(0.085, 0.018 + 0.017 * Math.log10(Math.max(1, e.value))),
  rank: (e) => e.value,
  tip: (e) => {
    const a = (e.detail.articles || [])[0];
    return [
      e.detail.place || e.title,
      Math.round(e.value).toLocaleString() + ' headlines in 24 h' + (a ? ' \u00b7 ' + a.title.slice(0, 70) + (a.title.length > 70 ? '\u2026' : '') : ''),
    ];
  },
  rows: (e) => [
    ['Location', e.detail.place || e.title],
    ['Headlines in the last 24 hours', Math.round(e.value).toLocaleString()],
    ['Updated', ago(e.time)],
  ],
  links: (e) => (e.detail.articles || [])
    .filter((a) => /^https?:\/\//.test(a.url))
    .map((a) => ({ text: a.title, url: a.url, domain: a.domain })),
  source: {
    name: 'Headlines from BBC News, Al Jazeera, The Guardian and France 24 feeds, placed on the map by the city or country named in each one. Placement is approximate and can be wrong.',
    linkLabel: 'News feeds',
    prefix: 'about:none',
  },
  summary: (n) => summaryLabel + ' \u00b7 ' + n + ' places (news feeds)',
});

const SPORT_COLORS = {
  football: [0.25, 1.0, 0.55], basketball: [1.0, 0.62, 0.2], 'american-football': [0.85, 0.6, 0.35],
  baseball: [1.0, 0.4, 0.4], hockey: [0.6, 0.85, 1.0], f1: [1.0, 0.25, 0.25], mma: [0.82, 0.45, 1.0],
  rugby: [0.6, 0.9, 0.4], volleyball: [1.0, 0.85, 0.3],
  'rugby-league': [0.5, 0.85, 0.35], tennis: [0.8, 1.0, 0.3], golf: [0.35, 0.9, 0.55], lacrosse: [0.9, 0.55, 0.8],
  'australian-football': [1.0, 0.7, 0.3], 'field-hockey': [0.5, 0.8, 1.0], 'water-polo': [0.3, 0.7, 1.0],
};
const matchState = (e) => (e.detail && e.detail.state) || 'pre';
const matchStyle = (isFootball) => ({
  pulse: (e) => (matchState(e) === 'in' ? 1 : 0),
  color: (e) => {
    const base = SPORT_COLORS[e.detail.sport] || [0.8, 0.9, 1.0];
    const k = matchState(e) === 'in' ? 1 : matchState(e) === 'pre' ? 0.75 : 0.45;
    return [base[0] * k, base[1] * k, base[2] * k];
  },
  size: (e) => (isFootball ? 1.25 : 1) * (matchState(e) === 'in' ? 0.055 : matchState(e) === 'pre' ? 0.032 : 0.026),
  rank: (e) => (matchState(e) === 'in' ? 2e12 : 1e12) - Math.abs(e.time - Date.now()),
  tip: (e) => [e.title, [e.detail.league, e.detail.status].filter(Boolean).join(' \u00b7 ')],
  rows: (e) => {
    const d = e.detail;
    return [
      ['Match', e.title],
      ['Status', d.status || (matchState(e) === 'in' ? 'Live' : matchState(e) === 'post' ? 'Finished' : 'Scheduled')],
      d.league ? ['Competition', d.league] : null,
      d.sport_label ? ['Sport', d.sport_label] : null,
      Array.isArray(d.competitors) && d.competitors.length ? ['Competitors', d.competitors.map((c) => c.name).join(', ')] : null,
      ['Start', new Date(e.time).toLocaleString()],
      d.venue ? ['Venue', d.venue + (d.city ? ', ' + d.city : '')] : null,
    ];
  },
  links: (e) => (typeof e.url === 'string' && e.url.startsWith('https://www.espn.com/')
    ? [{ text: 'Match page on ESPN', url: e.url, domain: 'espn.com' }] : []),
  source: {
    name: 'Scores from ESPN public scoreboards (an unofficial feed). The map position is the venue city, so it is approximate.',
    linkLabel: 'ESPN',
    prefix: 'about:none',
  },
  summary: (n) => (isFootball ? 'Football \u00b7 ' + n + ' matches' : 'Sports \u00b7 ' + n + ' games') + ' (ESPN)',
});

const marketState = (e) => (e.detail && e.detail.state) || 'closed';
const marketChange = (e) => (e.detail && typeof e.detail.change_pct === 'number' ? e.detail.change_pct : 0);
const marketStyle = {
  pulse: (e) => (marketState(e) === 'open' ? 1 : 0),
  color: (e) => {
    const chg = marketChange(e);
    const k = marketState(e) === 'open' ? 1 : marketState(e) === 'closed' ? 0.4 : 0.7;
    const base = chg >= 0.005 ? [0.18, 0.9, 0.48] : chg <= -0.005 ? [1.0, 0.17, 0.24] : [1.0, 0.37, 0.82];
    return [base[0] * k, base[1] * k, base[2] * k];
  },
  size: (e) => 0.03 + Math.min(Math.abs(marketChange(e)), 3) * 0.008 + (marketState(e) === 'open' ? 0.01 : 0),
  rank: (e) => Math.abs(marketChange(e)) + (marketState(e) === 'open' ? 100 : 0),
  tip: (e) => [e.title, String(e.detail.state || '').toUpperCase() + (e.detail.label ? ' \u00b7 ' + e.detail.label : '')],
  rows: (e) => {
    const d = e.detail;
    return [
      ['Exchange', d.exchange],
      ['City', d.city + ', ' + d.country],
      ['Index', d.index],
      typeof d.level === 'number' ? ['Level', d.level.toLocaleString(undefined, { maximumFractionDigits: 2 }) + (d.currency ? ' ' + d.currency : '')] : null,
      typeof d.change_pct === 'number' ? ['Today', (d.change_pct >= 0 ? '+' : '') + d.change_pct.toFixed(2) + '%'] : null,
      ['Status', String(d.state || '').toUpperCase() + (d.label ? ' \u00b7 ' + d.label : '')],
      ['Local time', d.local_time],
      ['Hours', d.hours],
    ];
  },
  links: () => [],
  source: {
    name: 'Index levels from Yahoo Finance, which can run 10 to 15 minutes behind. Opening hours follow the normal timetable; public holidays are not listed.',
    linkLabel: 'Yahoo Finance',
    prefix: 'about:none',
  },
  summary: (n) => 'Markets \u00b7 ' + n + ' exchanges',
};

export const STYLE = {
  football: matchStyle(true),
  sports: matchStyle(false),
  markets: marketStyle,
  ships: {
    pulse: 0,
    color: () => [0.31, 0.49, 1.0],
    size: () => 0.02,
    rank: () => 0,
    tip: (e) => [e.title, ''],
    rows: () => [],
    source: null,
    summary: (n, l) => 'Ships \u00b7 ' + ((l && l.count) || 0).toLocaleString() + ' vessels (AISstream)',
  },
  news: placeStyle([0.8, 0.92, 1.0], 'News'),
  politics: placeStyle([0.85, 0.5, 1.0], 'Politics'),
  aviation: {
    pulse: 0,
    color: () => [0.4, 0.8, 1.0],
    size: () => 0.02,
    rank: () => 0,
    tip: (e) => [e.title, ''],
    rows: () => [],
    source: null,
    summary: (n, l) => 'Aircraft \u00b7 ' + ((l && l.count) || 0) + ' airborne (OpenSky Network)',
  },
  earthquakes: {
    pulse: 1,
    color: (e) => quakeColor(e.value),
    size: (e) => Math.min(0.16, 0.03 * Math.pow(1.38, Math.max(0, e.value - 2.5))),
    rank: (e) => e.value,
    tip: (e) => [e.title, (num(e.detail.depth_km) ? 'Depth ' + Math.round(e.detail.depth_km) + ' km \u00b7 ' : '') + ago(e.time)],
    rows: (e) => [
      ['Magnitude', e.value.toFixed(1)],
      num(e.detail.depth_km) ? ['Depth', Math.round(e.detail.depth_km) + ' km'] : null,
      ['When', new Date(e.time).toLocaleString() + ' (' + ago(e.time) + ')'],
      e.detail.place ? ['Location', e.detail.place] : null,
      e.detail.status ? ['Review status', e.detail.status] : null,
    ],
    source: { name: 'US Geological Survey', linkLabel: 'Open the USGS event page', prefix: 'https://earthquake.usgs.gov/' },
    summary: (n) => 'Earthquakes M2.5+ \u00b7 past 24 h \u00b7 ' + n,
  },
  weather: {
    pulse: 0,
    color: (e) => tempColor(e.value),
    size: () => 0.018,
    rank: (e) => e.detail.pop || 0,
    tip: (e) => [e.title, (num(e.detail.feels_like) ? 'Feels like ' + Math.round(e.detail.feels_like) + '\u00b0C \u00b7 ' : '') + (num(e.detail.wind_kmh) ? 'wind ' + Math.round(e.detail.wind_kmh) + ' km/h' : ago(e.time))],
    rows: (e) => [
      ['Temperature', Math.round(e.value) + '\u00b0C'],
      num(e.detail.feels_like) ? ['Feels like', Math.round(e.detail.feels_like) + '\u00b0C'] : null,
      e.detail.condition ? ['Conditions', e.detail.condition] : null,
      num(e.detail.humidity) ? ['Humidity', Math.round(e.detail.humidity) + '%'] : null,
      num(e.detail.wind_kmh) ? ['Wind', Math.round(e.detail.wind_kmh) + ' km/h' + (num(e.detail.wind_dir) ? ' from ' + Math.round(e.detail.wind_dir) + '\u00b0' : '')] : null,
      num(e.detail.precip_mm) ? ['Precipitation', e.detail.precip_mm + ' mm'] : null,
      ['Observed', new Date(e.time).toLocaleString() + ' (' + ago(e.time) + ')'],
      e.detail.country ? ['Country', e.detail.country] : null,
    ],
    source: { name: 'Weather data by Open-Meteo.com (CC BY 4.0)', linkLabel: 'Open-Meteo.com', prefix: 'https://open-meteo.com/' },
    summary: (n) => 'Weather \u00b7 ' + n + ' cities (Open-Meteo.com)',
  },
};

const FALLBACK = {
  pulse: 0,
  color: () => [0.7, 0.8, 1.0],
  size: () => 0.03,
  rank: () => 0,
  tip: (e) => [e.title, ago(e.time)],
  rows: (e) => [['When', new Date(e.time).toLocaleString() + ' (' + ago(e.time) + ')']],
  source: null,
  summary: (n) => n + ' events',
};
const styleOf = (layer) => STYLE[layer] || FALLBACK;

function loadEnabled() {
  try {
    const v = JSON.parse(localStorage.getItem(STORE_KEY));
    if (Array.isArray(v)) return new Set(v.filter((x) => typeof x === 'string'));
  } catch (e) { /* storage unavailable */ }
  return new Set(['earthquakes']);
}
function saveEnabled(set) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify([...set])); } catch (e) { /* ignore */ }
}
async function getJSON(url) {
  const r = await fetch(url, { credentials: 'same-origin' });
  if (r.status === 401) { location.href = '/login'; throw new Error('auth'); }
  if (!r.ok) throw new Error(url + ' ' + r.status);
  return r.json();
}

// Which event marker (if any) is under the pointer. Only markers on the visible side count.
export function hitTest(THREE, shown, globe, camera, rect, x, y, pxPerUnit, dpr) {
  globe.updateWorldMatrix(true, false);
  camera.updateMatrixWorld();
  const center = globe.getWorldPosition(new THREE.Vector3());
  const camPos = camera.position;
  const v = new THREE.Vector3();
  const nrm = new THREE.Vector3();
  const toCam = new THREE.Vector3();
  let best = null;
  let bestD = Infinity;
  for (const e of shown) {
    v.set(e.ux, e.uy, e.uz).multiplyScalar(1.006).applyMatrix4(globe.matrixWorld);
    nrm.copy(v).sub(center);
    toCam.copy(camPos).sub(v);
    if (nrm.dot(toCam) <= 0) continue; // on the far side of the globe
    const dist = camPos.distanceTo(v);
    v.project(camera);
    const sx = rect.left + ((v.x + 1) / 2) * rect.width;
    const sy = rect.top + ((1 - v.y) / 2) * rect.height;
    const radius = Math.max(11, (e.size * pxPerUnit) / dist / dpr / 2 + 5);
    const d = Math.hypot(sx - x, sy - y);
    if (d <= radius && d < bestD) { best = e; bestD = d; }
  }
  return best;
}

const SPORTS_OFF_KEY = 'xyron.sportsoff';
function loadSportsOff() {
  try {
    const v = JSON.parse(localStorage.getItem(SPORTS_OFF_KEY));
    if (Array.isArray(v)) return new Set(v.filter((x) => typeof x === 'string'));
  } catch (e) { /* storage unavailable */ }
  return new Set();
}
function saveSportsOff(set) {
  try { localStorage.setItem(SPORTS_OFF_KEY, JSON.stringify([...set])); } catch (e) { /* ignore */ }
}
// is this event switched on? (layers are chips; the sports layer also has one chip per sport)
export function eventVisible(e, enabled, sportsOff) {
  if (!enabled.has(e.layer)) return false;
  return !(e.layer === 'sports' && e.detail && sportsOff.has(e.detail.sport));
}
// the sports present in the data, biggest first, for the sport chips
export function sportList(events) {
  const m = new Map();
  for (const e of events) {
    if (e.layer !== 'sports' || !e.detail || !e.detail.sport) continue;
    const cur = m.get(e.detail.sport) || { id: e.detail.sport, label: e.detail.sport_label || e.detail.sport, n: 0, live: 0 };
    cur.n += 1;
    if (e.detail.state === 'in') cur.live += 1;
    m.set(e.detail.sport, cur);
  }
  return [...m.values()].sort((a, b) => b.live - a.live || b.n - a.n);
}

const SVG_NS = 'http://www.w3.org/2000/svg';
// One colour per layer, matching what it shows. Aviation is left out on purpose and keeps the default look.
export const CHIP_COLORS = {
  earthquakes: '#ff5a36', weather: '#36d6e7', news: '#a5c8ff', politics: '#b07cff', sports: '#ffc83d', football: '#2ee57a', markets: '#ff5fd2', ships: '#4f7cff',
};
// Simple icons on a 24 by 24 grid. Lines, except the plane, which is solid.
const CHIP_ICONS = {
  markets: { d: ['M3 17l6-6 4 4 8-8', 'M15 7h6v6'] },
  ships: { d: ['M3 16h18l-2.5 4h-13z', 'M6 16v-5h12v5', 'M12 11V6', 'M9 6h6'] },
  earthquakes: { d: ['M2 12h4l2.5-6 4 12 3-9 1.5 3H22'] },
  weather: { d: ['M7 18a4 4 0 0 1-.4-7.98A5.5 5.5 0 0 1 17.1 9.2 3.9 3.9 0 0 1 17 18H7z'] },
  news: { d: ['M4 5h12v14H5.5A1.5 1.5 0 0 1 4 17.5V5z', 'M16 9h3.5v8.5a1.5 1.5 0 0 1-1.5 1.5H16', 'M7 9h6M7 12.5h6M7 16h4'] },
  politics: { d: ['M3 9.5 12 4l9 5.5H3z', 'M6 12v6M10 12v6M14 12v6M18 12v6', 'M3.5 20.5h17'] },
  sports: { d: ['M8 4h8v5a4 4 0 0 1-8 0V4z', 'M8 6H5v1a3 3 0 0 0 3 3', 'M16 6h3v1a3 3 0 0 1-3 3', 'M12 13v4', 'M9 20.5h6', 'M10 17h4'] },
  football: { circles: [[12, 12, 9]], d: ['M12 8.3l3.3 2.4-1.3 3.9h-4l-1.3-3.9z', 'M12 8.3V3.2', 'M15.3 10.7l4.6-1.5', 'M14 14.6l2.9 3.9', 'M10 14.6l-2.9 3.9', 'M8.7 10.7 4.1 9.2'] },
  aviation: { fill: true, d: ['M12 2c.9 0 1.5.8 1.5 1.7V9l8 5v2.2l-8-2.4V19l2 1.5V22L12 21l-3.5 1v-1.5l2-1.5v-5.2l-8 2.4V14l8-5V3.7C10.5 2.8 11.1 2 12 2z'] },
};
export function chipIcon(id) {
  const spec = CHIP_ICONS[id];
  if (!spec) return '';
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'ico');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('fill', spec.fill ? 'currentColor' : 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', spec.fill ? '0' : '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  for (const [cx, cy, r] of spec.circles || []) {
    const c = document.createElementNS(SVG_NS, 'circle');
    c.setAttribute('cx', cx); c.setAttribute('cy', cy); c.setAttribute('r', r);
    svg.appendChild(c);
  }
  for (const d of spec.d) {
    const p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', d);
    svg.appendChild(p);
  }
  return svg;
}
function hexRgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
}
export function rgbHex(rgb) {
  return '#' + rgb.map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, '0')).join('');
}
// give a chip its colour; no colour means the chip keeps the default look
export function paintChip(b, hex) {
  if (!hex) return;
  b.classList.add('coded');
  b.style.setProperty('--c', hex);
  b.style.setProperty('--cb', hexRgba(hex, 0.45));
  b.style.setProperty('--cbg', hexRgba(hex, 0.16));
  b.style.setProperty('--cg', hexRgba(hex, 0.42));
}

export function init(ctx) {
  const { THREE, globe, camera, renderer, canvas, nearestCountry, countries, deselect, flyTo, openPanel } = ctx;
  // the football hub asks the globe to fly to a stadium
  window.addEventListener('xyron-flyto', (ev) => {
    const d = ev.detail || {};
    if (typeof d.lat === 'number' && typeof d.lon === 'number') flyTo(d.lat, d.lon, 2.2);
  });
  const chipsEl = document.getElementById('layers');
  const statusEl = document.getElementById('status');
  const listEl = document.getElementById('pevents');
  const evTitleEl = document.getElementById('pevtitle');
  const tipEl = document.getElementById('tip');
  const enabled = loadEnabled();
  const sportsOff = loadSportsOff();
  const sportRow = document.createElement('div');
  sportRow.id = 'sportchips';
  sportRow.hidden = true;
  chipsEl.after(sportRow);
  const bufSize = new THREE.Vector2();
  let layers = [];
  let events = [];
  let shown = [];
  let points = null;
  let selected = -1;
  let pxPerUnit = 600;

  const material = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uPx: { value: 600 } },
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });

  function rebuildMarkers() {
    if (points) { globe.remove(points); points.geometry.dispose(); points = null; }
    shown = events.filter((e) => eventVisible(e, enabled, sportsOff));
    if (!shown.length) return;
    const pos = new Float32Array(shown.length * 3);
    const size = new Float32Array(shown.length);
    const phase = new Float32Array(shown.length);
    const pulse = new Float32Array(shown.length);
    const color = new Float32Array(shown.length * 3);
    shown.forEach((e, i) => {
      pos[3 * i] = 1.006 * e.ux;
      pos[3 * i + 1] = 1.006 * e.uy;
      pos[3 * i + 2] = 1.006 * e.uz;
      size[i] = e.size;
      phase[i] = (i * 0.618034) % 1;
      pulse[i] = e.pulse;
      color[3 * i] = e.color[0]; color[3 * i + 1] = e.color[1]; color[3 * i + 2] = e.color[2];
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
    g.setAttribute('aPhase', new THREE.BufferAttribute(phase, 1));
    g.setAttribute('aPulse', new THREE.BufferAttribute(pulse, 1));
    g.setAttribute('aColor', new THREE.BufferAttribute(color, 3));
    points = new THREE.Points(g, material);
    points.frustumCulled = false;
    globe.add(points);
  }

  function broadcast() {
    window.dispatchEvent(new CustomEvent('xyron-layers', { detail: [...enabled] }));
  }

  function renderChips() {
    chipsEl.replaceChildren();
    for (const l of layers) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'chip' + (l.live && enabled.has(l.id) ? ' on' : '') + (l.id === 'football' ? ' football' : '');
      b.disabled = !l.live;
      paintChip(b, CHIP_COLORS[l.id]);
      b.append(chipIcon(l.id), l.label);
      const s = document.createElement('small');
      s.textContent = l.live ? String(l.count) : 'soon';
      b.append(s);
      if (l.live) {
        b.addEventListener('click', () => {
          if (enabled.has(l.id)) enabled.delete(l.id); else enabled.add(l.id);
          saveEnabled(enabled);
          broadcast();
          renderChips();
          renderSportChips();
          rebuildMarkers();
          renderList();
          renderStatus();
          hideTip();
        });
      }
      chipsEl.appendChild(b);
    }
  }

  function renderSportChips() {
    sportRow.replaceChildren();
    const list = sportList(events);
    sportRow.hidden = !(enabled.has('sports') && list.length);
    for (const s of list) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'chip small' + (sportsOff.has(s.id) ? '' : ' on');
      paintChip(b, rgbHex(SPORT_COLORS[s.id] || [0.8, 0.9, 1.0]));
      b.append(s.label);
      const c = document.createElement('small');
      c.textContent = (s.live ? s.live + ' live \u00b7 ' : '') + s.n;
      b.append(c);
      b.addEventListener('click', () => {
        if (sportsOff.has(s.id)) sportsOff.delete(s.id); else sportsOff.add(s.id);
        saveSportsOff(sportsOff);
        renderSportChips();
        rebuildMarkers();
        renderList();
        hideTip();
      });
      sportRow.appendChild(b);
    }
  }

  function renderStatus() {
    const on = layers.filter((l) => l.live && enabled.has(l.id));
    if (!on.length) { statusEl.textContent = layers.length ? 'No live layers switched on' : ''; return; }
    const parts = on.map((l) => styleOf(l.id).summary(events.filter((e) => e.layer === l.id).length, l));
    const stamps = on.map((l) => l.updated).filter(Boolean).sort();
    let t = parts.join('  |  ');
    if (stamps.length) t += ' \u00b7 updated ' + new Date(stamps[stamps.length - 1]).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    statusEl.textContent = t;
  }

  // ----- hover card -----
  function showTip(e, x, y) {
    const [title, line] = styleOf(e.layer).tip(e);
    tipEl.replaceChildren();
    const a = document.createElement('div');
    a.className = 'tip-title';
    a.textContent = title;
    const b = document.createElement('div');
    b.textContent = line;
    const c = document.createElement('div');
    c.className = 'tip-hint';
    c.textContent = 'Click for details';
    tipEl.append(a, b, c);
    tipEl.hidden = false;
    const w = tipEl.offsetWidth;
    const h = tipEl.offsetHeight;
    tipEl.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x + 16)) + 'px';
    tipEl.style.top = Math.max(8, Math.min(window.innerHeight - h - 8, y + 16)) + 'px';
  }
  function hideTip() { tipEl.hidden = true; }

  // ----- panel: events near the selected country, or one event in detail -----
  function renderList() {
    listEl.replaceChildren();
    evTitleEl.hidden = selected < 0;
    if (selected < 0) return;
    evTitleEl.textContent = 'Live events near ' + countries[selected].name;
    const here = [];
    for (const l of layers) {
      if (!l.live || !enabled.has(l.id)) continue;
      const st = styleOf(l.id);
      here.push(...events
        .filter((e) => e.layer === l.id && e.country === selected && eventVisible(e, enabled, sportsOff))
        .sort((a, b) => st.rank(b) - st.rank(a))
        .slice(0, 8));
    }
    if (!here.length) {
      const p = document.createElement('p');
      p.className = 'muted';
      p.textContent = 'No live events near here right now.';
      listEl.appendChild(p);
      return;
    }
    for (const e of here) {
      const row = document.createElement('div');
      row.className = 'ev';
      row.textContent = e.title;
      const when = document.createElement('div');
      when.className = 'when';
      when.textContent = ago(e.time);
      row.appendChild(when);
      row.addEventListener('click', () => showEvent(e));
      listEl.appendChild(row);
    }
  }

  function dlRow(dl, label, value) {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.textContent = value;
    dl.append(dt, dd);
  }

  function showEvent(e) {
    const st = styleOf(e.layer);
    hideTip();
    deselect();
    document.getElementById('pname').textContent = e.title;
    const dl = document.getElementById('pinfo');
    dl.replaceChildren();
    for (const r of st.rows(e)) if (r) dlRow(dl, r[0], r[1]);
    if (e.country >= 0) dlRow(dl, 'Nearest country', countries[e.country].name);
    dlRow(dl, 'Coordinates', e.lat.toFixed(2) + '\u00b0, ' + e.lon.toFixed(2) + '\u00b0');
    listEl.replaceChildren();
    const links = st.links ? st.links(e) : [];
    evTitleEl.hidden = !(st.source || links.length);
    for (const l of links) {
      const row = document.createElement('div');
      row.className = 'ev';
      const a = document.createElement('a');
      a.href = l.url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = l.text;
      row.appendChild(a);
      if (l.domain) {
        const d = document.createElement('div');
        d.className = 'when';
        d.textContent = l.domain;
        row.appendChild(d);
      }
      listEl.appendChild(row);
    }
    if (st.source) {
      evTitleEl.textContent = links.length ? 'Headlines and source' : 'Source';
      const src = document.createElement('div');
      src.className = 'ev';
      src.append(st.source.name);
      if (typeof e.url === 'string' && e.url.startsWith(st.source.prefix)) {
        const a = document.createElement('a');
        a.href = e.url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.textContent = st.source.linkLabel;
        src.appendChild(document.createElement('br'));
        src.appendChild(a);
      }
      listEl.appendChild(src);
    }
    openPanel();
    flyTo(e.lat, e.lon, 2.4);
  }

  async function refresh(only) {
    try {
      const subset = Array.isArray(only) ? only : null;
      layers = await getJSON('/api/layers');
      const live = layers.filter((l) => l.live && (!subset || subset.includes(l.id))).map((l) => l.id).join(',');
      const raw = live ? await getJSON('/api/events?hours=24&layers=' + live) : [];
      const fresh = raw.map((r) => {
        const la = r.lat * DEG;
        const lo = r.lon * DEG;
        const st = styleOf(r.layer);
        const e = {
          id: r.id, layer: r.layer, title: r.title, lat: r.lat, lon: r.lon,
          value: r.severity || 0, time: Date.parse(r.occurred_at), url: r.url, detail: r.detail || {},
          ux: Math.cos(la) * Math.sin(lo), uy: Math.sin(la), uz: Math.cos(la) * Math.cos(lo),
          country: nearestCountry(r.lat, r.lon), pulse: 0,
        };
        e.pulse = typeof st.pulse === 'function' ? st.pulse(e) : st.pulse;
        e.size = st.size(e);
        e.color = st.color(e);
        return e;
      });
      events = subset ? events.filter((e) => !subset.includes(e.layer)).concat(fresh) : fresh;
      renderChips();
      renderSportChips();
      rebuildMarkers();
      renderList();
      renderStatus();
      broadcast();
    } catch (err) {
      if (err.message !== 'auth') statusEl.textContent = 'Live data unavailable right now';
    }
  }

  function hit(x, y) {
    if (!shown.length) return null;
    return hitTest(THREE, shown, globe, camera, canvas.getBoundingClientRect(), x, y, pxPerUnit, renderer.getPixelRatio());
  }

  refresh();
  setInterval(() => refresh(), 300000);
  setInterval(() => {
    const ids = ['football', 'sports'].filter((id) => enabled.has(id));
    const gameOn = events.some((e) => ids.includes(e.layer) && e.detail && e.detail.state === 'in');
    if (gameOn && !document.hidden) refresh(ids);
  }, 20000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

  return {
    onSelect(ci) { selected = ci; renderList(); },
    onHover(x, y) {
      if (x < 0) { hideTip(); return false; }
      const e = hit(x, y);
      if (!e) { hideTip(); return false; }
      showTip(e, x, y);
      return true;
    },
    onClick(x, y) {
      const e = hit(x, y);
      if (!e) return false;
      showEvent(e);
      return true;
    },
    onFrame(now) {
      material.uniforms.uTime.value = now / 1000;
      renderer.getDrawingBufferSize(bufSize);
      pxPerUnit = bufSize.y / (2 * Math.tan((camera.fov * DEG) / 2));
      material.uniforms.uPx.value = pxPerUnit;
    },
  };
}
