// Alerts: connect Telegram, choose which alerts you want and how often, and see what was sent.
// Everything from the server is written with textContent, never as HTML.
(function () {
  'use strict';
  var bar = document.getElementById('bar');
  if (!bar) return; // only the globe page has a header
  var NS = 'http://www.w3.org/2000/svg';
  var BELL = ['M6 17V11a6 6 0 0 1 12 0v6l1.5 2h-15z', 'M10 21a2 2 0 0 0 4 0'];
  var RADII = [[100, '100 km'], [250, '250 km'], [500, '500 km'], [1000, '1,000 km'], [2000, '2,000 km'], [5000, '5,000 km']];
  var HOURS = []; for (var i = 0; i < 24; i++) HOURS.push(i);
  var FALLBACK_ZONES = ['Europe/London', 'Europe/Dublin', 'Europe/Paris', 'Europe/Berlin', 'Europe/Madrid', 'Europe/Istanbul', 'Africa/Cairo', 'Asia/Dubai', 'Asia/Karachi', 'Asia/Kolkata', 'Asia/Dhaka', 'Asia/Singapore', 'Asia/Tokyo',
    'Australia/Sydney', 'Pacific/Auckland', 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'America/Toronto', 'America/Sao_Paulo', 'UTC'];
  var S = { open: false, data: null, link: null, timers: {}, saves: {}, unlinkAsk: false, error: null };

  // ---------- helpers ----------
  function h(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; }
  function add(parent) { for (var i = 1; i < arguments.length; i++) if (arguments[i]) parent.appendChild(arguments[i]); return parent; }
  function svg(tag, attrs) { var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); return e; }
  function icon() {
    var s = svg('svg', { viewBox: '0 0 24 24', 'class': 'ico', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
    BELL.forEach(function (d) { s.appendChild(svg('path', { d: d })); });
    return s;
  }
  function api(path, opts) {
    var o = { credentials: 'same-origin' };
    for (var k in (opts || {})) o[k] = opts[k];
    return fetch(path, o).then(function (r) {
      if (r.status === 401) { location.href = '/login'; throw new Error('auth'); }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) { var e = new Error(path + ' ' + r.status); e.status = r.status; e.detail = typeof j.detail === 'string' ? j.detail : null; throw e; } return j; });
    });
  }
  function send(method, path, body) { return api(path, { method: method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) }); }
  function problem(e, fallback) { return e && e.detail ? e.detail : fallback; }
  function localTime(iso) { var d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); }
  function status(el, text, kind) { el.textContent = text || ''; el.className = 'a-msg' + (kind ? ' ' + kind : ''); }
  function cs(el, text, kind) { S.connMsg = text ? { text: text, kind: kind } : null; status(el, text, kind); } // the connection card's message survives its redraws
  function later(key, fn, ms) { clearTimeout(S.saves[key]); S.saves[key] = setTimeout(fn, ms); }

  // ---------- the header button and the overlay ----------
  var btn = h('button', 'alertbtn'); btn.id = 'alertbtn'; btn.type = 'button'; btn.title = 'Alerts';
  add(btn, icon(), h('span', 'lbl', 'ALERTS'));
  var after = document.getElementById('searchbtn') || document.getElementById('mktbtn') || document.getElementById('hubbtn') || bar.querySelector('.brand');
  if (after && after.nextSibling) bar.insertBefore(btn, after.nextSibling); else bar.appendChild(btn);
  btn.addEventListener('click', function () { if (S.open) close(); else open(); });
  ['hubbtn', 'mktbtn'].forEach(function (id) { var b = document.getElementById(id); if (b) b.addEventListener('click', function () { if (S.open) close(); }); });

  var root = h('div'); root.id = 'alerts'; root.hidden = true; root.setAttribute('role', 'dialog'); root.setAttribute('aria-modal', 'true'); root.setAttribute('aria-label', 'Alerts');
  var head = h('div', 'a-head'), title = h('div', 'a-title'), closeBtn = h('button', 'a-close', '\u00d7');
  closeBtn.type = 'button'; closeBtn.setAttribute('aria-label', 'Close');
  add(title, icon(), h('span', null, 'ALERTS // TELEGRAM')); add(head, title, closeBtn);
  var body = h('div', 'a-body'); add(root, head, body);
  document.body.appendChild(root);
  closeBtn.addEventListener('click', function () { close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && S.open) close(); });

  function open() {
    ['hub', 'mkt'].forEach(function (id) { var el = document.getElementById(id); if (el && !el.hidden) { var c = el.querySelector('.hub-close, .mk-close'); if (c) c.click(); } });
    S.open = true; root.hidden = false; document.body.classList.add('alerts-open'); load(true);
    S.timers.live = setInterval(function () { if (!document.hidden && S.open && !S.link) refreshLive(); }, 20000);
  }
  function close() {
    S.open = false; root.hidden = true; document.body.classList.remove('alerts-open');
    Object.keys(S.timers).forEach(function (k) { clearInterval(S.timers[k]); }); S.timers = {}; S.link = null;
    Object.keys(S.saves).forEach(function (k) { clearTimeout(S.saves[k]); });
  }

  // ---------- loading ----------
  function load(first) {
    if (first) body.replaceChildren(h('p', 'a-note', 'Loading\u2026'));
    return api('/api/alerts').then(function (d) { S.data = d; S.error = null; if (S.open) build(); }).catch(function (e) {
      if (S.open && first) body.replaceChildren(h('p', 'a-note err', 'Alerts are unavailable right now.'));
    });
  }
  function refreshLive() {
    return api('/api/alerts').then(function (d) {
      if (!S.open || !S.data) return;
      S.data.telegram = d.telegram; S.data.recent = d.recent; S.data.paused_until = d.paused_until; S.data.sent_24h = d.sent_24h; S.data.watchlist = d.watchlist;
      drawConnection(); drawPause(); drawRecent();
    }).catch(function () { /* quiet */ });
  }

  // ---------- the page ----------
  var elConn, elPause, elRecent;
  function card(titleText, blurb) { var c = h('section', 'a-card'); add(c, h('h3', null, titleText)); if (blurb) c.appendChild(h('p', 'a-blurb', blurb)); return c; }
  function build() {
    body.replaceChildren();
    var d = S.data;
    elConn = h('section', 'a-card conn'); elPause = h('section', 'a-card'); elRecent = h('section', 'a-card');
    add(body, h('p', 'a-intro', 'Nothing is sent until you switch an alert on. Related alerts are grouped into one message, the same thing is never sent twice, and you control the quiet hours and a daily limit.'),
      elConn, deliveryCard(d), elPause, h('h2', 'a-h2', 'WHAT TO BE TOLD ABOUT'));
    d.catalog.kinds.forEach(function (k) { if (d.rules[k.id]) body.appendChild(ruleCard(k, d.rules[k.id])); });
    add(body, elRecent);
    drawConnection(); drawPause(); drawRecent();
  }

  // ----- connecting Telegram -----
  function drawConnection() {
    var d = S.data, t = d.telegram, c = elConn;
    c.replaceChildren(h('h3', null, 'TELEGRAM'));
    var msg = h('div', 'a-msg'); msg.id = 'a-conn-msg';
    if (S.connMsg) status(msg, S.connMsg.text, S.connMsg.kind);
    if (!d.configured) { add(c, h('p', 'a-blurb', 'Telegram is not set up on this server yet. The owner needs to add the bot token.')); return; }
    if (t.linked) {
      var row = h('div', 'a-row');
      add(row, h('span', 'a-badge ok', 'CONNECTED'), h('span', 'a-dim', (t.name ? t.name + ' \u00b7 ' : '') + (t.since ? 'since ' + localTime(t.since) : '')));
      var test = h('button', 'a-btn', 'SEND A TEST ALERT'); test.type = 'button';
      test.addEventListener('click', function () {
        cs(msg, 'Sending\u2026');
        send('POST', '/api/alerts/test').then(function (r) { cs(msg, r.sent ? 'Sent. Check Telegram.' : 'It could not be sent right now.', r.sent ? 'ok' : 'err'); refreshLive(); })
          .catch(function (e) { cs(msg, problem(e, 'It could not be sent right now.'), 'err'); });
      });
      var un = h('button', 'a-btn danger', S.unlinkAsk ? 'CLICK AGAIN TO DISCONNECT' : 'DISCONNECT'); un.type = 'button';
      un.addEventListener('click', function () {
        if (!S.unlinkAsk) { S.unlinkAsk = true; drawConnection(); S.timers.ask = setTimeout(function () { S.unlinkAsk = false; if (S.open) drawConnection(); }, 4000); return; }
        S.unlinkAsk = false; clearTimeout(S.timers.ask);
        send('DELETE', '/api/alerts/telegram').then(function () { return load(); }).catch(function (e) { cs(msg, problem(e, 'Could not disconnect.'), 'err'); });
      });
      add(c, row, add(h('div', 'a-row'), test, un), msg, h('p', 'a-blurb', 'Send /status in Telegram at any time to see what is on, or /pause to pause everything.'));
      return;
    }
    var intro = t.blocked ? 'Telegram says you blocked the bot or deleted the chat, so alerts stopped. Connect again to restart them.' : 'Connect your Telegram account to receive alerts there. You press one button here, then press Start in Telegram.';
    add(c, h('p', 'a-blurb', intro));
    if (S.link) {
      var open = h('a', 'a-btn primary', 'OPEN TELEGRAM'); open.href = S.link.url; open.target = '_blank'; open.rel = 'noopener noreferrer';
      var left = Math.max(0, Math.round((S.link.expires - Date.now()) / 1000));
      if (!left) { S.link = null; S.expired = true; clearInterval(S.timers.poll); clearInterval(S.timers.tick); drawConnection(); return; } // the link ran out: offer a fresh one
      var count = h('span', 'a-dim'); count.id = 'a-countdown'; count.textContent = 'Press Start in Telegram. This link works for ' + Math.floor(left / 60) + ':' + ('0' + (left % 60)).slice(-2) + ' and then this page updates by itself.';
      add(c, add(h('div', 'a-row'), open), add(h('div', 'a-row'), count));
      return;
    }
    if (S.expired) add(c, h('p', 'a-msg err', 'That link expired before it was used. Make a new one.'));
    var go = h('button', 'a-btn primary', t.blocked ? 'CONNECT AGAIN' : 'CONNECT TELEGRAM'); go.type = 'button';
    go.addEventListener('click', function () {
      cs(msg, 'Making a link\u2026');
      send('POST', '/api/alerts/telegram/link').then(function (r) {
        S.connMsg = null; S.expired = false; S.link = { url: r.url, expires: Date.now() + r.expires_in * 1000 };
        drawConnection();
        S.timers.tick = setInterval(function () { if (S.link) drawConnection(); }, 1000);
        S.timers.poll = setInterval(function () {
          api('/api/alerts/telegram').then(function (t2) { if (t2.linked) { S.connMsg = null; S.link = null; clearInterval(S.timers.poll); clearInterval(S.timers.tick); load(); } }).catch(function () { /* keep waiting */ });
        }, 3000);
      }).catch(function (e) { cs(msg, problem(e, 'Could not make a link.'), 'err'); });
    });
    add(c, add(h('div', 'a-row'), go), msg);
  }

  // ----- quiet hours, limits and pausing -----
  function zones(current) {
    var list = [];
    try { if (typeof Intl.supportedValuesOf === 'function') list = Intl.supportedValuesOf('timeZone'); } catch (e) { list = []; }
    if (!list.length) list = FALLBACK_ZONES.slice();
    var browser; try { browser = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) { browser = null; }
    [current, browser].forEach(function (z) { if (z && list.indexOf(z) < 0) list.push(z); });
    return list;
  }
  function deliveryCard(d) {
    var c = card('DELIVERY', 'How and when alerts reach you.'), s = d.settings;
    var msg = h('div', 'a-msg');
    function field(label, control) { return add(h('label', 'a-field'), h('span', null, label), control); }
    var quietOn = h('input'); quietOn.type = 'checkbox'; quietOn.checked = !!s.quiet_start;
    var qs = h('input'); qs.type = 'time'; qs.value = s.quiet_start || '23:00'; var qe = h('input'); qe.type = 'time'; qe.value = s.quiet_end || '07:00';
    var tz = h('select'); zones(s.tz).forEach(function (z) { var o = h('option', null, z.replace(/_/g, ' ')); o.value = z; tz.appendChild(o); }); tz.value = s.tz;
    var cap = h('input'); cap.type = 'number'; cap.min = 5; cap.max = 200; cap.value = s.daily_cap;
    var mode = h('select'); [['instant', 'Instant'], ['digest', 'One daily summary']].forEach(function (m) { var o = h('option', null, m[1]); o.value = m[0]; mode.appendChild(o); }); mode.value = s.mode;
    var hour = h('select'); HOURS.forEach(function (x) { var o = h('option', null, ('0' + x).slice(-2) + ':00'); o.value = x; hour.appendChild(o); }); hour.value = s.digest_hour;
    var hourField = field('Summary time', hour);
    function sync() { qs.disabled = qe.disabled = !quietOn.checked; hourField.hidden = mode.value !== 'digest'; }
    function save() {
      sync();
      later('settings', function () {
        status(msg, 'Saving\u2026');
        send('PUT', '/api/alerts/settings', { tz: tz.value, quiet_start: quietOn.checked ? qs.value : null, quiet_end: quietOn.checked ? qe.value : null, daily_cap: parseInt(cap.value, 10) || 30, mode: mode.value, digest_hour: parseInt(hour.value, 10) })
          .then(function (r) { S.data.settings = r; status(msg, 'Saved', 'ok'); }).catch(function (e) { status(msg, problem(e, 'Could not save.'), 'err'); });
      }, 600);
    }
    [quietOn, qs, qe, tz, cap, mode, hour].forEach(function (el) { el.addEventListener('change', save); });
    add(c, add(h('div', 'a-grid'), field('Quiet hours', add(h('span', 'a-inline'), quietOn, h('span', null, 'on'))), field('From', qs), field('Until', qe), field('Time zone', tz), field('Most alerts a day', cap), field('Delivery', mode), hourField), msg,
      h('p', 'a-blurb', 'During quiet hours, ordinary alerts wait and arrive together afterwards. Urgent safety alerts (an aircraft emergency, a major quake, your account security) still come through.'));
    sync();
    return c;
  }
  function drawPause() {
    var d = S.data, c = elPause;
    c.replaceChildren(h('h3', null, 'PAUSE'));
    var msg = h('div', 'a-msg');
    function setPause(hours) { send('POST', '/api/alerts/pause', { hours: hours }).then(function (r) { S.data.paused_until = r.paused_until; drawPause(); }).catch(function (e) { status(msg, problem(e, 'Could not change the pause.'), 'err'); }); }
    if (d.paused_until) {
      var r = h('button', 'a-btn primary', 'RESUME NOW'); r.type = 'button'; r.addEventListener('click', function () { setPause(0); });
      add(c, h('p', 'a-blurb', 'Alerts are paused until ' + localTime(d.paused_until) + '. They are held, not lost.'), add(h('div', 'a-row'), r), msg);
    } else {
      var row = h('div', 'a-row');
      [[1, 'PAUSE 1 HOUR'], [8, 'PAUSE 8 HOURS'], [24, 'PAUSE 24 HOURS']].forEach(function (p) { var b = h('button', 'a-btn', p[1]); b.type = 'button'; b.addEventListener('click', function () { setPause(p[0]); }); row.appendChild(b); });
      add(c, h('p', 'a-blurb', 'Sent in the last 24 hours: ' + d.sent_24h + ' of ' + d.settings.daily_cap + '.'), row, msg);
    }
  }

  // ----- one card per kind of alert -----
  function chips(options, p, key, onChange) {
    // p[key] is read afresh on every press: after a save the server's cleaned copy replaces it
    var wrap = h('div', 'a-chips');
    options.forEach(function (o) {
      var b = h('button', 'a-chip' + (p[key].indexOf(o.id) >= 0 ? ' on' : ''), o.label); b.type = 'button'; b.setAttribute('aria-pressed', p[key].indexOf(o.id) >= 0 ? 'true' : 'false');
      b.addEventListener('click', function () {
        var chosen = p[key]; var i = chosen.indexOf(o.id); if (i >= 0) chosen.splice(i, 1); else chosen.push(o.id);
        b.classList.toggle('on', i < 0); b.setAttribute('aria-pressed', i < 0 ? 'true' : 'false'); onChange();
      });
      wrap.appendChild(b);
    });
    return wrap;
  }
  function numberField(label, value, min, max, step, onChange) {
    var inp = h('input'); inp.type = 'number'; inp.min = min; inp.max = max; inp.step = step; inp.value = value;
    inp.addEventListener('change', function () { onChange(parseFloat(inp.value)); });
    return add(h('label', 'a-field'), h('span', null, label), inp);
  }
  function checkField(label, checked, onChange) {
    var inp = h('input'); inp.type = 'checkbox'; inp.checked = !!checked; inp.addEventListener('change', function () { onChange(inp.checked); });
    return add(h('label', 'a-check'), inp, h('span', null, label));
  }
  function nearFields(p, changed) {
    var name = h('input'); name.type = 'text'; name.maxLength = 60; name.placeholder = 'Anywhere (or type a city or country)'; name.value = p.near ? p.near.name : '';
    var radius = h('select'); RADII.forEach(function (r) { var o = h('option', null, r[1]); o.value = r[0]; radius.appendChild(o); }); radius.value = p.near ? p.near.radius_km : 500;
    function upd() { p.near = name.value.trim() ? { name: name.value.trim(), radius_km: parseInt(radius.value, 10) } : null; changed(); }
    name.addEventListener('change', upd); radius.addEventListener('change', upd);
    return add(h('div', 'a-grid'), add(h('label', 'a-field wide'), h('span', null, 'Only near'), name), add(h('label', 'a-field'), h('span', null, 'Within'), radius));
  }
  function ruleCard(kind, rule) {
    var d = S.data, p = rule.params, c = h('section', 'a-card rule' + (rule.enabled ? ' on' : '')), msg = h('div', 'a-msg');
    var sw = h('input'); sw.type = 'checkbox'; sw.checked = rule.enabled; sw.id = 'a-sw-' + kind.id; sw.setAttribute('aria-label', 'Switch ' + kind.label + ' on');
    var top = add(h('div', 'a-top'), add(h('label', 'a-switch'), sw, h('i')), add(h('div', 'a-ttl'), h('h3', null, kind.label.toUpperCase()), h('p', 'a-blurb', kind.blurb)));
    var inner = h('div', 'a-inner');
    function save() {
      later('rule-' + kind.id, function () {
        status(msg, 'Saving\u2026');
        send('PUT', '/api/alerts/rules/' + kind.id, { enabled: rule.enabled, params: p }).then(function (r) {
          rule.params = r.params; Object.keys(p).forEach(function (k) { delete p[k]; }); Object.keys(r.params).forEach(function (k) { p[k] = r.params[k]; });
          status(msg, rule.enabled ? 'Saved. Only new events will be reported.' : 'Switched off.', 'ok');
        }).catch(function (e) { status(msg, problem(e, 'Could not save.'), 'err'); });
      }, 600);
    }
    sw.addEventListener('change', function () { rule.enabled = sw.checked; c.classList.toggle('on', sw.checked); save(); });
    var k = kind.id;
    if (k === 'quake') add(inner, numberField('Magnitude of at least', p.min_mag, 4, 9, 0.1, function (v) { p.min_mag = v; save(); }), nearFields(p, save));
    else if (k === 'hazard') add(inner, chips(d.catalog.hazard_categories, p, 'categories', save), nearFields(p, save));
    else if (k === 'price') add(inner, numberField('Move of at least (%)', p.threshold, 1, 50, 0.5, function (v) { p.threshold = v; save(); }), h('p', 'a-blurb', d.watchlist.length ? 'Watching ' + d.watchlist.length + ' from your Markets watchlist: ' + d.watchlist.slice(0, 8).join(', ') + (d.watchlist.length > 8 ? '\u2026' : '') + '.' : 'Your Markets watchlist is empty. Add tickers there and they are watched here.'));
    else if (k === 'index') add(inner, chips(d.catalog.indices.map(function (i) { return { id: i.symbol, label: i.name }; }), p, 'indices', save), numberField('Move of at least (%)', p.threshold, 0.5, 10, 0.5, function (v) { p.threshold = v; save(); }));
    else if (k === 'crypto') add(inner, chips(d.catalog.coins.map(function (x) { return { id: x, label: x }; }), p, 'coins', save), numberField('Move in 24 hours of at least (%)', p.threshold, 2, 50, 1, function (v) { p.threshold = v; save(); }));
    else if (k === 'football') {
      var list = h('div', 'a-chips'), inp = h('input'), addBtn = h('button', 'a-btn', 'ADD'); inp.type = 'text'; inp.maxLength = 40; inp.placeholder = 'A team, e.g. Arsenal'; addBtn.type = 'button';
      var drawTeams = function () {
        list.replaceChildren();
        p.teams.forEach(function (t) { var chip = h('span', 'a-chip on team'); chip.appendChild(h('span', null, t)); var x = h('button', 'x', '\u00d7'); x.type = 'button'; x.setAttribute('aria-label', 'Remove ' + t); x.addEventListener('click', function () { var j = p.teams.indexOf(t); if (j >= 0) p.teams.splice(j, 1); drawTeams(); save(); }); chip.appendChild(x); list.appendChild(chip); });
        if (!p.teams.length) list.appendChild(h('span', 'a-dim', 'No teams yet.'));
      };
      var addTeam = function () { var v = inp.value.trim().replace(/\s+/g, ' '); if (v.length < 2) return; if (!p.teams.some(function (t) { return t.toLowerCase() === v.toLowerCase(); })) { p.teams.push(v); drawTeams(); save(); } inp.value = ''; };
      addBtn.addEventListener('click', addTeam); inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); addTeam(); } });
      drawTeams();
      add(inner, list, add(h('div', 'a-row'), inp, addBtn), add(h('div', 'a-checks'), checkField('Kick-off', p.kickoff, function (v) { p.kickoff = v; save(); }), checkField('Goals', p.goals, function (v) { p.goals = v; save(); }), checkField('Full time', p.fulltime, function (v) { p.fulltime = v; save(); })),
        h('p', 'a-blurb', 'Type the team the way it appears on the football screen, such as Arsenal, Real Madrid or Manchester United.'));
    } else if (k === 'squawk') add(inner, chips(d.catalog.squawks.map(function (s) { return { id: s.code, label: s.code + ' ' + s.meaning }; }), p, 'codes', save));
    else if (k === 'security') add(inner, add(h('div', 'a-checks'), checkField('Sign-in from a new address', p.new_address, function (v) { p.new_address = v; save(); }), checkField('Repeated failed sign-ins on my account', p.failed, function (v) { p.failed = v; save(); })));
    else if (k === 'admin') add(inner, add(h('div', 'a-checks'), checkField('New registration waiting for approval', p.registrations, function (v) { p.registrations = v; save(); }), checkField('A burst of blocked sign-ins', p.blocked, function (v) { p.blocked = v; save(); })));
    add(c, top, inner, msg);
    if (rule.muted_until) c.appendChild(h('p', 'a-blurb', 'Muted until ' + localTime(rule.muted_until) + '.'));
    return c;
  }

  // ----- what was sent -----
  function drawRecent() {
    var c = elRecent, rec = S.data.recent;
    c.replaceChildren(h('h3', null, 'RECENT ALERTS'));
    if (!rec.length) { c.appendChild(h('p', 'a-blurb', 'Nothing yet. Alerts you receive are listed here, newest first.')); return; }
    var list = h('div', 'a-list');
    rec.forEach(function (r) {
      var row = h('div', 'a-rec ' + r.status);
      add(row, h('span', 'a-when', localTime(r.at)), h('span', 'a-what', r.text), h('span', 'a-state', r.status === 'suppressed' && r.reason ? 'held back: ' + r.reason : r.status));
      list.appendChild(row);
    });
    c.appendChild(list);
  }
})();
