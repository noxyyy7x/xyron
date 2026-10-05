// Live data layers: toggles, glowing event markers and the per-country event list.
const DEG = Math.PI / 180;
const STORE_KEY = 'xyron.layers';

const VERTEX = `
attribute float aSize;
attribute float aPhase;
attribute vec3 aColor;
uniform float uTime;
uniform float uPx;
varying float vPhase;
varying vec3 vColor;
void main() {
  vPhase = aPhase;
  vColor = aColor;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  float pulse = 1.0 + 0.22 * sin(uTime * 2.0 + aPhase * 6.2831);
  gl_PointSize = max(7.0, aSize * pulse * uPx / -mv.z);
  gl_Position = projectionMatrix * mv;
}`;

const FRAGMENT = `
varying float vPhase;
varying vec3 vColor;
uniform float uTime;
void main() {
  float d = length(gl_PointCoord - 0.5) * 2.0;
  if (d > 1.0) discard;
  float core = smoothstep(0.3, 0.0, d);
  float glow = pow(1.0 - d, 2.0) * 0.55;
  float t = fract(uTime * 0.5 + vPhase);
  float ring = smoothstep(0.1, 0.0, abs(d - t)) * (1.0 - t);
  float a = clamp(core + glow + ring * 0.8, 0.0, 1.0);
  gl_FragColor = vec4(vColor, a);
}`;

function colorFor(mag) {
  if (mag >= 5.5) return [1.0, 0.25, 0.25];
  if (mag >= 4.0) return [1.0, 0.55, 0.2];
  return [1.0, 0.82, 0.3];
}
function sizeFor(mag) {
  return Math.min(0.16, 0.03 * Math.pow(1.38, Math.max(0, mag - 2.5)));
}
function ago(ms) {
  const m = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (m < 1) return 'just now';
  if (m < 60) return m + ' min ago';
  const h = Math.floor(m / 60);
  return h + ' h ' + (m % 60) + ' min ago';
}
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

export function init(ctx) {
  const { THREE, globe, camera, renderer, nearestCountry } = ctx;
  const chipsEl = document.getElementById('layers');
  const statusEl = document.getElementById('status');
  const listEl = document.getElementById('pevents');
  const enabled = loadEnabled();
  const bufSize = new THREE.Vector2();
  let layers = [];
  let events = [];
  let points = null;
  let selected = -1;

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
    const shown = events.filter((e) => enabled.has(e.layer));
    if (!shown.length) return;
    const pos = new Float32Array(shown.length * 3);
    const size = new Float32Array(shown.length);
    const phase = new Float32Array(shown.length);
    const color = new Float32Array(shown.length * 3);
    shown.forEach((e, i) => {
      const la = e.lat * DEG;
      const lo = e.lon * DEG;
      pos[3 * i] = 1.006 * Math.cos(la) * Math.sin(lo);
      pos[3 * i + 1] = 1.006 * Math.sin(la);
      pos[3 * i + 2] = 1.006 * Math.cos(la) * Math.cos(lo);
      size[i] = sizeFor(e.mag);
      phase[i] = (i * 0.618034) % 1;
      const c = colorFor(e.mag);
      color[3 * i] = c[0]; color[3 * i + 1] = c[1]; color[3 * i + 2] = c[2];
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
    g.setAttribute('aPhase', new THREE.BufferAttribute(phase, 1));
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
        });
      }
      chipsEl.appendChild(b);
    }
  }

  function renderStatus() {
    const q = layers.find((l) => l.id === 'earthquakes');
    if (!q) { statusEl.textContent = ''; return; }
    if (!enabled.has('earthquakes')) { statusEl.textContent = 'No live layers switched on'; return; }
    let t = 'Earthquakes M2.5+ \u00b7 past 24 h \u00b7 ' + events.filter((e) => e.layer === 'earthquakes').length + ' events';
    if (q.updated) t += ' \u00b7 updated ' + new Date(q.updated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    statusEl.textContent = t;
  }

  function renderList() {
    listEl.replaceChildren();
    if (selected < 0) return;
    const here = events
      .filter((e) => enabled.has(e.layer) && e.country === selected)
      .sort((a, b) => b.mag - a.mag)
      .slice(0, 15);
    if (!here.length) {
      const p = document.createElement('p');
      p.className = 'muted';
      p.textContent = 'No live events near here in the last 24 hours.';
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
      if (typeof e.url === 'string' && e.url.startsWith('https://earthquake.usgs.gov/')) {
        const a = document.createElement('a');
        a.href = e.url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.textContent = 'USGS details';
        row.appendChild(a);
      }
      listEl.appendChild(row);
    }
  }

  async function refresh() {
    try {
      layers = await getJSON('/api/layers');
      const live = layers.filter((l) => l.live).map((l) => l.id).join(',');
      const raw = live ? await getJSON('/api/events?hours=24&layers=' + live) : [];
      events = raw.map((e) => ({
        id: e.id, layer: e.layer, title: e.title, lat: e.lat, lon: e.lon,
        mag: e.severity || 0, time: Date.parse(e.occurred_at), url: e.url,
        country: nearestCountry(e.lat, e.lon),
      }));
      renderChips();
      rebuildMarkers();
      renderList();
      renderStatus();
    } catch (err) {
      if (err.message !== 'auth') statusEl.textContent = 'Live data unavailable right now';
    }
  }

  refresh();
  setInterval(refresh, 300000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

  return {
    onSelect(ci) { selected = ci; renderList(); },
    onFrame(now) {
      material.uniforms.uTime.value = now / 1000;
      renderer.getDrawingBufferSize(bufSize);
      material.uniforms.uPx.value = bufSize.y / (2 * Math.tan((camera.fov * DEG) / 2));
    },
  };
}
