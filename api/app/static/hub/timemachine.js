// Time machine: replay the last day or week on the globe: earthquakes, hazards, football, headlines, ship tracks and market moves.
// It draws its own points and lines on the globe, and hides the live layers while it is open. Everything from the server is written with textContent.
(function () {
  'use strict';
  var bar = document.getElementById('bar');
  if (!bar) return;
  var NS = 'http://www.w3.org/2000/svg', DEG = Math.PI / 180, LIFT = 1.008, TRAIL_LIFT = 1.004, TRAIL_SECONDS = 4 * 3600, TRAIL_POINTS = 8, SHIP_GRACE = 3 * 3600;
  var SPEEDS = [[600, 'Slow \u00b7 10 min per second'], [3600, 'Normal \u00b7 1 hour per second'], [10800, 'Fast \u00b7 3 hours per second'], [43200, 'Very fast \u00b7 12 hours per second']];
  var KIND = { q: ['Earthquake', '#ff7a3d'], h: ['Hazard', '#b8e62e'], k: ['Kick-off', '#2ee57a'], g: ['Goal', '#7dffb0'], f: ['Full time', '#2ee57a'], n: ['Headline', '#e6f0ff'] };
  var GROUP = { q: 'q', h: 'h', k: 'f', g: 'f', f: 'f', n: 'n' };
  var SHIP_RGB = { cargo: '#4f9eff', tanker: '#ff8a3d', passenger: '#d27aff', fishing: '#52e07a', service: '#ffd140', pleasure: '#ffffff', highspeed: '#52e0ff', military: '#ff4040', other: '#a9c1d6' };
  var S = { open: false, hours: 24, cache: {}, t: 0, from: 0, to: 0, playing: false, speed: 3600, on: { q: true, h: true, f: true, n: true, s: true, m: true }, suspended: [], gl: null, mom: null, ship: null, mkt: null, range: null, raf: 0, lastFrame: 0, feedAt: 0, tipFor: null, errors: {} };

  function h(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; }
  function add(parent) { for (var i = 1; i < arguments.length; i++) if (arguments[i]) parent.appendChild(arguments[i]); return parent; }
  function svg(tag, attrs) { var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); return e; }
  function icon() {
    var s = svg('svg', { viewBox: '0 0 24 24', 'class': 'ico', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
    s.appendChild(svg('circle', { cx: '12', cy: '12', r: '8.5' })); s.appendChild(svg('path', { d: 'M12 7v5l3.2 2' })); s.appendChild(svg('path', { d: 'M3 12 1.5 10.5M3 12l1.5-1.5' })); return s;
  }
  function getJSON(path) { return fetch(path, { credentials: 'same-origin' }).then(function (r) { if (r.status === 401) { location.href = '/login'; throw new Error('auth'); } if (!r.ok) throw new Error(path + ' ' + r.status); return r.json(); }); }
  function when(sec, long) { return new Date(sec * 1000).toLocaleString([], long ? { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit' }); }
  function ago(sec) { var d = Math.max(0, Math.round(sec)); if (d < 90) return 'now'; var m = Math.round(d / 60); if (m < 90) return m + ' min ago'; var hr = Math.floor(m / 60); return hr < 48 ? hr + ' h ' + (m % 60) + ' m ago' : Math.floor(hr / 24) + ' d ' + (hr % 24) + ' h ago'; }
  function vec(lat, lon, r) { var la = lat * DEG, lo = lon * DEG; return [r * Math.cos(la) * Math.sin(lo), r * Math.sin(la), r * Math.cos(la) * Math.cos(lo)]; }
  function rgb(hex) { var n = parseInt(hex.slice(1), 16); return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255]; }
  function bsearch(arr, x) { var lo = 0, hi = arr.length; while (lo < hi) { var mid = (lo + hi) >> 1; if (arr[mid] <= x) lo = mid + 1; else hi = mid; } return lo - 1; } // last index with arr[i] <= x
  function clamp(x, a, b) { return x < a ? a : x > b ? b : x; }

  // ---------- how bright each thing is at a given moment ----------
  function momentLook(k, age, mag) {
    if (age < 0) return [0, 0];
    if (k === 'q') return [age < 10800 ? 1 - 0.5 * age / 10800 : Math.max(0, 0.5 - 0.5 * (age - 10800) / 32400), 4 + clamp(mag, 2, 8) * 1.8];
    if (k === 'h') return [0.85, 9];
    if (k === 'n') return [Math.max(0, 1 - age / 21600), 6];
    if (k === 'k') return [age < 7200 ? 1 : 0, 9];
    if (k === 'g') return [Math.max(0, 1 - age / 1800), 15];
    if (k === 'f') return [Math.max(0, 1 - age / 5400), 10];
    return [0, 0];
  }
  function momentColor(it) { if (it[1] === 'q') return it[4] >= 5.5 ? [1, 0.25, 0.25] : it[4] >= 4 ? [1, 0.55, 0.2] : [1, 0.82, 0.3]; return rgb(KIND[it[1]][1]); }
  function moveColor(c) { var m = clamp(Math.abs(c) / 300, 0, 1); return c >= 0 ? [0.2 + 0.1 * (1 - m), 0.7 + 0.3 * m, 0.4] : [0.8 + 0.2 * m, 0.25, 0.3]; }
  function shipPosition(v, t) {
    var tt = v.tt, n = tt.length;
    if (t < tt[0] - SHIP_GRACE || t > tt[n - 1] + SHIP_GRACE) return null;
    if (t <= tt[0]) return { lat: v.la[0], lon: v.lo[0], i: -1 };
    if (t >= tt[n - 1]) return { lat: v.la[n - 1], lon: v.lo[n - 1], i: n - 1 };
    var i = bsearch(tt, t), f = (t - tt[i]) / (tt[i + 1] - tt[i]), dl = v.lo[i + 1] - v.lo[i];
    if (dl > 180) dl -= 360; else if (dl < -180) dl += 360;
    return { lat: v.la[i] + (v.la[i + 1] - v.la[i]) * f, lon: v.lo[i] + dl * f, i: i };
  }

  // ---------- the header button, the bar and the panel ----------
  var btn = h('button', 'timebtn'); btn.id = 'timebtn'; btn.type = 'button'; btn.title = 'Time machine'; add(btn, icon(), h('span', 'lbl', 'TIME'));
  var after = document.getElementById('secbtn') || document.getElementById('alertbtn') || document.getElementById('searchbtn') || document.getElementById('mktbtn') || document.getElementById('hubbtn') || bar.querySelector('.brand');
  if (after && after.nextSibling) bar.insertBefore(btn, after.nextSibling); else bar.appendChild(btn);
  btn.addEventListener('click', function () { if (S.open) close(); else open(); });
  ['hubbtn', 'mktbtn', 'searchbtn', 'alertbtn', 'secbtn'].forEach(function (id) { var b = document.getElementById(id); if (b) b.addEventListener('click', function () { if (S.open) close(); }); });

  var root = h('div'); root.id = 'timebar'; root.hidden = true; root.setAttribute('role', 'region'); root.setAttribute('aria-label', 'Time machine');
  var r1 = h('div', 'tm-row'), titleEl = h('div', 'tm-title', 'TIME MACHINE'), win = h('div', 'tm-win'), b24 = h('button', 'tm-btn on', '24 H'), b7 = h('button', 'tm-btn', '7 D');
  b24.type = b7.type = 'button'; b24.dataset.h = '24'; b7.dataset.h = '168'; add(win, b24, b7);
  var clock = h('div', 'tm-clock'), clockMain = h('div', 'tm-main', '\u2013'), clockSub = h('div', 'tm-sub', ''); add(clock, clockMain, clockSub);
  var live = h('button', 'tm-btn live', 'BACK TO LIVE'); live.type = 'button'; var x = h('button', 'tm-x', '\u00d7'); x.type = 'button'; x.setAttribute('aria-label', 'Close the time machine');
  add(r1, titleEl, win, clock, live, x);
  var r2 = h('div', 'tm-row'), start = h('button', 'tm-btn', '\u23EE'), play = h('button', 'tm-btn play', '\u25B6'), speed = h('select', 'tm-speed'), slider = h('input', 'tm-slider');
  start.type = play.type = 'button'; start.title = 'Back to the start'; play.title = 'Play'; play.setAttribute('aria-label', 'Play');
  SPEEDS.forEach(function (s) { var o = h('option', null, s[1]); o.value = s[0]; speed.appendChild(o); });
  slider.type = 'range'; slider.min = 0; slider.max = 1000; slider.value = 1000; slider.setAttribute('aria-label', 'Time');
  add(r2, start, play, speed, slider);
  var r3 = h('div', 'tm-row tm-chips'), chipEls = {};
  [['q', 'QUAKES'], ['h', 'HAZARDS'], ['f', 'FOOTBALL'], ['n', 'HEADLINES'], ['s', 'SHIPS'], ['m', 'MARKETS']].forEach(function (c) {
    var b = h('button', 'tm-chip on'); b.type = 'button'; b.dataset.k = c[0]; b.setAttribute('aria-pressed', 'true'); b.appendChild(h('span', null, c[1])); b.appendChild(h('small', null, ''));
    b.addEventListener('click', function () { S.on[c[0]] = !S.on[c[0]]; b.classList.toggle('on', S.on[c[0]]); b.setAttribute('aria-pressed', S.on[c[0]] ? 'true' : 'false'); render(true); });
    chipEls[c[0]] = b; r3.appendChild(b);
  });
  var note = h('div', 'tm-note'); add(root, r1, r2, r3, note); document.body.appendChild(root);
  var panel = h('div'); panel.id = 'timepanel'; panel.hidden = true; var feedHead = h('h4', null, 'AROUND THIS TIME'), feedEl = h('div', 'tm-feed'), mktHead = h('h4', null, 'MARKETS (24 H MOVE)'), mktEl = h('div', 'tm-mkt'); add(panel, feedHead, feedEl, mktHead, mktEl); document.body.appendChild(panel);
  var tip = h('div'); tip.id = 'timetip'; tip.hidden = true; document.body.appendChild(tip);

  // ---------- opening and closing ----------
  function ready() { return window.xyronGlobe && window.xyronGlobe.THREE; }
  function chipsNow() { return Array.prototype.slice.call(document.querySelectorAll('#layers .chip')); }
  function suspendLive() { S.suspended = []; chipsNow().forEach(function (b, i) { if (b.classList.contains('on')) S.suspended.push(i); }); S.suspended.forEach(function (i) { var b = chipsNow()[i]; if (b) b.click(); }); }
  function resumeLive() { S.suspended.forEach(function (i) { var b = chipsNow()[i]; if (b && !b.classList.contains('on')) b.click(); }); S.suspended = []; }
  window.addEventListener('pagehide', function () { if (S.open) resumeLive(); });

  function open() {
    if (!ready()) { note.textContent = 'The globe is not ready yet. Try again in a moment.'; root.hidden = false; return; }
    ['hub', 'mkt', 'alerts', 'security'].forEach(function (id) { var el = document.getElementById(id); if (el && !el.hidden) { var c = el.querySelector('.hub-close, .mk-close, .a-close, .sx-close'); if (c) c.click(); } });
    S.open = true; S.gl = S.gl || buildScene(); root.hidden = false; panel.hidden = false; document.body.classList.add('time-open'); btn.classList.add('on');
    suspendLive(); S.errors = {}; load(S.hours);
  }
  function close() {
    S.open = false; S.playing = false; cancelAnimationFrame(S.raf); root.hidden = true; panel.hidden = true; tip.hidden = true; document.body.classList.remove('time-open'); btn.classList.remove('on');
    if (S.gl) { destroyScene(S.gl); S.gl = null; } resumeLive(); drawPlay();
  }
  x.addEventListener('click', close); live.addEventListener('click', close);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && S.open) close(); });

  // ---------- the data ----------
  function load(hours) {
    S.hours = hours; b24.classList.toggle('on', hours === 24); b7.classList.toggle('on', hours === 168); S.playing = false; cancelAnimationFrame(S.raf); drawPlay();
    S.speed = hours === 24 ? 3600 : 10800; speed.value = S.speed;
    var c = S.cache[hours];
    if (c) { use(c); return; }
    c = S.cache[hours] = { hours: hours, mom: null, ship: null, mkt: null, range: null, errors: {} };
    note.textContent = 'Loading the past\u2026'; var token = c;
    var jobs = [['mom', '/api/time/moments?hours=' + hours], ['ship', '/api/time/ships?hours=' + hours], ['mkt', '/api/time/markets?hours=' + hours], ['range', '/api/time/range']];
    jobs.forEach(function (j) {
      getJSON(j[1]).then(function (d) { token[j[0]] = d; }).catch(function () { token.errors[j[0]] = true; }).then(function () { if (S.open && S.hours === hours) use(token); });
    });
  }
  function prepare(c) {
    // the three answers arrive one after another, so each part is prepared the first time it is there
    var p = c.prep || (c.prep = { items: null, ships: null, mkt: null });
    if (c.mom && !p.items) { p.items = c.mom.items; p.times = p.items.map(function (i) { return i[0]; }); p.counts = { q: 0, h: 0, f: 0, n: 0 }; p.hz = []; p.items.forEach(function (i, k) { p.counts[GROUP[i[1]]]++; if (i[1] === 'h') p.hz.push(k); }); }
    if (c.ship && !p.ships) p.ships = c.ship.vessels.map(function (v) { var o = { m: v.m, n: v.n, k: v.k, tt: v.p.map(function (q) { return c.ship.from + q[0] * 60; }), la: v.p.map(function (q) { return q[1] / 1000; }), lo: v.p.map(function (q) { return q[2] / 1000; }) }; o.xyz = new Float32Array(v.p.length * 3); for (var j = 0; j < v.p.length; j++) { var w = vec(o.la[j], o.lo[j], TRAIL_LIFT); o.xyz[j * 3] = w[0]; o.xyz[j * 3 + 1] = w[1]; o.xyz[j * 3 + 2] = w[2]; } return o; });
    if (c.mkt && !p.mkt) p.mkt = c.mkt;
    return p;
  }
  function use(c) {
    // the bar needs something to scrub through: take the window from whichever answer arrived
    var any = c.mom || c.ship || c.mkt, first = !S.mom && !S.ship && !S.mkt;
    S.mom = c.mom ? prepare(c) : null; S.ship = c.ship ? prepare(c) : null; S.mkt = c.mkt ? prepare(c) : null; S.range = c.range; S.errors = c.errors;
    var p = prepare(c);
    if (c.mom) { S.from = c.mom.from; S.to = c.mom.to; } else if (c.ship) { S.from = c.ship.from; S.to = c.ship.to; } else if (c.mkt) { S.from = c.mkt.from; S.to = c.mkt.from + (c.hours * 3600); }
    else { var nowS = Math.floor(Date.now() / 1000); S.from = nowS - c.hours * 3600; S.to = nowS; }
    if (!any || first || S.t < S.from || S.t > S.to || !S.t) S.t = S.to;
    buildShips(p); drawChips(p); drawNote(); slider.value = Math.round((S.t - S.from) / Math.max(1, S.to - S.from) * 1000); render(true);
  }
  function drawChips(p) {
    var counts = { q: p.counts ? p.counts.q : null, h: p.counts ? p.counts.h : null, f: p.counts ? p.counts.f : null, n: p.counts ? p.counts.n : null, s: p.ships ? p.ships.length : null, m: p.mkt ? p.mkt.exchanges.length : null };
    Object.keys(chipEls).forEach(function (k) { chipEls[k].querySelector('small').textContent = counts[k] === null ? '\u2013' : String(counts[k]); });
  }
  function drawNote() {
    var parts = [], r = S.range && S.range.earliest;
    if (S.errors.mom) parts.push('Events could not be loaded.'); if (S.errors.ship) parts.push('Ship tracks could not be loaded.'); if (S.errors.mkt) parts.push('Market history could not be loaded.');
    if (r) {
      [['hazards', 'Hazards'], ['football', 'Football moments'], ['ships', 'Ship tracks'], ['markets', 'Market history']].forEach(function (s) {
        var t = r[s[0]] ? Date.parse(r[s[0]]) / 1000 : null;
        if (t === null) parts.push(s[1] + ': nothing recorded yet.'); else if (t > S.from + 3600) parts.push(s[1] + ' are recorded from ' + when(t, true) + '.');
      });
    }
    note.textContent = parts.join(' ');
  }

  // ---------- drawing on the globe ----------
  var POINT_V = 'attribute vec3 aColor; attribute float aAlpha; attribute float aSize; uniform float uPx; varying vec3 vColor; varying float vAlpha;\n' +
    'void main() { vec3 wp = (modelMatrix * vec4(position, 1.0)).xyz; float facing = dot(normalize(wp), normalize(cameraPosition - wp)); vColor = aColor; vAlpha = aAlpha * smoothstep(0.02, 0.18, facing);\n' +
    '  gl_Position = projectionMatrix * viewMatrix * vec4(wp, 1.0); gl_PointSize = aSize * uPx; }';
  var POINT_F = 'varying vec3 vColor; varying float vAlpha; void main() { float d = length(gl_PointCoord - 0.5) * 2.0; if (d > 1.0) discard; float a = (smoothstep(1.0, 0.55, d) * 0.85 + pow(1.0 - d, 2.0) * 0.35) * vAlpha; gl_FragColor = vec4(vColor, a); }';
  function makePoints(THREE, n) {
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3)); g.setAttribute('aColor', new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    g.setAttribute('aAlpha', new THREE.BufferAttribute(new Float32Array(n), 1)); g.setAttribute('aSize', new THREE.BufferAttribute(new Float32Array(n), 1));
    var m = new THREE.ShaderMaterial({ vertexShader: POINT_V, fragmentShader: POINT_F, uniforms: { uPx: { value: 1 } }, transparent: true, depthWrite: false });
    var p = new THREE.Points(g, m); p.frustumCulled = false; p.renderOrder = 6; return p;
  }
  function buildScene() {
    var G = window.xyronGlobe, THREE = G.THREE, px = (G.renderer && G.renderer.getPixelRatio ? G.renderer.getPixelRatio() : 1) || 1;
    var gl = { G: G, THREE: THREE, mom: null, ships: null, ex: null, trail: null, trailCap: 0 };
    gl.px = px; return gl;
  }
  function destroyScene(gl) {
    ['mom', 'ships', 'ex', 'trail'].forEach(function (k) { var o = gl[k]; if (o) { gl.G.globe.remove(o); if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); gl[k] = null; } });
  }
  function ensure(key, make) { var gl = S.gl; if (!gl[key]) { gl[key] = make(); gl.G.globe.add(gl[key]); } return gl[key]; }
  function buildShips(p) {
    if (!S.gl) return; var gl = S.gl, THREE = gl.THREE;
    ['mom', 'ships', 'trail', 'ex'].forEach(function (k) { var o = gl[k]; if (o) { gl.G.globe.remove(o); o.geometry.dispose(); o.material.dispose(); gl[k] = null; } });
    if (p.items && p.items.length) { var m = makePoints(THREE, p.items.length); m.material.uniforms.uPx.value = gl.px; p.items.forEach(function (it, i) { var v = vec(it[2], it[3], LIFT), c = momentColor(it); m.geometry.attributes.position.setXYZ(i, v[0], v[1], v[2]); m.geometry.attributes.aColor.setXYZ(i, c[0], c[1], c[2]); }); m.geometry.attributes.position.needsUpdate = true; m.geometry.attributes.aColor.needsUpdate = true; gl.mom = m; gl.G.globe.add(m); }
    if (p.ships && p.ships.length) {
      var sp = makePoints(THREE, p.ships.length); sp.material.uniforms.uPx.value = gl.px; p.ships.forEach(function (v, i) { var c = rgb(SHIP_RGB[v.k] || SHIP_RGB.other); sp.geometry.attributes.aColor.setXYZ(i, c[0], c[1], c[2]); sp.geometry.attributes.aSize.setX(i, 4); }); gl.ships = sp; gl.G.globe.add(sp);
      var cap = p.ships.length * TRAIL_POINTS * 2, g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(cap * 3), 3)); g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(cap * 3), 3));
      var tl = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.55, depthWrite: false })); tl.frustumCulled = false; tl.renderOrder = 5; gl.trail = tl; gl.trailCap = cap; gl.G.globe.add(tl);
    }
    if (p.mkt && p.mkt.exchanges.length) { var ex = makePoints(THREE, p.mkt.exchanges.length); ex.material.uniforms.uPx.value = gl.px; p.mkt.exchanges.forEach(function (e, i) { var v = vec(e.lat, e.lon, LIFT); ex.geometry.attributes.position.setXYZ(i, v[0], v[1], v[2]); }); ex.geometry.attributes.position.needsUpdate = true; gl.ex = ex; gl.G.globe.add(ex); }
  }
  function marketIndex(p) { return p.mkt ? clamp(Math.round((S.t - p.mkt.from) / p.mkt.step), 0, p.mkt.n - 1) : 0; }
  function exchangeMove(p, e) { var si = p.mkt.symbols.findIndex(function (s) { return s.s === e.index; }); return si < 0 ? null : p.mkt.chg[si][marketIndex(p)]; }
  function render(force) {
    if (!S.gl || !S.open) return; var p = (S.mom || S.ship || S.mkt) ? (S.mom || S.ship || S.mkt) : null, gl = S.gl, t = S.t;
    clockMain.textContent = when(t, true); clockSub.textContent = S.to - t < 120 ? 'now' : ago(S.to - t);
    if (!p) return;
    if (gl.mom && S.mom) { var a = gl.mom.geometry.attributes, items = S.mom.items, times = S.mom.times, n = items.length, hi = bsearch(times, t), i;
      for (i = 0; i < n; i++) a.aAlpha.array[i] = 0;
      for (i = Math.max(0, hi); i >= 0; i--) { var it = items[i], age = t - it[0]; if (age > 43200) break; if (it[1] === 'h') continue; var look = S.on[GROUP[it[1]]] ? momentLook(it[1], age, it[4]) : [0, 0]; a.aAlpha.array[i] = look[0]; a.aSize.array[i] = look[1]; }
      for (i = 0; i < S.mom.hz.length; i++) { var hi2 = S.mom.hz[i]; a.aAlpha.array[hi2] = S.on.h && times[hi2] <= t ? 0.85 : 0; a.aSize.array[hi2] = 9; } // hazards stay open until the end of the replay
      a.aAlpha.needsUpdate = true; a.aSize.needsUpdate = true; }
    if (gl.ships && S.ship) { var sh = S.ship.ships, pa = gl.ships.geometry.attributes, tl = gl.trail.geometry.attributes, P = tl.position.array, C = tl.color.array, col = pa.aColor.array, seg = 0, cap = gl.trailCap;
      for (var k = 0; k < sh.length; k++) {
        var v = sh[k], pos = S.on.s ? shipPosition(v, t) : null;
        if (!pos) { pa.aAlpha.array[k] = 0; continue; }
        var w = vec(pos.lat, pos.lon, LIFT); pa.position.setXYZ(k, w[0], w[1], w[2]); pa.aAlpha.array[k] = 0.95;
        var r = col[k * 3], g2 = col[k * 3 + 1], b2 = col[k * 3 + 2], px = w[0], py = w[1], pz = w[2], lo = Math.max(0, bsearch(v.tt, t - TRAIL_SECONDS)), used = 0;
        for (var j = pos.i; j >= lo && used < TRAIL_POINTS - 1 && seg + 2 <= cap; j--) {
          if (v.tt[j] < t - TRAIL_SECONDS) break;
          var o = seg * 3, qx = v.xyz[j * 3], qy = v.xyz[j * 3 + 1], qz = v.xyz[j * 3 + 2];
          P[o] = px; P[o + 1] = py; P[o + 2] = pz; P[o + 3] = qx; P[o + 4] = qy; P[o + 5] = qz;
          C[o] = r; C[o + 1] = g2; C[o + 2] = b2; C[o + 3] = r * 0.35; C[o + 4] = g2 * 0.35; C[o + 5] = b2 * 0.35;
          seg += 2; px = qx; py = qy; pz = qz; used++;
        }
      }
      gl.trail.geometry.setDrawRange(0, seg); pa.position.needsUpdate = true; pa.aAlpha.needsUpdate = true; pa.aSize.needsUpdate = true; tl.position.needsUpdate = true; tl.color.needsUpdate = true; }
    if (gl.ex && S.mkt) { var ea = gl.ex.geometry.attributes; S.mkt.mkt.exchanges.forEach(function (e, k) { var c = S.on.m ? exchangeMove(S.mkt, e) : null; if (c === null || c === undefined) { ea.aAlpha.array[k] = 0; return; } var col = moveColor(c); ea.aColor.setXYZ(k, col[0], col[1], col[2]); ea.aSize.setX(k, 8 + clamp(Math.abs(c) / 60, 0, 10)); ea.aAlpha.array[k] = 0.95; }); ea.aAlpha.needsUpdate = true; ea.aColor.needsUpdate = true; ea.aSize.needsUpdate = true; }
    var nowMs = Date.now(); if (force || nowMs - S.feedAt > 300) { S.feedAt = nowMs; drawFeed(); drawMarkets(); }
  }

  // ---------- the side panel ----------
  function drawFeed() {
    feedEl.replaceChildren(); var p = S.mom; if (!p) { feedEl.appendChild(h('p', 'tm-dim', S.errors.mom ? 'Events are unavailable.' : 'Loading\u2026')); return; }
    var t = S.t, hi = bsearch(p.times, t), shown = 0;
    for (var i = hi; i >= 0 && shown < 8; i--) {
      var it = p.items[i]; if (t - it[0] > 5400) break; if (!S.on[GROUP[it[1]]]) continue;
      var row = h('button', 'tm-item'); row.type = 'button'; row.style.setProperty('--c', KIND[it[1]][1]);
      add(row, h('i'), h('span', 'tm-when', when(it[0])), h('span', 'tm-what', KIND[it[1]][0] + (it[1] === 'q' ? ' M' + it[4].toFixed(1) : '') + ' \u00b7 ' + it[5]));
      (function (item) { row.addEventListener('click', function () { if (S.gl && S.gl.G.flyTo) S.gl.G.flyTo(item[2], item[3], 2.2); showTip(item); }); })(it);
      feedEl.appendChild(row); shown++;
    }
    if (!shown) feedEl.appendChild(h('p', 'tm-dim', 'Nothing in the hour and a half before this moment.'));
  }
  function drawMarkets() {
    mktEl.replaceChildren(); var p = S.mkt; if (!p || !S.on.m) { mktHead.hidden = true; return; } mktHead.hidden = false;
    var i = marketIndex(p), rows = [];
    p.mkt.symbols.forEach(function (s, k) { var v = p.mkt.chg[k][i]; if (v !== null && v !== undefined && s.kind !== 'currency') rows.push([s.name, v]); });
    rows.sort(function (a, b) { return b[1] - a[1]; });
    var pick = rows.filter(function (r) { return r[1] > 0; }).slice(0, 3).concat(rows.filter(function (r) { return r[1] < 0; }).slice(-3).reverse()); // three biggest risers, three biggest fallers
    pick.forEach(function (r) { var row = h('div', 'tm-mrow ' + (r[1] >= 0 ? 'up' : 'down')); add(row, h('span', null, r[0]), h('b', null, (r[1] >= 0 ? '+' : '') + (r[1] / 100).toFixed(2) + '%')); mktEl.appendChild(row); });
    if (!pick.length) mktEl.appendChild(h('p', 'tm-dim', 'No prices at this time.'));
  }
  function showTip(it) {
    S.tipFor = it; tip.replaceChildren(); var kind = it[1];
    add(tip, h('div', 'tm-tt', KIND[kind][0] + (kind === 'q' ? ' M' + it[4].toFixed(1) : '') + (it[7] === '~' ? ' (time approximate)' : '')), h('div', 'tm-tm', when(it[0], true)), h('div', 'tm-tx', it[5]));
    if (kind === 'n') { add(tip, h('div', 'tm-ts', it[6])); if (it[7] && it[7].indexOf('https://') === 0) { var a = h('a', 'tm-link', 'OPEN ARTICLE'); a.href = it[7]; a.target = '_blank'; a.rel = 'noopener noreferrer'; tip.appendChild(a); } }
    else if (kind === 'h') add(tip, h('div', 'tm-ts', it[7] || it[6])); else if (it[6]) add(tip, h('div', 'tm-ts', it[6]));
    var c = h('button', 'tm-tclose', '\u00d7'); c.type = 'button'; c.addEventListener('click', function () { tip.hidden = true; }); tip.appendChild(c); tip.hidden = false;
  }
  function showShipTip(v, pos) {
    tip.replaceChildren(); add(tip, h('div', 'tm-tt', v.n || 'Ship ' + v.m), h('div', 'tm-tm', 'MMSI ' + v.m + ' \u00b7 ' + v.k), h('div', 'tm-tx', pos.lat.toFixed(2) + ', ' + pos.lon.toFixed(2)));
    var c = h('button', 'tm-tclose', '\u00d7'); c.type = 'button'; c.addEventListener('click', function () { tip.hidden = true; }); tip.appendChild(c); tip.hidden = false;
  }

  // ---------- tapping a point on the globe ----------
  function pick(clientX, clientY) {
    var gl = S.gl; if (!gl || !S.open) return; var G = gl.G, rect = G.canvas.getBoundingClientRect(), THREE = gl.THREE, best = null, bd = 14;
    var v = new THREE.Vector3(), cam = G.camera.position;
    function test(arr, i, kind, ref) {
      v.set(arr.position.getX(i), arr.position.getY(i), arr.position.getZ(i)); G.globe.localToWorld(v);
      if (v.clone().normalize().dot(cam.clone().sub(v).normalize()) < 0.1) return;
      v.project(G.camera); var sx = (v.x + 1) / 2 * rect.width + rect.left, sy = (1 - v.y) / 2 * rect.height + rect.top, d = Math.hypot(sx - clientX, sy - clientY);
      if (d < bd) { bd = d; best = { kind: kind, ref: ref }; }
    }
    if (gl.mom && S.mom) { var a = gl.mom.geometry.attributes; for (var i = 0; i < S.mom.items.length; i++) if (a.aAlpha.array[i] > 0.25) test(a, i, 'm', S.mom.items[i]); }
    if (gl.ships && S.ship) { var sa = gl.ships.geometry.attributes; S.ship.ships.forEach(function (s, k) { if (sa.aAlpha.array[k] > 0.25) test(sa, k, 's', s); }); }
    if (best) { if (best.kind === 'm') showTip(best.ref); else showShipTip(best.ref, shipPosition(best.ref, S.t)); } else tip.hidden = true;
  }
  var down = null;
  document.addEventListener('pointerdown', function (e) { if (S.open && S.gl && e.target === S.gl.G.canvas) down = [e.clientX, e.clientY]; });
  document.addEventListener('pointerup', function (e) { if (down && S.open && S.gl && e.target === S.gl.G.canvas && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 5) pick(e.clientX, e.clientY); down = null; });

  // ---------- controls ----------
  function drawPlay() { play.textContent = S.playing ? '\u23F8' : '\u25B6'; play.title = S.playing ? 'Pause' : 'Play'; play.setAttribute('aria-label', S.playing ? 'Pause' : 'Play'); }
  function setTime(t) { S.t = clamp(t, S.from, S.to); slider.value = Math.round((S.t - S.from) / Math.max(1, S.to - S.from) * 1000); render(false); }
  function tick(now) {
    if (!S.playing || !S.open) return;
    var dt = Math.min(0.1, (now - S.lastFrame) / 1000); S.lastFrame = now; S.t = Math.min(S.to, S.t + dt * S.speed);
    slider.value = Math.round((S.t - S.from) / Math.max(1, S.to - S.from) * 1000); render(false);
    if (S.t >= S.to) { S.playing = false; drawPlay(); return; }
    S.raf = requestAnimationFrame(tick);
  }
  play.addEventListener('click', function () {
    if (S.playing) { S.playing = false; cancelAnimationFrame(S.raf); drawPlay(); return; }
    if (S.t >= S.to - 60) setTime(S.from);
    S.playing = true; S.lastFrame = (window.performance && performance.now) ? performance.now() : Date.now(); drawPlay(); S.raf = requestAnimationFrame(tick);
  });
  start.addEventListener('click', function () { setTime(S.from); });
  speed.addEventListener('change', function () { S.speed = parseInt(speed.value, 10) || 3600; });
  slider.addEventListener('input', function () { setTime(S.from + (S.to - S.from) * (parseInt(slider.value, 10) / 1000)); });
  [b24, b7].forEach(function (b) { b.addEventListener('click', function () { var hrs = parseInt(b.dataset.h, 10); if (hrs !== S.hours && S.open) load(hrs); }); });

  window.xyronTimeMachine = { state: S, momentLook: momentLook, shipPosition: shipPosition, moveColor: moveColor };
})();
