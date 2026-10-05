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

export const STYLE = {
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

export function init(ctx) {
  const { THREE, globe, camera, renderer, canvas, nearestCountry, countries, deselect, flyTo, openPanel } = ctx;
  const chipsEl = document.getElementById('layers');
  const statusEl = document.getElementById('status');
  const listEl = document.getElementById('pevents');
  const evTitleEl = document.getElementById('pevtitle');
  const tipEl = document.getElementById('tip');
  const enabled = loadEnabled();
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
    shown = events.filter((e) => enabled.has(e.layer));
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

  function renderChips() {
    chipsEl.replaceChildren();
    for (const l of layers) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'chip' + (l.live && enabled.has(l.id) ? ' on' : '');
      b.disabled = !l.live;
      b.append(l.label);
      const s = document.createElement('small');
      s.textContent = l.live ? String(l.count) : 'soon';
      b.append(s);
      if (l.live) {
        b.addEventListener('click', () => {
          if (enabled.has(l.id)) enabled.delete(l.id); else enabled.add(l.id);
          saveEnabled(enabled);
          renderChips();
          rebuildMarkers();
          renderList();
          renderStatus();
          hideTip();
        });
      }
      chipsEl.appendChild(b);
    }
  }

  function renderStatus() {
    const on = layers.filter((l) => l.live && enabled.has(l.id));
    if (!on.length) { statusEl.textContent = layers.length ? 'No live layers switched on' : ''; return; }
    const parts = on.map((l) => styleOf(l.id).summary(events.filter((e) => e.layer === l.id).length));
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
        .filter((e) => e.layer === l.id && e.country === selected)
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
    evTitleEl.hidden = !st.source;
    if (st.source) {
      evTitleEl.textContent = 'Source';
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

  async function refresh() {
    try {
      layers = await getJSON('/api/layers');
      const live = layers.filter((l) => l.live).map((l) => l.id).join(',');
      const raw = live ? await getJSON('/api/events?hours=24&layers=' + live) : [];
      events = raw.map((r) => {
        const la = r.lat * DEG;
        const lo = r.lon * DEG;
        const st = styleOf(r.layer);
        const e = {
          id: r.id, layer: r.layer, title: r.title, lat: r.lat, lon: r.lon,
          value: r.severity || 0, time: Date.parse(r.occurred_at), url: r.url, detail: r.detail || {},
          ux: Math.cos(la) * Math.sin(lo), uy: Math.sin(la), uz: Math.cos(la) * Math.cos(lo),
          country: nearestCountry(r.lat, r.lon), pulse: st.pulse,
        };
        e.size = st.size(e);
        e.color = st.color(e);
        return e;
      });
      renderChips();
      rebuildMarkers();
      renderList();
      renderStatus();
    } catch (err) {
      if (err.message !== 'auth') statusEl.textContent = 'Live data unavailable right now';
    }
  }

  function hit(x, y) {
    if (!shown.length) return null;
    return hitTest(THREE, shown, globe, camera, canvas.getBoundingClientRect(), x, y, pxPerUnit, renderer.getPixelRatio());
  }

  refresh();
  setInterval(refresh, 300000);
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
