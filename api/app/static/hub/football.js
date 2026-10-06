// Football hub: live scores, fixtures, league tables, football news and a match centre, plus a view of the other sports.
// Everything from the server is written with textContent, never as HTML.
(function () {
  'use strict';
  var bar = document.getElementById('bar');
  if (!bar) return; // only the globe page has a header
  var PREF_KEY = 'xyron.hub';
  var BALL = ['M12 8.3l3.3 2.4-1.3 3.9h-4l-1.3-3.9z', 'M12 8.3V3.2', 'M15.3 10.7l4.6-1.5', 'M14 14.6l2.9 3.9', 'M10 14.6l-2.9 3.9', 'M8.7 10.7 4.1 9.2'];
  var KIND_TAG = { goal: 'GOAL', penalty: 'PEN', owngoal: 'OWN GOAL', penmiss: 'PEN MISS', yellow: 'YELLOW', red: 'RED', sub: 'SUB', var: 'VAR', period: '', other: '' };
  var S = { open: false, mode: 'football', tab: 'matches', day: 'today', league: '', q: '', sel: null, matches: [], leagues: [], sports: [], sportFilter: '',
    centre: null, centreTab: 'events', liveCount: 0, timers: {}, newsLeague: '', tableLeague: '' };
  try { var saved = JSON.parse(localStorage.getItem(PREF_KEY)); if (saved && typeof saved === 'object') { S.day = saved.day || S.day; S.tab = saved.tab || S.tab; } } catch (e) { /* storage unavailable */ }
  function savePrefs() { try { localStorage.setItem(PREF_KEY, JSON.stringify({ day: S.day, tab: S.tab })); } catch (e) { /* ignore */ } }

  // ---------- small helpers ----------
  function h(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function add(parent) { for (var i = 1; i < arguments.length; i++) if (arguments[i]) parent.appendChild(arguments[i]); return parent; }
  function icon(paths, circle) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', 'ico'); svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '1.8');
    svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round');
    if (circle) { var c = document.createElementNS(ns, 'circle'); c.setAttribute('cx', 12); c.setAttribute('cy', 12); c.setAttribute('r', 9); svg.appendChild(c); }
    paths.forEach(function (d) { var p = document.createElementNS(ns, 'path'); p.setAttribute('d', d); svg.appendChild(p); });
    return svg;
  }
  function api(path) {
    return fetch(path, { credentials: 'same-origin' }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; throw new Error('auth'); }
      if (!r.ok) throw new Error(path + ' ' + r.status);
      return r.json();
    });
  }
  function lum(hex) {
    var n = parseInt(hex, 16);
    return (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
  }
  function badge(team, big) {
    var b = h('span', 'badge' + (big ? ' big' : ''));
    var c = team && team.color;
    if (c && /^[0-9a-fA-F]{6}$/.test(c)) { b.style.background = '#' + c; b.style.color = lum(c) > 0.55 ? '#000' : '#fff'; }
    b.textContent = String((team && (team.abbr || team.name)) || '?').slice(0, 3).toUpperCase();
    return b;
  }
  function localTime(iso) {
    var d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  function ago(iso) {
    var t = Date.parse(iso);
    if (isNaN(t)) return '';
    var m = Math.max(0, Math.round((Date.now() - t) / 60000));
    if (m < 60) return m + ' min ago';
    if (m < 1440) return Math.floor(m / 60) + ' h ago';
    return Math.floor(m / 1440) + ' d ago';
  }
  function safeUrl(u) { return typeof u === 'string' && u.indexOf('https://') === 0 ? u : null; }
  function dayRange(offset) {
    var a = new Date(); a.setHours(0, 0, 0, 0); a.setDate(a.getDate() + offset);
    var b = new Date(a); b.setDate(b.getDate() + 1);
    return { from: a.toISOString(), to: b.toISOString() };
  }
  function fly(m) {
    if (typeof m.lat !== 'number' || typeof m.lon !== 'number') return;
    close();
    window.dispatchEvent(new CustomEvent('xyron-flyto', { detail: { lat: m.lat, lon: m.lon } }));
  }
  function empty(text) { return h('p', 'hub-empty', text); }

  // ---------- the header button ----------
  var btn = h('button', 'hubbtn');
  btn.id = 'hubbtn'; btn.type = 'button'; btn.title = 'Open the football hub';
  var btnLabel = h('span', 'lbl', 'FOOTBALL');
  var btnLive = h('span', 'livecount'); btnLive.hidden = true;
  add(btn, icon(BALL, true), btnLabel, btnLive);
  var brand = bar.querySelector('.brand');
  if (brand && brand.nextSibling) bar.insertBefore(btn, brand.nextSibling); else bar.appendChild(btn);
  btn.addEventListener('click', function () { if (S.open) close(); else open(); });
  function showLive() {
    btnLive.hidden = !S.liveCount;
    btnLive.textContent = S.liveCount ? 'LIVE ' + S.liveCount : '';
    btn.classList.toggle('isLive', S.liveCount > 0);
  }
  function pollLive() {
    if (document.hidden) return;
    api('/api/football/matches?state=in').then(function (r) { S.liveCount = (r.matches || []).length; showLive(); }).catch(function () { /* quiet */ });
  }
  pollLive();
  setInterval(pollLive, 60000);

  // ---------- the overlay ----------
  var hub = h('div'); hub.id = 'hub'; hub.hidden = true; hub.setAttribute('role', 'dialog'); hub.setAttribute('aria-modal', 'true'); hub.setAttribute('aria-label', 'Football hub');
  var head = h('div', 'hub-head');
  var title = h('div', 'hub-title'); add(title, icon(BALL, true), h('span', null, 'FOOTBALL // MATCH CENTRE'));
  var modes = h('div', 'hub-modes'), nav = h('div', 'hub-nav');
  var closeBtn = h('button', 'hub-close', '\u00d7'); closeBtn.type = 'button'; closeBtn.setAttribute('aria-label', 'Close');
  add(head, title, modes, nav, closeBtn);
  var body = h('div', 'hub-body');
  var listPane = h('section', 'hub-list'), centrePane = h('section', 'hub-centre');
  add(body, listPane, centrePane);
  add(hub, head, body);
  document.body.appendChild(hub);
  closeBtn.addEventListener('click', function () { close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && S.open) close(); });

  function open() {
    S.open = true; hub.hidden = false; document.body.classList.add('hub-open');
    render(); load(); startTimers(); closeBtn.focus();
  }
  function close() {
    S.open = false; hub.hidden = true; document.body.classList.remove('hub-open'); stopTimers();
  }
  function stopTimers() { Object.keys(S.timers).forEach(function (k) { clearInterval(S.timers[k]); }); S.timers = {}; }
  function startTimers() {
    stopTimers();
    S.timers.list = setInterval(function () { if (!document.hidden && S.tab === 'matches') loadList(true); }, 20000);
    S.timers.centre = setInterval(function () { if (!document.hidden && S.centre && S.centre.state === 'in') loadCentre(S.sel, true); }, 15000);
  }

  // ---------- top bars ----------
  function renderBars() {
    modes.replaceChildren(); nav.replaceChildren();
    [['football', 'FOOTBALL'], ['sports', 'OTHER SPORTS']].forEach(function (m) {
      var b = h('button', 'tab' + (S.mode === m[0] ? ' on' : ''), m[1]); b.type = 'button';
      b.addEventListener('click', function () { S.mode = m[0]; S.sel = null; S.centre = null; render(); load(); });
      modes.appendChild(b);
    });
    if (S.mode === 'football') {
      [['matches', 'MATCHES'], ['tables', 'TABLES'], ['news', 'NEWS']].forEach(function (t) {
        var b = h('button', 'tab' + (S.tab === t[0] ? ' on' : ''), t[1]); b.type = 'button';
        b.addEventListener('click', function () { S.tab = t[0]; savePrefs(); render(); load(); });
        nav.appendChild(b);
      });
    }
  }

  function render() {
    renderBars();
    hub.classList.toggle('mc-open', !!S.sel && S.mode === 'football' && S.tab === 'matches');
    if (S.mode === 'sports') { renderSports(); centrePane.replaceChildren(); hub.classList.add('single'); return; }
    hub.classList.toggle('single', S.tab !== 'matches');
    if (S.tab === 'matches') { renderList(); renderCentre(); } else if (S.tab === 'tables') renderTables(); else renderNews();
  }
  function load() {
    if (S.mode === 'sports') return loadSports();
    if (S.tab === 'matches') { loadList(); if (S.sel) loadCentre(S.sel); } else if (S.tab === 'tables') loadTables(); else loadNews();
  }

  // ---------- matches ----------
  var DAYS = [['live', 'LIVE NOW'], ['yesterday', 'YESTERDAY'], ['today', 'TODAY'], ['tomorrow', 'TOMORROW']];
  function loadList(quiet) {
    var url = '/api/football/matches';
    if (S.day === 'live') url += '?state=in';
    else { var r = dayRange({ yesterday: -1, today: 0, tomorrow: 1 }[S.day] || 0); url += '?from=' + encodeURIComponent(r.from) + '&to=' + encodeURIComponent(r.to); }
    var p = [api(url)];
    if (!S.leagues.length) p.push(api('/api/football/leagues').catch(function () { return []; }));
    return Promise.all(p).then(function (res) {
      S.matches = res[0].matches || [];
      if (res[1]) S.leagues = res[1];
      if (S.day === 'live') { S.liveCount = S.matches.length; showLive(); }
      if (S.open && S.tab === 'matches') renderList();
    }).catch(function (e) { if (!quiet && S.open) { listPane.replaceChildren(empty('Football scores are unavailable right now.')); } });
  }
  function groupMatches(matches) {
    var q = S.q.trim().toLowerCase();
    var order = {}; S.leagues.forEach(function (l, i) { order[l.name] = i; });
    var groups = {};
    matches.forEach(function (m) {
      var name = m.league || 'Other competitions';
      if (S.league && name !== S.league) return;
      if (q && (String(m.home && m.home.name).toLowerCase() + ' ' + String(m.away && m.away.name).toLowerCase() + ' ' + name.toLowerCase()).indexOf(q) < 0) return;
      (groups[name] = groups[name] || []).push(m);
    });
    return Object.keys(groups).sort(function (a, b) {
      var oa = a === 'Other competitions' ? 9999 : (order[a] === undefined ? 5000 : order[a]);
      var ob = b === 'Other competitions' ? 9999 : (order[b] === undefined ? 5000 : order[b]);
      return oa - ob || a.localeCompare(b);
    }).map(function (name) { return { name: name, matches: groups[name] }; });
  }
  function renderList() {
    listPane.replaceChildren();
    var tabs = h('div', 'daytabs');
    DAYS.forEach(function (d) {
      var b = h('button', 'tab' + (S.day === d[0] ? ' on' : '') + (d[0] === 'live' ? ' livetab' : ''), d[1]); b.type = 'button';
      b.addEventListener('click', function () { S.day = d[0]; savePrefs(); S.matches = []; renderList(); loadList(); });
      tabs.appendChild(b);
    });
    var tools = h('div', 'tools');
    var search = h('input'); search.type = 'search'; search.placeholder = 'Search team or league'; search.value = S.q; search.setAttribute('aria-label', 'Search');
    search.addEventListener('input', function () { S.q = search.value; renderGroups(); });
    var sel = h('select'); sel.setAttribute('aria-label', 'League');
    var names = {}; S.matches.forEach(function (m) { names[m.league || 'Other competitions'] = 1; });
    var optAll = h('option', null, 'All competitions'); optAll.value = ''; sel.appendChild(optAll);
    Object.keys(names).sort().forEach(function (n) { var o = h('option', null, n); o.value = n; sel.appendChild(o); });
    sel.value = names[S.league] ? S.league : ''; if (!names[S.league]) S.league = '';
    sel.addEventListener('change', function () { S.league = sel.value; renderGroups(); });
    add(tools, search, sel);
    var groupsEl = h('div', 'groups'); groupsEl.id = 'hub-groups';
    add(listPane, tabs, tools, groupsEl);
    renderGroups();
  }
  function renderGroups() {
    var el = document.getElementById('hub-groups');
    if (!el) return;
    el.replaceChildren();
    var groups = groupMatches(S.matches);
    if (!groups.length) { el.appendChild(empty(S.day === 'live' ? 'No football is being played right now.' : S.matches.length ? 'Nothing matches that search.' : 'No matches listed for this day.')); return; }
    groups.forEach(function (g) {
      var box = h('div', 'group');
      add(box, h('h3', null, g.name));
      g.matches.forEach(function (m) { box.appendChild(matchRow(m)); });
      el.appendChild(box);
    });
  }
  function statusCell(m) {
    if (m.state === 'in') return h('span', 'mstat live', m.status || 'LIVE');
    if (m.state === 'post') return h('span', 'mstat fin', m.status && m.status.length <= 8 ? m.status : 'FT');
    return h('span', 'mstat pre', localTime(m.start));
  }
  function matchRow(m) {
    var row = h('div', 'mrow' + (m.state === 'in' ? ' live' : '') + (S.sel === m.id ? ' sel' : ''));
    var main = h('button', 'mmain'); main.type = 'button';
    var score = m.state === 'pre' ? h('span', 'mscore vs', 'vs') : h('span', 'mscore', (m.home && m.home.score || '0') + ' \u2013 ' + (m.away && m.away.score || '0'));
    var home = h('span', 'mteam home'), away = h('span', 'mteam away');
    add(home, h('span', 'tname', m.home && m.home.name), badge(m.home));
    add(away, badge(m.away), h('span', 'tname', m.away && m.away.name));
    add(main, statusCell(m), home, score, away);
    main.addEventListener('click', function () { S.sel = m.id; S.centre = null; S.centreTab = 'events'; hub.classList.add('mc-open'); renderList(); renderCentre(m); loadCentre(m.id); });
    var loc = h('button', 'mloc'); loc.type = 'button'; loc.title = 'Show the venue on the globe'; loc.setAttribute('aria-label', 'Show on globe');
    loc.appendChild(icon(['M12 21s-6-5.4-6-10a6 6 0 0 1 12 0c0 4.6-6 10-6 10z', 'M12 8.5v5M9.5 11h5']));
    loc.disabled = typeof m.lat !== 'number'; loc.addEventListener('click', function () { fly(m); });
    return add(row, main, loc);
  }

  // ---------- match centre ----------
  function loadCentre(id, quiet) {
    if (!id) return;
    return api('/api/football/match/' + encodeURIComponent(id)).then(function (c) {
      if (S.sel !== id) return; // the user moved on
      S.centre = c;
      if (S.open && S.tab === 'matches') renderCentre();
    }).catch(function () { if (!quiet && S.sel === id) renderCentre(null, true); });
  }
  function renderCentre(listMatch, failed) {
    centrePane.replaceChildren();
    if (!S.sel) { centrePane.appendChild(h('div', 'hub-hint', 'Select a match for lineups, events and stats.')); return; }
    var c = S.centre;
    var fallback = listMatch || S.matches.filter(function (m) { return m.id === S.sel; })[0] || {};
    var m = c || { home: fallback.home, away: fallback.away, state: fallback.state, status: fallback.status, league: fallback.league, venue: fallback.venue, city: fallback.city, events: [], stats: [], lineups: {}, commentary: [], league_slug: fallback.league_slug };
    var back = h('button', 'mc-back', '\u2039 MATCHES'); back.type = 'button'; back.addEventListener('click', function () { S.sel = null; S.centre = null; render(); });
    var top = h('div', 'mc-top');
    add(top, h('div', 'mc-league', m.league || 'Football'));
    var board = h('div', 'mc-board');
    var hs = h('div', 'mc-team'), as = h('div', 'mc-team');
    add(hs, badge(m.home, true), h('div', 'mc-name', m.home && m.home.name));
    add(as, badge(m.away, true), h('div', 'mc-name', m.away && m.away.name));
    var mid = h('div', 'mc-score');
    add(mid, h('div', 'big', m.state === 'pre' ? 'vs' : (m.home && m.home.score || '0') + ' \u2013 ' + (m.away && m.away.score || '0')),
      h('div', 'mc-status' + (m.state === 'in' ? ' live' : ''), m.state === 'pre' ? localTime(fallback.start || m.start) : (m.status || '')));
    add(board, hs, mid, as);
    var meta = [m.venue && (m.venue + (m.city ? ', ' + m.city : '')), m.attendance && 'Attendance ' + Number(m.attendance).toLocaleString(), m.referee && 'Referee ' + m.referee].filter(Boolean).join('  \u00b7  ');
    add(top, board, meta ? h('div', 'mc-meta', meta) : null);
    var tabs = h('div', 'mc-tabs');
    [['events', 'EVENTS'], ['lineups', 'LINEUPS'], ['stats', 'STATS'], ['commentary', 'COMMENTARY'], ['table', 'TABLE']].forEach(function (t) {
      if (t[0] === 'commentary' && !(m.commentary && m.commentary.length)) return;
      var b = h('button', 'tab' + (S.centreTab === t[0] ? ' on' : ''), t[1]); b.type = 'button';
      b.addEventListener('click', function () { S.centreTab = t[0]; renderCentre(); }); tabs.appendChild(b);
    });
    var pane = h('div', 'mc-pane');
    if (failed && !c) pane.appendChild(empty('Match details are unavailable right now.'));
    else if (S.centreTab === 'events') pane.appendChild(eventsView(m));
    else if (S.centreTab === 'lineups') pane.appendChild(lineupsView(m));
    else if (S.centreTab === 'stats') pane.appendChild(statsView(m));
    else if (S.centreTab === 'commentary') pane.appendChild(commentaryView(m));
    else pane.appendChild(tableForMatch(m));
    add(centrePane, back, top, tabs, pane);
  }
  function eventsView(m) {
    var wrap = h('div', 'timeline');
    if (!m.events || !m.events.length) return empty(m.state === 'pre' ? 'Events appear here once the match starts.' : 'No events listed for this match.');
    m.events.forEach(function (e) {
      var row = h('div', 'tl ' + (e.side || 'mid') + ' k-' + e.kind);
      var tag = KIND_TAG[e.kind];
      var text = h('div', 'tl-text');
      if (tag) add(text, h('span', 'tag k-' + e.kind, tag));
      add(text, h('span', 'who', e.player || (e.kind === 'period' ? e.text : '')));
      if (e.kind === 'other' && !e.player) text.appendChild(h('span', 'who', e.text));
      var minute = h('div', 'tl-min', e.minute);
      if (e.side === 'home') add(row, text, minute, h('div'));
      else if (e.side === 'away') add(row, h('div'), minute, text);
      else add(row, h('div'), minute, text);
      wrap.appendChild(row);
    });
    return wrap;
  }
  function lineupsView(m) {
    var wrap = h('div', 'lineups'), any = false;
    ['home', 'away'].forEach(function (side) {
      var l = m.lineups && m.lineups[side];
      var col = h('div', 'lu');
      add(col, h('h4', null, (m[side] && m[side].name || side.toUpperCase()) + (l && l.formation ? '  ' + l.formation : '')));
      if (l && l.starters && l.starters.length) {
        any = true;
        l.starters.forEach(function (p) { add(col, h('div', 'pl', (p.number ? p.number + '  ' : '') + p.name + (p.pos ? '  ' + p.pos : ''))); });
        if (l.subs && l.subs.length) { add(col, h('h5', null, 'SUBSTITUTES')); l.subs.forEach(function (p) { add(col, h('div', 'pl sub' + (p.subbed ? ' used' : ''), (p.number ? p.number + '  ' : '') + p.name)); }); }
      } else col.appendChild(h('div', 'pl dim', 'Not published yet'));
      wrap.appendChild(col);
    });
    return any ? wrap : empty('Lineups are usually published about an hour before kick-off.');
  }
  function num(v) { var n = parseFloat(String(v).replace('%', '').replace('+', '')); return isNaN(n) ? null : n; }
  function statsView(m) {
    if (!m.stats || !m.stats.length) return empty('No stats yet.');
    var wrap = h('div', 'stats'), seasonShown = false;
    m.stats.forEach(function (s) {
      if (s.season && !seasonShown) { seasonShown = true; wrap.appendChild(h('h5', null, 'SEASON TOTALS')); }
      var a = num(s.home), b = num(s.away), tot = (a || 0) + (b || 0);
      var row = h('div', 'stat');
      var left = h('span', 'sv', s.home), right = h('span', 'sv', s.away);
      var bars = h('div', 'bars'), lb = h('i', 'lb'), rb = h('i', 'rb');
      var pa = a !== null && tot > 0 ? Math.round((a / tot) * 100) : 0, pb = b !== null && tot > 0 ? Math.round((b / tot) * 100) : 0;
      lb.style.width = pa + '%'; rb.style.width = pb + '%';
      add(bars, lb, rb);
      add(row, left, h('span', 'sl', s.label), right, bars);
      wrap.appendChild(row);
    });
    return wrap;
  }
  function commentaryView(m) {
    var wrap = h('div', 'commentary');
    (m.commentary || []).forEach(function (c) { add(wrap, add(h('div', 'cm'), h('span', 'min', c.minute), h('span', 'tx', c.text))); });
    return wrap;
  }
  function tableForMatch(m) {
    var wrap = h('div', 'tbl-wrap');
    if (!m.league_slug) return empty('No league table for this competition.');
    wrap.appendChild(empty('Loading the table\u2026'));
    api('/api/football/standings?league=' + encodeURIComponent(m.league_slug)).then(function (t) {
      wrap.replaceChildren(tableView(t, [m.home && m.home.name, m.away && m.away.name]));
    }).catch(function () { wrap.replaceChildren(empty('The table is unavailable right now.')); });
    return wrap;
  }

  // ---------- tables ----------
  function tableView(data, highlight) {
    var box = h('div', 'tables');
    if (!data || !data.groups || !data.groups.length) return empty('No table available.');
    data.groups.forEach(function (g) {
      if (data.groups.length > 1) box.appendChild(h('h4', null, g.name));
      var t = h('div', 'tbl');
      var hd = h('div', 'tr th'); ['#', 'TEAM', 'P', 'W', 'D', 'L', 'GD', 'PTS'].forEach(function (c, i) { hd.appendChild(h('span', i === 1 ? 'team' : 'n', c)); }); t.appendChild(hd);
      g.rows.forEach(function (r) {
        var row = h('div', 'tr' + (highlight && highlight.indexOf(r.team) >= 0 ? ' hl' : ''));
        if (r.note_color && /^#[0-9a-fA-F]{6}$/.test(r.note_color)) row.style.borderLeftColor = r.note_color;
        if (r.note) row.title = r.note;
        var team = h('span', 'team'); add(team, badge({ abbr: r.abbr, name: r.team, color: r.color }), h('span', null, r.team));
        add(row, h('span', 'n', r.rank), team, h('span', 'n', r.played === null ? '' : r.played), h('span', 'n', r.won === null ? '' : r.won), h('span', 'n', r.drawn === null ? '' : r.drawn),
          h('span', 'n', r.lost === null ? '' : r.lost), h('span', 'n', r.gd === null ? '' : (r.gd > 0 ? '+' : '') + r.gd), h('span', 'n pts', r.pts === null ? '' : r.pts));
        t.appendChild(row);
      });
      box.appendChild(t);
    });
    return box;
  }
  function leaguePicker(current, onChange, withAll) {
    var sel = h('select'); sel.setAttribute('aria-label', 'League');
    if (withAll) { var a = h('option', null, 'All football'); a.value = ''; sel.appendChild(a); }
    S.leagues.forEach(function (l) { var o = h('option', null, l.name); o.value = l.slug; sel.appendChild(o); });
    sel.value = current; sel.addEventListener('change', function () { onChange(sel.value); });
    return sel;
  }
  function loadTables() {
    return (S.leagues.length ? Promise.resolve() : api('/api/football/leagues').then(function (l) { S.leagues = l; }).catch(function () { })).then(function () {
      if (!S.tableLeague && S.leagues.length) S.tableLeague = S.leagues[0].slug;
      renderTables();
    });
  }
  function renderTables() {
    listPane.replaceChildren(); centrePane.replaceChildren();
    var pane = h('div', 'wide');
    if (!S.leagues.length) { listPane.appendChild(empty('League tables appear once the first scores have loaded.')); return; }
    var holder = h('div', 'tbl-holder'); holder.appendChild(empty('Loading the table\u2026'));
    add(pane, add(h('div', 'tools'), leaguePicker(S.tableLeague, function (v) { S.tableLeague = v; renderTables(); }, false)), holder);
    listPane.appendChild(pane);
    api('/api/football/standings?league=' + encodeURIComponent(S.tableLeague)).then(function (t) { holder.replaceChildren(tableView(t)); })
      .catch(function () { holder.replaceChildren(empty('The table is unavailable right now.')); });
  }

  // ---------- news ----------
  function loadNews() {
    return (S.leagues.length ? Promise.resolve() : api('/api/football/leagues').then(function (l) { S.leagues = l; }).catch(function () { })).then(renderNews);
  }
  function renderNews() {
    listPane.replaceChildren(); centrePane.replaceChildren();
    var pane = h('div', 'wide'), holder = h('div', 'news'); holder.appendChild(empty('Loading the news\u2026'));
    add(pane, add(h('div', 'tools'), leaguePicker(S.newsLeague, function (v) { S.newsLeague = v; renderNews(); }, true)), holder);
    listPane.appendChild(pane);
    api('/api/football/news' + (S.newsLeague ? '?league=' + encodeURIComponent(S.newsLeague) : '')).then(function (items) {
      holder.replaceChildren();
      if (!items.length) { holder.appendChild(empty('No football news right now.')); return; }
      items.forEach(function (n) {
        var url = safeUrl(n.url); if (!url) return;
        var a = h('a', 'item'); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        add(a, h('span', 'nt', n.title), h('span', 'ns', n.source + (n.published ? '  \u00b7  ' + ago(n.published) : '')));
        holder.appendChild(a);
      });
    }).catch(function () { holder.replaceChildren(empty('Football news is unavailable right now.')); });
  }

  // ---------- other sports ----------
  function loadSports() {
    return api('/api/matches?hours=36&limit=500').then(function (rows) {
      S.sports = rows.filter(function (r) { return r.sport !== 'football' && r.detail; }); renderSports();
    }).catch(function () { listPane.replaceChildren(empty('Sports scores are unavailable right now.')); });
  }
  function renderSports() {
    listPane.replaceChildren();
    var counts = {}, labels = {};
    S.sports.forEach(function (r) { counts[r.sport] = (counts[r.sport] || 0) + 1; labels[r.sport] = r.detail.sport_label || r.sport; });
    var chips = h('div', 'daytabs');
    var all = h('button', 'tab' + (!S.sportFilter ? ' on' : ''), 'ALL'); all.type = 'button'; all.addEventListener('click', function () { S.sportFilter = ''; renderSports(); }); chips.appendChild(all);
    Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; }).forEach(function (s) {
      var b = h('button', 'tab' + (S.sportFilter === s ? ' on' : ''), labels[s].toUpperCase() + ' ' + counts[s]); b.type = 'button';
      b.addEventListener('click', function () { S.sportFilter = s; renderSports(); }); chips.appendChild(b);
    });
    var groups = {};
    S.sports.filter(function (r) { return !S.sportFilter || r.sport === S.sportFilter; }).forEach(function (r) {
      var k = (r.detail.sport_label || r.sport) + (r.detail.league ? ' \u00b7 ' + r.detail.league : '');
      (groups[k] = groups[k] || []).push(r);
    });
    var el = h('div', 'groups');
    var keys = Object.keys(groups).sort();
    if (!keys.length) el.appendChild(empty('No games listed right now.'));
    keys.forEach(function (k) {
      var box = h('div', 'group'); box.appendChild(h('h3', null, k));
      groups[k].forEach(function (r) {
        var d = r.detail, row = h('div', 'mrow' + (r.state === 'in' ? ' live' : ''));
        var main = h('div', 'mmain static');
        var st = r.state === 'in' ? h('span', 'mstat live', d.status || 'LIVE') : r.state === 'post' ? h('span', 'mstat fin', 'FT') : h('span', 'mstat pre', localTime(d.start || r.start_at));
        if (d.home && d.away) {
          var home = h('span', 'mteam home'), away = h('span', 'mteam away');
          add(home, h('span', 'tname', d.home.name), badge(d.home)); add(away, badge(d.away), h('span', 'tname', d.away.name));
          add(main, st, home, r.state === 'pre' ? h('span', 'mscore vs', 'vs') : h('span', 'mscore', (d.home.score || '0') + ' \u2013 ' + (d.away.score || '0')), away);
        } else {
          var names = (d.competitors || []).slice(0, 3).map(function (c) { return c.name; }).join(', ');
          add(main, st, h('span', 'tname wide', r.title + (names ? '  \u00b7  ' + names : '')));
        }
        var loc = h('button', 'mloc'); loc.type = 'button'; loc.title = 'Show on the globe'; loc.setAttribute('aria-label', 'Show on globe');
        loc.appendChild(icon(['M12 21s-6-5.4-6-10a6 6 0 0 1 12 0c0 4.6-6 10-6 10z', 'M12 8.5v5M9.5 11h5']));
        loc.disabled = typeof r.lat !== 'number'; loc.addEventListener('click', function () { fly(r); });
        add(row, main, loc);
        var url = safeUrl(r.url);
        if (url) { var a = h('a', 'mlink', 'ESPN'); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; row.appendChild(a); }
        box.appendChild(row);
      });
      el.appendChild(box);
    });
    add(listPane, chips, el);
  }
})();
