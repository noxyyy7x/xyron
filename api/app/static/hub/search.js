// Search: press / or Ctrl+K, type a country, city, ship, flight, team or ticker, and the globe goes there.
// Everything from the server is written with textContent, never as HTML.
(function () {
  'use strict';
  var bar = document.getElementById('bar');
  if (!bar) return; // only the globe page has a header
  var RECENT_KEY = 'xyron.recent';
  var COLORS = { places: '#5cc8ff', ships: '#4f7cff', flights: '#f0883e', football: '#2ee57a', markets: '#ff5fd2', events: '#b8e62e' };
  var EXAMPLES = ['London', 'EK203', 'Take-Two', 'Arsenal', 'Gold', 'Taiwan', 'EVER GIVEN'];
  var S = { open: false, q: '', groups: [], flat: [], active: -1, seq: 0, loading: false, error: false, timer: null, recent: [] };
  try { var saved = JSON.parse(localStorage.getItem(RECENT_KEY)); if (Array.isArray(saved)) S.recent = saved.filter(function (x) { return typeof x === 'string'; }).slice(0, 6); } catch (e) { /* storage unavailable */ }

  function h(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; }
  function add(parent) { for (var i = 1; i < arguments.length; i++) if (arguments[i]) parent.appendChild(arguments[i]); return parent; }
  var NS = 'http://www.w3.org/2000/svg';
  function glass() {
    var s = document.createElementNS(NS, 'svg');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'ico'); s.setAttribute('aria-hidden', 'true'); s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round');
    var c = document.createElementNS(NS, 'circle'); c.setAttribute('cx', 11); c.setAttribute('cy', 11); c.setAttribute('r', 6.5); s.appendChild(c);
    var p = document.createElementNS(NS, 'path'); p.setAttribute('d', 'M16 16l5 5'); s.appendChild(p);
    return s;
  }

  // ----- the header button -----
  var btn = h('button', 'searchbtn'); btn.id = 'searchbtn'; btn.type = 'button'; btn.title = 'Search (press / or Ctrl+K)';
  add(btn, glass(), h('span', 'lbl', 'SEARCH'), h('kbd', null, '/'));
  var after = document.getElementById('mktbtn') || document.getElementById('hubbtn') || bar.querySelector('.brand');
  if (after && after.nextSibling) bar.insertBefore(btn, after.nextSibling); else bar.appendChild(btn);
  btn.addEventListener('click', function () { if (S.open) close(); else open(); });

  // ----- the box -----
  var root = h('div'); root.id = 'search'; root.hidden = true; root.setAttribute('role', 'dialog'); root.setAttribute('aria-modal', 'true'); root.setAttribute('aria-label', 'Search');
  var back = h('div', 's-back'), box = h('div', 's-box'), field = h('div', 's-field');
  var input = h('input'); input.id = 's-input'; input.type = 'text'; input.placeholder = 'Search a place, ship, flight, team or ticker\u2026'; input.autocomplete = 'off'; input.spellcheck = false; input.maxLength = 60;
  input.setAttribute('role', 'combobox'); input.setAttribute('aria-expanded', 'false'); input.setAttribute('aria-controls', 's-results'); input.setAttribute('aria-label', 'Search');
  add(field, glass(), input, h('kbd', null, 'ESC'));
  var results = h('div', 's-results'); results.id = 's-results'; results.setAttribute('role', 'listbox');
  var foot = h('div', 's-foot', '\u2191 \u2193 to move   \u00b7   Enter to go   \u00b7   Esc to close');
  add(box, field, results, foot); add(root, back, box);
  document.body.appendChild(root);
  back.addEventListener('click', function () { close(); });

  function open() {
    S.open = true; root.hidden = false; document.body.classList.add('search-open');
    S.q = ''; S.groups = []; S.active = -1; S.error = false; input.value = ''; // a fresh box every time, with your recent searches
    render(); input.focus();
  }
  function close() { S.open = false; root.hidden = true; document.body.classList.remove('search-open'); clearTimeout(S.timer); S.seq++; S.loading = false; }

  // ----- doing the search -----
  function remember(q) {
    q = q.trim(); if (!q) return;
    S.recent = [q].concat(S.recent.filter(function (r) { return r.toLowerCase() !== q.toLowerCase(); })).slice(0, 6);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(S.recent)); } catch (e) { /* ignore */ }
  }
  function run(q) {
    var mine = ++S.seq;
    S.loading = true; S.error = false; render();
    fetch('/api/search?q=' + encodeURIComponent(q), { credentials: 'same-origin' }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; throw new Error('auth'); }
      if (!r.ok) throw new Error('search ' + r.status);
      return r.json();
    }).then(function (j) {
      if (mine !== S.seq) return; // a newer search has started
      S.groups = Array.isArray(j.groups) ? j.groups : []; S.loading = false; S.active = S.groups.length ? 0 : -1; render();
    }).catch(function () {
      if (mine !== S.seq) return;
      S.loading = false; S.error = true; S.groups = []; render();
    });
  }
  input.addEventListener('input', function () {
    S.q = input.value; clearTimeout(S.timer);
    if (S.q.trim().length < 2) { S.seq++; S.groups = []; S.loading = false; S.error = false; S.active = -1; render(); return; }
    S.timer = setTimeout(function () { run(S.q.trim()); }, 200);
  });

  // ----- drawing the list -----
  function render() {
    results.replaceChildren();
    S.flat = [];
    var typed = S.q.trim().length >= 2;
    if (!typed) {
      if (S.recent.length) {
        results.appendChild(heading('RECENT', '#8b949e', S.recent.length));
        S.recent.forEach(function (r) {
          var row = h('div', 's-item s-recent'); row.setAttribute('role', 'option');
          add(row, h('div', 's-title', r)); row.addEventListener('click', function () { input.value = S.q = r; run(r); input.focus(); });
          results.appendChild(row);
        });
      }
      var ex = h('div', 's-examples'); ex.appendChild(h('span', 's-hint', 'TRY'));
      EXAMPLES.forEach(function (t) { var c = h('button', 's-chip', t); c.type = 'button'; c.addEventListener('click', function () { input.value = S.q = t; run(t); input.focus(); }); ex.appendChild(c); });
      results.appendChild(ex);
      results.appendChild(h('p', 's-note', 'Countries and cities, ships by name, MMSI or IMO, flights by callsign, airline or number (EK203), football teams, and stocks, crypto and commodities.'));
      input.setAttribute('aria-expanded', 'false'); return;
    }
    if (S.loading && !S.groups.length) { results.appendChild(h('p', 's-note', 'Searching\u2026')); return; }
    if (S.error) { results.appendChild(h('p', 's-note err', 'Search is unavailable right now.')); return; }
    if (!S.groups.length) { results.appendChild(h('p', 's-note', 'Nothing found for \u201c' + S.q.trim() + '\u201d. Try a country, a city, a ship name, a flight like EK203, a team or a ticker.')); return; }
    S.groups.forEach(function (g) {
      results.appendChild(heading(g.label, COLORS[g.id] || '#8b949e', g.items.length));
      g.items.forEach(function (it) {
        var idx = S.flat.length, row = h('div', 's-item' + (idx === S.active ? ' active' : ''));
        row.id = 's-opt-' + idx; row.setAttribute('role', 'option'); row.setAttribute('aria-selected', idx === S.active ? 'true' : 'false'); row.style.setProperty('--gc', COLORS[g.id] || '#2f81ff');
        add(row, h('div', 's-title', it.title), h('div', 's-sub', it.subtitle));
        row.addEventListener('mousemove', function () { if (S.active !== idx) { S.active = idx; mark(); } });
        row.addEventListener('click', function () { choose(idx); });
        S.flat.push(it); results.appendChild(row);
      });
    });
    input.setAttribute('aria-expanded', 'true'); input.setAttribute('aria-activedescendant', S.active >= 0 ? 's-opt-' + S.active : '');
  }
  function heading(label, color, count) {
    var el = h('div', 's-group'); el.style.setProperty('--gc', color);
    add(el, h('i'), h('span', null, String(label).toUpperCase()), h('small', null, String(count)));
    return el;
  }
  function mark() {
    var rows = results.querySelectorAll('.s-item');
    for (var i = 0; i < rows.length; i++) { var on = i === S.active; rows[i].classList.toggle('active', on); rows[i].setAttribute('aria-selected', on ? 'true' : 'false'); if (on && rows[i].scrollIntoView) rows[i].scrollIntoView({ block: 'nearest' }); }
    input.setAttribute('aria-activedescendant', S.active >= 0 ? 's-opt-' + S.active : '');
  }

  // ----- going to a result -----
  function fire(name, detail) { window.dispatchEvent(new CustomEvent(name, { detail: detail })); }
  function choose(i) {
    var it = S.flat[i]; if (!it) return;
    remember(S.q); close();
    var a = it.action || {};
    if (a.type === 'fly') fire('xyron-flyto', { lat: a.lat, lon: a.lon, zoom: a.zoom });
    else if (a.type === 'ship') { fire('xyron-enable-layer', 'ships'); fire('xyron-flyto', { lat: a.lat, lon: a.lon }); fire('xyron-select-ship', { mmsi: a.mmsi, lat: a.lat, lon: a.lon }); }
    else if (a.type === 'flight') { fire('xyron-enable-layer', 'aviation'); fire('xyron-flyto', { lat: a.lat, lon: a.lon }); fire('xyron-select-flight', { icao24: a.icao24, lat: a.lat, lon: a.lon }); }
    else if (a.type === 'match') fire('xyron-open-match', { id: a.id });
    else if (a.type === 'quote') fire('xyron-open-quote', { symbol: a.symbol, kind: a.kind });
  }

  // ----- keyboard -----
  input.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!S.flat.length) return;
      e.preventDefault();
      S.active = (S.active + (e.key === 'ArrowDown' ? 1 : -1) + S.flat.length) % S.flat.length; mark();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (S.flat.length) choose(S.active >= 0 ? S.active : 0);
      else if (S.q.trim().length >= 2) { clearTimeout(S.timer); run(S.q.trim()); }
    }
  });
  function typing(t) { return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable); }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && S.open) { e.stopPropagation(); close(); return; }
    if (S.open || e.altKey || e.isComposing) return;
    if ((e.key === 'k' || e.key === 'K') && (e.ctrlKey || e.metaKey)) { e.preventDefault(); open(); }
    else if (e.key === '/' && !e.ctrlKey && !e.metaKey && !typing(e.target)) { e.preventDefault(); open(); }
  }, true);
})();
