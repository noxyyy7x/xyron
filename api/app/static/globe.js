import * as THREE from '/static/vendor/three.module.min.js';

const $ = (id) => document.getElementById(id);
const canvas = $('globe');
const hint = $('hint');
const DEG = Math.PI / 180;
const BASE = [0.26, 0.5, 0.92];
const HOVER = [0.55, 0.86, 1.0];
const SELECT = [1.0, 0.78, 0.28];
const MAX_TILT = 1.3;
const ZMIN = 1.5;
const ZMAX = 6;
const narrow = window.matchMedia('(max-width: 700px)');

let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
} catch (e) {
  hint.textContent = 'This browser cannot show the 3D globe (WebGL is unavailable).';
  throw e;
}
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 50);
let zoom = 3.4;
camera.position.set(0, 0, zoom);

const stage = new THREE.Group();
const globe = new THREE.Group();
stage.add(globe);
scene.add(stage);

const ball = new THREE.Mesh(
  new THREE.SphereGeometry(0.985, 64, 48),
  new THREE.MeshBasicMaterial({ color: 0x070d18 }),
);
globe.add(ball);

stage.add(new THREE.Mesh(
  new THREE.SphereGeometry(1.14, 64, 48),
  new THREE.ShaderMaterial({
    side: THREE.BackSide,
    blending: THREE.AdditiveBlending,
    transparent: true,
    depthWrite: false,
    vertexShader: 'varying vec3 vN; void main(){ vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: 'varying vec3 vN; void main(){ float i = pow(max(0.7 - dot(vN, vec3(0.0, 0.0, 1.0)), 0.0), 3.0); gl_FragColor = vec4(0.25, 0.55, 1.0, 1.0) * i; }',
  }),
));

function dotTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  g.beginPath();
  g.arc(32, 32, 30, 0, Math.PI * 2);
  g.fillStyle = '#fff';
  g.fill();
  return new THREE.CanvasTexture(c);
}

// ---------- load data ----------
let data;
try {
  const me = await fetch('/auth/me', { credentials: 'same-origin' });
  if (me.status === 401) { location.href = '/login'; await new Promise(() => {}); }
  const user = await me.json();
  $('who').textContent = user.email + ' \u00b7 ' + user.role;
  if (user.role === 'owner' || user.role === 'admin') $('adminlink').hidden = false;
  const res = await fetch('/static/globe/dots.json');
  data = await res.json();
} catch (e) {
  hint.textContent = 'Could not load the globe data.';
  throw e;
}

const n = data.c.length;
const pos = new Float32Array(n * 3);
const col = new Float32Array(n * 3);
const byCountry = data.countries.map(() => []);
for (let i = 0; i < n; i++) {
  const la = data.lat[i] * DEG;
  const lo = data.lon[i] * DEG;
  pos[3 * i] = Math.cos(la) * Math.sin(lo);
  pos[3 * i + 1] = Math.sin(la);
  pos[3 * i + 2] = Math.cos(la) * Math.cos(lo);
  col[3 * i] = BASE[0]; col[3 * i + 1] = BASE[1]; col[3 * i + 2] = BASE[2];
  byCountry[data.c[i]].push(i);
}
const geo = new THREE.BufferGeometry();
geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
const colorAttr = new THREE.BufferAttribute(col, 3);
geo.setAttribute('color', colorAttr);
globe.add(new THREE.Points(geo, new THREE.PointsMaterial({
  size: 0.0165, vertexColors: true, sizeAttenuation: true, map: dotTexture(), alphaTest: 0.5,
})));

// ---------- selection and hover ----------
let layerHooks = {};
let hoverC = -1;
let selC = -1;

function paint(ci) {
  if (ci < 0) return;
  const rgb = ci === selC ? SELECT : ci === hoverC ? HOVER : BASE;
  for (const i of byCountry[ci]) {
    col[3 * i] = rgb[0]; col[3 * i + 1] = rgb[1]; col[3 * i + 2] = rgb[2];
  }
  colorAttr.needsUpdate = true;
}

const ray = new THREE.Raycaster();
const ndc = new THREE.Vector2();
const tmp = new THREE.Vector3();

function pick(clientX, clientY) {
  const r = canvas.getBoundingClientRect();
  ndc.set(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObject(ball)[0];
  if (!hit) return -1;
  tmp.copy(hit.point);
  globe.worldToLocal(tmp);
  tmp.normalize();
  let best = -1;
  let bestDot = 0.9986; // within about 3 degrees of a land dot
  for (let i = 0; i < n; i++) {
    const d = pos[3 * i] * tmp.x + pos[3 * i + 1] * tmp.y + pos[3 * i + 2] * tmp.z;
    if (d > bestDot) { bestDot = d; best = i; }
  }
  return best < 0 ? -1 : data.c[best];
}

let pendingHover = null;
function setHover(ci) {
  if (ci === hoverC) return;
  const prev = hoverC;
  hoverC = ci;
  paint(prev);
  paint(ci);
  canvas.style.cursor = ci >= 0 ? 'pointer' : 'grab';
}

// ---------- detail panel ----------
const panel = $('panel');
function row(dl, label, value) {
  const dt = document.createElement('dt');
  dt.textContent = label;
  const dd = document.createElement('dd');
  dd.textContent = value;
  dl.append(dt, dd);
}
function showPanel(ci) {
  const c = data.countries[ci];
  $('pname').textContent = c.name;
  const dl = $('pinfo');
  dl.replaceChildren();
  row(dl, 'Country code', c.iso);
  if (c.continent) row(dl, 'Continent', c.continent);
  if (c.region) row(dl, 'Region', c.region);
  if (c.pop) row(dl, 'Population (est.)', c.pop.toLocaleString());
  row(dl, 'Centre point', c.lat.toFixed(2) + '\u00b0, ' + c.lon.toFixed(2) + '\u00b0');
  panel.hidden = false;
  document.body.classList.add('panel-open');
}
function hidePanel() {
  panel.hidden = true;
  document.body.classList.remove('panel-open');
}

let flying = false;
let tY = 0;
let tX = 0;
let tZoom = zoom;
function wrap(a) { return ((((a + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) - Math.PI; }

function select(ci) {
  const prev = selC;
  selC = ci;
  paint(prev);
  paint(ci);
  if (ci < 0) { hidePanel(); if (layerHooks.onSelect) layerHooks.onSelect(-1); return; }
  showPanel(ci);
  if (layerHooks.onSelect) layerHooks.onSelect(ci);
  const c = data.countries[ci];
  tY = -c.lon * DEG;
  tX = Math.max(-MAX_TILT, Math.min(MAX_TILT, c.lat * DEG));
  tZoom = Math.min(zoom, 2.6);
  flying = true;
}
$('close').addEventListener('click', () => select(-1));
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') select(-1); });

// ---------- controls: drag, pinch, wheel, tap ----------
const pointers = new Map();
let moved = 0;
let lastPinch = 0;
let lastInput = performance.now();

function setZoom(z) {
  zoom = Math.max(ZMIN, Math.min(ZMAX, z));
  camera.position.z = zoom;
}
function pinchDist() {
  const [a, b] = [...pointers.values()];
  return Math.hypot(a.x - b.x, a.y - b.y);
}
function touched() {
  lastInput = performance.now();
  flying = false;
  hint.classList.add('gone');
}

canvas.addEventListener('pointerdown', (e) => {
  canvas.setPointerCapture(e.pointerId);
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pointers.size === 1) moved = 0;
  if (pointers.size === 2) lastPinch = pinchDist();
  touched();
});
canvas.addEventListener('pointermove', (e) => {
  const p = pointers.get(e.pointerId);
  if (!p) {
    if (e.pointerType === 'mouse') pendingHover = [e.clientX, e.clientY];
    return;
  }
  const dx = e.clientX - p.x;
  const dy = e.clientY - p.y;
  p.x = e.clientX;
  p.y = e.clientY;
  touched();
  if (pointers.size === 1) {
    moved += Math.abs(dx) + Math.abs(dy);
    const k = 0.005 * (zoom / 3.4);
    globe.rotation.y += dx * k;
    globe.rotation.x = Math.max(-MAX_TILT, Math.min(MAX_TILT, globe.rotation.x + dy * k));
  } else if (pointers.size === 2) {
    const d = pinchDist();
    if (lastPinch > 0 && d > 0) setZoom(zoom * (lastPinch / d));
    lastPinch = d;
    moved += 10;
  }
});
function release(e) {
  if (!pointers.delete(e.pointerId)) return;
  if (pointers.size < 2) lastPinch = 0;
  if (pointers.size === 0 && e.type === 'pointerup' && moved < 8) select(pick(e.clientX, e.clientY));
}
canvas.addEventListener('pointerup', release);
canvas.addEventListener('pointercancel', release);
canvas.addEventListener('pointerleave', () => { if (pointers.size === 0) setHover(-1); });
canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  setZoom(zoom * Math.exp(e.deltaY * 0.0012));
  touched();
}, { passive: false });

// ---------- sizing ----------
function resize() {
  const r = canvas.parentElement.getBoundingClientRect();
  const w = Math.max(1, Math.floor(r.width));
  const h = Math.max(1, Math.floor(r.height));
  renderer.setSize(w, h, false);
  const aspect = w / h;
  camera.aspect = aspect;
  // on tall (phone) screens widen the vertical field so the whole globe still fits
  camera.fov = aspect < 1 ? Math.min(100, (2 * Math.atan(Math.tan(20 * DEG) / aspect)) / DEG) : 40;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(canvas.parentElement);
resize();

$('logout').addEventListener('click', async () => {
  await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' });
  location.href = '/login';
});

// ---------- live layers (layers.js) ----------
function nearestCountry(lat, lon) {
  const la = lat * DEG;
  const lo = lon * DEG;
  const x = Math.cos(la) * Math.sin(lo);
  const y = Math.sin(la);
  const z = Math.cos(la) * Math.cos(lo);
  let best = -1;
  let bestDot = 0.99; // within about 8 degrees of land
  for (let i = 0; i < n; i++) {
    const d = pos[3 * i] * x + pos[3 * i + 1] * y + pos[3 * i + 2] * z;
    if (d > bestDot) { bestDot = d; best = i; }
  }
  return best < 0 ? -1 : data.c[best];
}
try {
  const mod = await import('/static/layers.js');
  layerHooks = mod.init({ THREE, globe, camera, renderer, nearestCountry }) || {};
} catch (e) {
  console.error('Live layers failed to load', e);
}

// ---------- render loop ----------
let last = performance.now();
function frame(now) {
  const dt = Math.min(now - last, 50);
  last = now;

  if (pendingHover && pointers.size === 0) {
    setHover(pick(pendingHover[0], pendingHover[1]));
  }
  pendingHover = null;
  if (layerHooks.onFrame) layerHooks.onFrame(now, dt);

  if (flying) {
    const dy = wrap(tY - globe.rotation.y);
    const dx = tX - globe.rotation.x;
    globe.rotation.y += dy * 0.08;
    globe.rotation.x += dx * 0.08;
    setZoom(zoom + (tZoom - zoom) * 0.06);
    if (Math.abs(dy) < 0.002 && Math.abs(dx) < 0.002) flying = false;
  } else if (selC < 0 && pointers.size === 0 && now - lastInput > 2500) {
    globe.rotation.y += dt * 0.00012;
  }

  // on phones the detail panel is a bottom sheet, so lift the globe above it
  const lift = narrow.matches && document.body.classList.contains('panel-open') ? 0.13 * zoom : 0;
  stage.position.y += (lift - stage.position.y) * 0.1;

  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
