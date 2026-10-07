// Markets: crypto, stocks, indices, commodities and currencies, exchanges that are open, a watchlist, charts and a ticker tape.
// Everything from the server is written with textContent, never as HTML.
(function () {
  'use strict';
  var bar = document.getElementById('bar');
  if (!bar) return; // only the globe page has a header
  var TREND = ['M3 17l6-6 4 4 8-8', 'M15 7h6v6'];
  var TABS = [['overview', 'OVERVIEW'], ['crypto', 'CRYPTO'], ['stock', 'STOCKS'], ['index', 'INDICES'], ['commodity', 'COMMODITIES'], ['fx', 'CURRENCIES'], ['exchanges', 'EXCHANGES'], ['watch', 'WATCHLIST']];
  var RANGES = [['1d', '1D'], ['5d', '5D'], ['1mo', '1M'], ['6mo', '6M'], ['1y', '1Y']];
  var OVERVIEW = {
    index: ['^GSPC', '^IXIC', '^DJI', '^FTSE', '^GDAXI', '^FCHI', '^N225', '^HSI', '000001.SS', '^NSEI'],
    commodity: ['GC=F', 'SI=F', 'PL=F', 'PA=F', 'HG=F', 'CL=F', 'BZ=F', 'NG=F'],
    fx: ['GBPUSD=X', 'EURUSD=X', 'USDJPY=X', 'DX-Y.NYB'],
  };
  var S = { open: false, tab: 'overview', kinds: {}, movers: null, exchanges: [], watch: [], sel: null, range: '1d', chart: null, sort: { key: 'default', dir: 1 }, q: '', filter: '', timers: {}, ticker: [] };
  try { var saved = JSON.parse(localStorage.getItem('xyron.markets')); if (saved && saved.tab) S.tab = saved.tab; } catch (e) { /* storage unavailable */ }
  function savePrefs() { try { localStorage.setItem('xyron.markets', JSON.stringify({ tab: S.tab })); } catch (e) { /* ignore */ } }

  // ---------- helpers ----------
  function h(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; }
  function add(parent) { for (var i = 1; i < arguments.length; i++) if (arguments[i]) parent.appendChild(arguments[i]); return parent; }
  var NS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs) { var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); return e; }
  function icon(paths) {
    var s = svg('svg', { viewBox: '0 0 24 24', 'class': 'ico', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
    paths.forEach(function (d) { s.appendChild(svg('path', { d: d })); });
    return s;
  }
  function api(path, opts) {
    var o = { credentials: 'same-origin' };
    for (var k in (opts || {})) o[k] = opts[k];
    return fetch(path, o).then(function (r) {
      if (r.status === 401) { location.href = '/login'; throw new Error('auth'); }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) { var e = new Error(path + ' ' + r.status); e.detail = j && j.detail; throw e; } return j; });
    });
  }
  function num(v) { return typeof v === 'number' && isFinite(v) ? v : null; }
  function fmtPrice(p, kind) {
    p = num(p); if (p === null) return '\u2013';
    var a = Math.abs(p), d = kind === 'fx' ? (a < 20 ? 4 : 2) : a >= 1 ? 2 : a >= 0.01 ? 4 : 6;
    return p.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function fmtBig(n) {
    n = num(n); if (n === null) return '\u2013';
    var a = Math.abs(n);
    return a >= 1e12 ? (n / 1e12).toFixed(2) + ' T' : a >= 1e9 ? (n / 1e9).toFixed(2) + ' B' : a >= 1e6 ? (n / 1e6).toFixed(1) + ' M' : a >= 1e3 ? (n / 1e3).toFixed(1) + ' K' : n.toFixed(0);
  }
  function change(pct, big) {
    pct = num(pct);
    if (pct === null) return h('span', 'chg flat', '\u2013');
    var up = pct >= 0.005, down = pct <= -0.005;
    return h('span', 'chg ' + (up ? 'up' : down ? 'down' : 'flat') + (big ? ' big' : ''), (up ? '\u25b2 ' : down ? '\u25bc ' : '\u25cf ') + Math.abs(pct).toFixed(2) + '%');
  }
  function ago(sec) {
    if (sec === null || sec === undefined) return 'never';
    if (sec < 90) return sec + ' s ago';
    if (sec < 5400) return Math.round(sec / 60) + ' min ago';
    return Math.round(sec / 3600) + ' h ago';
  }
  function dot(q) {
    var d = h('span', 'fresh ' + (q.age === null || q.age === undefined ? 'old' : q.age < 150 ? 'live' : q.age < 1500 ? 'mid' : 'old'));
    d.title = 'Updated ' + ago(q.age) + ' via ' + (q.source || '?');
    return d;
  }
  function spark(points, up) {
    var s = svg('svg', { viewBox: '0 0 80 24', 'class': 'spark', preserveAspectRatio: 'none', 'aria-hidden': 'true' });
    if (!points || points.length < 2) return s;
    var min = Math.min.apply(null, points), max = Math.max.apply(null, points), span = max - min || 1;
    var d = points.map(function (v, i) { return (i ? 'L' : 'M') + (i / (points.length - 1) * 80).toFixed(1) + ' ' + (22 - (v - min) / span * 20).toFixed(1); }).join('');
    s.appendChild(svg('path', { d: d, 'class': 'line ' + (up === null ? 'flat' : up ? 'up' : 'down'), fill: 'none' }));
    return s;
  }
  function trendUp(q) { var s = q.spark; return s && s.length > 1 ? s[s.length - 1] >= s[0] : (num(q.change_pct) === null ? null : q.change_pct >= 0); }
  function fly(lat, lon) {
    if (typeof lat !== 'number' || typeof lon !== 'number') return;
    close();
    window.dispatchEvent(new CustomEvent('xyron-flyto', { detail: { lat: lat, lon: lon } }));
  }

  // ---------- header button and ticker tape ----------
  var btn = h('button', 'mkbtn'); btn.id = 'mktbtn'; btn.type = 'button'; btn.title = 'Open the markets';
  add(btn, icon(TREND), h('span', 'lbl', 'MARKETS'));
  var after = document.getElementById('hubbtn') || bar.querySelector('.brand');
  if (after && after.nextSibling) bar.insertBefore(btn, after.nextSibling); else bar.appendChild(btn);
  btn.addEventListener('click', function () { if (S.open) close(); else open(); });
  var hubBtn = document.getElementById('hubbtn');
  if (hubBtn) hubBtn.addEventListener('click', function () { if (S.open) close(); });

  var tape = h('div', 'ticker'); tape.id = 'ticker'; tape.hidden = true;
  var track = h('div', 'track'); tape.appendChild(track);
  document.body.appendChild(tape);
  tape.addEventListener('click', function () { open(); });
  function loadTicker() {
    if (document.hidden) return;
    api('/api/markets/ticker').then(function (items) {
      S.ticker = Array.isArray(items) ? items : [];
      track.replaceChildren();
      if (!S.ticker.length) { tape.hidden = true; document.body.classList.remove('has-ticker'); return; }
      for (var pass = 0; pass < 2; pass++) {
        S.ticker.forEach(function (t) {
          var item = h('span', 'tk');
          add(item, h('span', 'tk-sym', String(t.name || t.symbol).replace(/ \(.*\)$/, '')), h('span', 'tk-px', fmtPrice(t.price, t.kind)), change(t.change_pct));
          track.appendChild(item);
        });
      }
      track.style.animationDuration = Math.max(40, S.ticker.length * 6) + 's';
      tape.hidden = false; document.body.classList.add('has-ticker');
    }).catch(function () { /* the tape just stays as it was */ });
  }
  loadTicker();
  setInterval(loadTicker, 30000);

  // ---------- the overlay ----------
  var root = h('div'); root.id = 'mkt'; root.hidden = true; root.setAttribute('role', 'dialog'); root.setAttribute('aria-modal', 'true'); root.setAttribute('aria-label', 'Markets');
  var head = h('div', 'mk-head'), title = h('div', 'mk-title'), tabs = h('div', 'mk-tabs'), closeBtn = h('button', 'mk-close', '\u00d7');
  closeBtn.type = 'button'; closeBtn.setAttribute('aria-label', 'Close');
  add(title, icon(TREND), h('span', null, 'MARKETS // LIVE'));
  add(head, title, tabs, closeBtn);
  var body = h('div', 'mk-body'), main = h('section', 'mk-main'), side = h('section', 'mk-side');
  var foot = h('div', 'mk-foot', 'Information only, not financial advice. Crypto is live from Binance (CoinGecko for ranks). US stocks come from Finnhub, close to real time. Other stocks, indices, commodities and currencies come from Yahoo Finance and can run 10 to 15 minutes behind. These free sources are unofficial and can fail.');
  add(body, main, side); add(root, head, body, foot);
  document.body.appendChild(root);
  closeBtn.addEventListener('click', function () { close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && S.open) close(); });

  function open() {
    var hub = document.getElementById('hub');
    if (hub && !hub.hidden) { var hc = hub.querySelector('.hub-close'); if (hc) hc.click(); }
    S.open = true; root.hidden = false; document.body.classList.add('mkt-open');
    render(); load(); startTimers(); closeBtn.focus();
  }
  function close() { S.open = false; root.hidden = true; document.body.classList.remove('mkt-open'); stopTimers(); }
  function stopTimers() { Object.keys(S.timers).forEach(function (k) { clearInterval(S.timers[k]); }); S.timers = {}; }
  function startTimers() {
    stopTimers();
    S.timers.data = setInterval(function () { if (!document.hidden && S.open) load(true); }, 20000);
    S.timers.chart = setInterval(function () { if (!document.hidden && S.open && S.sel && S.range === '1d') loadChart(true); }, 60000);
  }

  function renderTabs() {
    tabs.replaceChildren();
    TABS.forEach(function (t) {
      var b = h('button', 'tab' + (S.tab === t[0] ? ' on' : ''), t[1]); b.type = 'button';
      b.addEventListener('click', function () { S.tab = t[0]; S.sel = null; S.q = ''; S.filter = ''; S.sort = { key: 'default', dir: 1 }; savePrefs(); render(); load(); });
      tabs.appendChild(b);
    });
  }
  function render() {
    renderTabs();
    root.classList.toggle('sel', !!S.sel);
    if (S.tab === 'overview') renderOverview();
    else if (S.tab === 'exchanges') renderExchanges();
    else if (S.tab === 'watch') renderWatch();
    else renderList(S.tab);
    renderDetail();
  }

  // ---------- loading ----------
  function loadKind(kind) {
    return api('/api/markets/quotes?kind=' + kind).then(function (r) { S.kinds[kind] = r.quotes || []; });
  }
  function load(quiet) {
    var jobs = [];
    var need = S.tab === 'overview' ? ['index', 'commodity', 'fx', 'crypto'] : ['crypto', 'stock', 'index', 'commodity', 'fx'].indexOf(S.tab) >= 0 ? [S.tab] : S.tab === 'watch' ? ['watch'] : [];
    need.forEach(function (k) { jobs.push(loadKind(k)); });
    if (S.tab === 'overview') jobs.push(api('/api/markets/movers').then(function (m) { S.movers = m; }));
    if (S.tab === 'exchanges' || S.tab === 'overview') jobs.push(api('/api/markets/exchanges').then(function (e) { S.exchanges = e; }));
    if (S.tab === 'watch' || !S.watchLoaded) jobs.push(api('/api/markets/watchlist').then(function (w) { S.watch = w; S.watchLoaded = true; }).catch(function () { }));
    return Promise.all(jobs).then(function () { if (S.open) render(); }).catch(function (e) {
      if (!quiet && S.open) { main.replaceChildren(h('p', 'mk-empty', 'Market data is unavailable right now.')); }
    });
  }

  // ---------- overview ----------
  function pick(kind, symbols) {
    var by = {}; (S.kinds[kind] || []).forEach(function (q) { by[q.symbol] = q; });
    return symbols.map(function (s) { return by[s]; }).filter(Boolean);
  }
  function miniRow(q) {
    var row = h('button', 'mini'); row.type = 'button';
    add(row, dot(q), h('span', 'nm', q.name), h('span', 'px', fmtPrice(q.price, q.kind)), change(q.change_pct));
    row.addEventListener('click', function () { choose(q); });
    return row;
  }
  function card(titleText, rows, empty, tab) {
    var c = h('div', 'card'), hd = h('div', 'card-h');
    add(hd, h('span', null, titleText));
    if (tab) { var more = h('button', 'more', 'ALL \u203a'); more.type = 'button'; more.addEventListener('click', function () { S.tab = tab; S.sel = null; savePrefs(); render(); load(); }); hd.appendChild(more); }
    c.appendChild(hd);
    if (!rows.length) c.appendChild(h('p', 'mk-empty', empty || 'Loading\u2026'));
    rows.forEach(function (r) { c.appendChild(r); });
    return c;
  }
  function moverRows(list) { return (list || []).map(miniRow); }
  function renderOverview() {
    main.replaceChildren();
    var grid = h('div', 'cards');
    var open = S.exchanges.filter(function (e) { return e.state === 'open'; });
    add(grid,
      card('GLOBAL INDICES', pick('index', OVERVIEW.index).map(miniRow), 'No index prices yet.', 'index'),
      card('COMMODITIES', pick('commodity', OVERVIEW.commodity).map(miniRow), 'No commodity prices yet.', 'commodity'),
      card('CURRENCIES', pick('fx', OVERVIEW.fx).map(miniRow), 'No currency prices yet.', 'fx'),
      card('CRYPTO TOP 10', (S.kinds.crypto || []).slice(0, 10).map(miniRow), 'No crypto prices yet.', 'crypto'),
      card('STOCK GAINERS', moverRows(S.movers && S.movers.stock.gainers), 'No stock prices yet.', 'stock'),
      card('STOCK LOSERS', moverRows(S.movers && S.movers.stock.losers), 'No stock prices yet.', 'stock'),
      card('CRYPTO GAINERS', moverRows(S.movers && S.movers.crypto.gainers), 'No crypto prices yet.', 'crypto'),
      card('CRYPTO LOSERS', moverRows(S.movers && S.movers.crypto.losers), 'No crypto prices yet.', 'crypto'));
    var ex = h('div', 'card wide'); var exh = h('div', 'card-h'); exh.appendChild(h('span', null, 'EXCHANGES OPEN NOW  ' + open.length + ' / ' + S.exchanges.length));
    var exm = h('button', 'more', 'ALL \u203a'); exm.type = 'button'; exm.addEventListener('click', function () { S.tab = 'exchanges'; savePrefs(); render(); load(); }); exh.appendChild(exm); ex.appendChild(exh);
    var chips = h('div', 'exchips'); open.forEach(function (e) { chips.appendChild(add(h('span', 'exchip'), h('span', null, e.exchange), change(e.change_pct))); });
    ex.appendChild(open.length ? chips : h('p', 'mk-empty', S.exchanges.length ? 'All exchanges are closed right now.' : 'Loading\u2026'));
    grid.appendChild(ex);
    main.appendChild(grid);
  }

  // ---------- lists ----------
  var COLUMNS = {
    crypto: [['rank', '#'], ['name', 'NAME'], ['price', 'PRICE'], ['change', '24H'], ['d7', '7D'], ['mcap', 'MARKET CAP'], ['spark', '7 DAYS']],
    stock: [['name', 'NAME'], ['sector', 'SECTOR'], ['price', 'PRICE'], ['change', 'CHANGE'], ['spark', '5 DAYS']],
    index: [['name', 'INDEX'], ['country', 'COUNTRY'], ['price', 'LEVEL'], ['change', 'CHANGE'], ['spark', '5 DAYS']],
    commodity: [['name', 'COMMODITY'], ['group', 'UNIT'], ['price', 'PRICE'], ['change', 'CHANGE'], ['spark', '5 DAYS']],
    fx: [['name', 'PAIR'], ['price', 'RATE'], ['change', 'CHANGE'], ['spark', '5 DAYS']],
    watch: [['name', 'NAME'], ['price', 'PRICE'], ['change', 'CHANGE'], ['spark', '5 DAYS'], ['x', '']],
  };
  function filterField(kind) { return { stock: 'sector', index: 'country', commodity: 'group' }[kind]; }
  function metaOf(q, f) { return f === 'group' ? (q.meta && q.meta.group) : q.meta && q.meta[f]; }
  function sortVal(q, key) {
    if (key === 'rank') return q.rank === null || q.rank === undefined ? 1e9 : q.rank;
    if (key === 'price') return num(q.price) === null ? -1e18 : q.price;
    if (key === 'change') return num(q.change_pct) === null ? -1e18 : q.change_pct;
    if (key === 'd7') return q.meta && num(q.meta.change_7d) !== null ? q.meta.change_7d : -1e18;
    if (key === 'mcap') return num(q.market_cap) === null ? -1e18 : q.market_cap;
    return String(key === 'sector' || key === 'country' || key === 'group' ? metaOf(q, key) || '' : q.name).toLowerCase();
  }
  function rowsFor(kind) {
    var rows = (S.kinds[kind] || []).slice();
    var f = filterField(kind), needle = S.q.trim().toLowerCase();
    if (S.filter && f) rows = rows.filter(function (q) { return metaOf(q, f) === S.filter; });
    if (needle) rows = rows.filter(function (q) { return q.symbol.toLowerCase().indexOf(needle) >= 0 || q.name.toLowerCase().indexOf(needle) >= 0; });
    if (S.sort.key !== 'default') rows.sort(function (a, b) { var x = sortVal(a, S.sort.key), y = sortVal(b, S.sort.key); return (x < y ? -1 : x > y ? 1 : 0) * S.sort.dir; });
    return rows;
  }
  function renderList(kind) {
    main.replaceChildren();
    var tools = h('div', 'tools');
    var search = h('input'); search.type = 'search'; search.placeholder = 'Search name or ticker'; search.value = S.q; search.setAttribute('aria-label', 'Search');
    search.addEventListener('input', function () { S.q = search.value; renderTable(kind); });
    tools.appendChild(search);
    var f = filterField(kind);
    if (f) {
      var vals = {}; (S.kinds[kind] || []).forEach(function (q) { var v = metaOf(q, f); if (v) vals[v] = 1; });
      var sel = h('select'); sel.setAttribute('aria-label', 'Filter');
      var all = h('option', null, 'All'); all.value = ''; sel.appendChild(all);
      Object.keys(vals).sort().forEach(function (v) { var o = h('option', null, v); o.value = v; sel.appendChild(o); });
      sel.value = vals[S.filter] ? S.filter : ''; if (!vals[S.filter]) S.filter = '';
      sel.addEventListener('change', function () { S.filter = sel.value; renderTable(kind); });
      tools.appendChild(sel);
    }
    var holder = h('div', 'tbl-holder'); holder.id = 'mk-table';
    add(main, tools, holder);
    renderTable(kind);
  }
  function renderTable(kind) {
    var holder = document.getElementById('mk-table');
    if (!holder) return;
    holder.replaceChildren();
    var cols = COLUMNS[kind], rows = rowsFor(kind);
    var t = h('div', 'mk-table k-' + kind), hd = h('div', 'mk-row mk-th');
    cols.forEach(function (c) {
      var cell = h('button', 'cell c-' + c[0] + (S.sort.key === c[0] ? ' sorted' : ''), c[1] + (S.sort.key === c[0] ? (S.sort.dir > 0 ? ' \u2191' : ' \u2193') : '')); cell.type = 'button';
      if (c[0] !== 'spark' && c[0] !== 'x') cell.addEventListener('click', function () {
        S.sort = S.sort.key === c[0] ? { key: c[0], dir: -S.sort.dir } : { key: c[0], dir: (c[0] === 'name' || c[0] === 'rank' || c[0] === 'sector' || c[0] === 'country' || c[0] === 'group') ? 1 : -1 };
        renderTable(kind);
      });
      hd.appendChild(cell);
    });
    t.appendChild(hd);
    if (!rows.length) { holder.appendChild(t); holder.appendChild(h('p', 'mk-empty', S.kinds[kind] ? (kind === 'watch' ? 'Your watchlist is empty. Add a ticker above.' : 'Nothing matches.') : 'Loading\u2026')); return; }
    rows.forEach(function (q) { t.appendChild(tableRow(kind, cols, q)); });
    holder.appendChild(t);
  }
  function tableRow(kind, cols, q) {
    var row = h('div', 'mk-row' + (S.sel && S.sel.symbol === q.symbol ? ' sel' : ''));
    cols.forEach(function (c) {
      var cell = h('div', 'cell c-' + c[0]);
      if (c[0] === 'rank') cell.textContent = q.rank === null || q.rank === undefined ? '' : q.rank;
      else if (c[0] === 'name') add(cell, dot(q), h('span', 'nm', q.name), h('span', 'sym', q.symbol.replace(/=F$|=X$/, '')));
      else if (c[0] === 'price') cell.textContent = fmtPrice(q.price, q.kind) + (q.currency && q.kind !== 'fx' && q.kind !== 'crypto' && q.kind !== 'index' ? ' ' + q.currency : '');
      else if (c[0] === 'change') cell.appendChild(change(q.change_pct));
      else if (c[0] === 'd7') cell.appendChild(change(q.meta && q.meta.change_7d));
      else if (c[0] === 'mcap') cell.textContent = fmtBig(q.market_cap);
      else if (c[0] === 'sector') cell.textContent = (q.meta && q.meta.sector) || '';
      else if (c[0] === 'country') cell.textContent = (q.meta && q.meta.country) || '';
      else if (c[0] === 'group') cell.textContent = (q.meta && q.meta.group) || '';
      else if (c[0] === 'spark') cell.appendChild(spark(q.spark, trendUp(q)));
      else if (c[0] === 'x') {
        var x = h('button', 'unwatch', '\u00d7'); x.type = 'button'; x.title = 'Remove from the watchlist'; x.setAttribute('aria-label', 'Remove ' + q.symbol);
        x.addEventListener('click', function (ev) { ev.stopPropagation(); unwatch(q.symbol); }); cell.appendChild(x);
      }
      row.appendChild(cell);
    });
    row.addEventListener('click', function () { choose(q); });
    return row;
  }

  // ---------- exchanges ----------
  function renderExchanges() {
    main.replaceChildren();
    if (!S.exchanges.length) { main.appendChild(h('p', 'mk-empty', 'Loading\u2026')); return; }
    var order = { open: 0, quiet: 1, 'break': 2, closed: 3 };
    var list = h('div', 'exlist');
    S.exchanges.slice().sort(function (a, b) { return order[a.state] - order[b.state] || a.exchange.localeCompare(b.exchange); }).forEach(function (e) {
      var row = h('div', 'exrow ' + e.state);
      add(row, h('span', 'state', e.state.toUpperCase()), add(h('span', 'exname'), h('b', null, e.exchange), h('small', null, e.city + ', ' + e.country)),
        add(h('span', 'exidx'), h('span', null, e.index), h('span', 'px', fmtPrice(e.level, 'index')), change(e.change_pct)),
        add(h('span', 'extime'), h('span', null, e.local_time), h('small', null, e.label)), h('span', 'exhours', e.hours));
      var loc = h('button', 'mloc'); loc.type = 'button'; loc.title = 'Show on the globe'; loc.setAttribute('aria-label', 'Show on globe');
      loc.appendChild(icon(['M12 21s-6-5.4-6-10a6 6 0 0 1 12 0c0 4.6-6 10-6 10z', 'M12 8.5v5M9.5 11h5'])); loc.addEventListener('click', function () { fly(e.lat, e.lon); });
      row.appendChild(loc); list.appendChild(row);
    });
    main.appendChild(list);
    main.appendChild(h('p', 'mk-note', 'Opening hours follow the normal timetable. Public holidays are not listed; an exchange whose index goes quiet during its session shows as QUIET.'));
  }

  // ---------- watchlist ----------
  function renderWatch() {
    main.replaceChildren();
    var form = h('div', 'tools wl'), input = h('input'); input.type = 'text'; input.placeholder = 'Add a ticker, e.g. NVDA, RR.L, 7974.T'; input.maxLength = 15; input.setAttribute('aria-label', 'Ticker');
    var go = h('button', 'addbtn', 'ADD'); go.type = 'button';
    var msg = h('div', 'wl-msg'); msg.id = 'wl-msg';
    function submit() {
      var v = input.value.trim(); if (!v) return;
      msg.textContent = 'Looking it up\u2026'; msg.className = 'wl-msg';
      api('/api/markets/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: v }) }).then(function (w) {
        S.watch = w; input.value = ''; msg.textContent = ''; loadKind('watch').then(function () { if (S.open && S.tab === 'watch') { render(); var again = main.querySelector('.wl input'); if (again) again.focus(); } });
      }).catch(function (e) { msg.textContent = typeof e.detail === 'string' ? e.detail : 'Could not add that ticker.'; msg.className = 'wl-msg err'; });
    }
    go.addEventListener('click', submit); input.addEventListener('keydown', function (e) { if (e.key === 'Enter') submit(); });
    add(form, input, go);
    var holder = h('div', 'tbl-holder'); holder.id = 'mk-table';
    add(main, form, msg, holder);
    renderTable('watch');
  }
  function unwatch(sym) {
    api('/api/markets/watchlist/' + encodeURIComponent(sym), { method: 'DELETE' }).then(function (w) {
      S.watch = w; if (S.sel && S.sel.symbol === sym && S.tab === 'watch') S.sel = null;
      return loadKind('watch');
    }).then(function () { if (S.open) render(); }).catch(function () { /* quiet */ });
  }

  // ---------- detail and chart ----------
  function choose(q) { S.sel = q; S.range = '1d'; S.chart = null; render(); loadChart(); }
  function loadChart(quiet) {
    if (!S.sel) return;
    var sym = S.sel.symbol, rng = S.range;
    return api('/api/markets/chart?symbol=' + encodeURIComponent(sym) + '&range=' + rng).then(function (c) {
      if (!S.sel || S.sel.symbol !== sym || S.range !== rng) return;
      S.chart = c; if (S.open) drawChart();
    }).catch(function () { if (!quiet && S.sel && S.sel.symbol === sym) { S.chart = { error: true }; if (S.open) drawChart(); } });
  }
  function renderDetail() {
    side.replaceChildren();
    root.classList.toggle('sel', !!S.sel);
    if (!S.sel) { side.appendChild(h('div', 'mk-hint', 'Select an instrument for its chart and details.')); return; }
    var q = S.sel;
    var fresh = (S.kinds[q.kind] || []).concat(S.kinds.watch || []).filter(function (x) { return x.symbol === q.symbol; })[0];
    if (fresh) q = S.sel = fresh;
    var back = h('button', 'mk-back', '\u2039 BACK'); back.type = 'button'; back.addEventListener('click', function () { S.sel = null; render(); });
    var top = h('div', 'dt-top');
    var star = h('button', 'star' + (S.watch.indexOf(q.symbol) >= 0 ? ' on' : ''), S.watch.indexOf(q.symbol) >= 0 ? '\u2605 WATCHING' : '\u2606 WATCH'); star.type = 'button';
    star.addEventListener('click', function () {
      var on = S.watch.indexOf(q.symbol) >= 0;
      (on ? api('/api/markets/watchlist/' + encodeURIComponent(q.symbol), { method: 'DELETE' }) : api('/api/markets/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: q.symbol }) }))
        .then(function (w) { S.watch = w; renderDetail(); }).catch(function (e) { star.textContent = typeof e.detail === 'string' ? e.detail : 'Could not change that.'; });
    });
    add(top, add(h('div', 'dt-name'), h('h2', null, q.name), h('span', 'sym', q.symbol)), star);
    var px = h('div', 'dt-price'); add(px, h('span', 'big', fmtPrice(q.price, q.kind) + (q.currency && q.kind !== 'crypto' && q.kind !== 'index' && q.kind !== 'fx' ? ' ' + q.currency : '')), change(q.change_pct, true));
    var ranges = h('div', 'ranges');
    RANGES.forEach(function (r) { var b = h('button', 'tab' + (S.range === r[0] ? ' on' : ''), r[1]); b.type = 'button'; b.addEventListener('click', function () { S.range = r[0]; S.chart = null; renderDetail(); loadChart(); }); ranges.appendChild(b); });
    var chart = h('div', 'chart'); chart.id = 'mk-chart';
    var stats = h('dl', 'stats');
    function row(k, v) { if (v === null || v === undefined || v === '') return; stats.appendChild(h('dt', null, k)); stats.appendChild(h('dd', null, v)); }
    row('PREVIOUS CLOSE', num(q.prev_close) === null ? null : fmtPrice(q.prev_close, q.kind));
    row('DAY RANGE', num(q.day_low) !== null && num(q.day_high) !== null ? fmtPrice(q.day_low, q.kind) + ' \u2013 ' + fmtPrice(q.day_high, q.kind) : null);
    row('VOLUME', num(q.volume) === null ? null : fmtBig(q.volume));
    row('MARKET CAP', num(q.market_cap) === null ? null : '$' + fmtBig(q.market_cap));
    row('RANK', q.rank ? '#' + q.rank : null);
    row('SECTOR', q.meta && q.meta.sector);
    row('COUNTRY', q.meta && q.meta.country);
    row('UNIT', q.meta && q.meta.unit);
    row('SOURCE', q.source === 'binance' ? 'Binance (live)' : q.source === 'finnhub' ? 'Finnhub (near real time)' : q.source === 'yahoo' ? 'Yahoo Finance (can be delayed)' : q.source === 'coingecko' ? 'CoinGecko (every few minutes)' : q.source);
    row('UPDATED', ago(q.age));
    add(side, back, top, px, ranges, chart, stats);
    drawChart();
  }
  var resizeTimer = null;
  window.addEventListener('resize', function () { clearTimeout(resizeTimer); resizeTimer = setTimeout(function () { if (S.open && S.sel) drawChart(); }, 150); });
  function timeLabel(ms, range) {
    var d = new Date(ms);
    return range === '1d' ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : range === '5d' ? d.toLocaleDateString([], { weekday: 'short' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : d.toLocaleDateString([], { day: 'numeric', month: 'short', year: range === '1y' ? '2-digit' : undefined });
  }
  function drawChart() {
    var el = document.getElementById('mk-chart');
    if (!el) return;
    el.replaceChildren();
    var c = S.chart;
    if (!c) { el.appendChild(h('p', 'mk-empty', 'Loading the chart\u2026')); return; }
    if (c.error || !c.points || c.points.length < 2) { el.appendChild(h('p', 'mk-empty', c.error ? 'The chart is unavailable right now.' : 'No chart data for this range.')); return; }
    var pts = c.points, W = Math.max(280, Math.round(el.clientWidth || 520)), H = 210, padL = 4, padR = 58, padT = 10, padB = 22;
    var vals = pts.map(function (p) { return p[1]; }), min = Math.min.apply(null, vals), max = Math.max.apply(null, vals), span = max - min || 1;
    var x = function (i) { return padL + i / (pts.length - 1) * (W - padL - padR); }, y = function (v) { return padT + (1 - (v - min) / span) * (H - padT - padB); };
    var up = vals[vals.length - 1] >= vals[0], cls = up ? 'up' : 'down';
    var line = pts.map(function (p, i) { return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(p[1]).toFixed(1); }).join('');
    var s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, 'class': 'bigchart' });
    s.appendChild(svg('path', { d: line + 'L' + x(pts.length - 1).toFixed(1) + ' ' + (H - padB) + 'L' + x(0).toFixed(1) + ' ' + (H - padB) + 'Z', 'class': 'area ' + cls }));
    s.appendChild(svg('path', { d: line, 'class': 'ln ' + cls, fill: 'none' }));
    [[max, padT + 8], [min, H - padB - 2]].forEach(function (g) { var t = svg('text', { x: W - padR + 4, y: g[1], 'class': 'axis' }); t.textContent = fmtPrice(g[0], S.sel && S.sel.kind); s.appendChild(t); });
    var t0 = svg('text', { x: padL, y: H - 6, 'class': 'axis' }); t0.textContent = timeLabel(pts[0][0], c.range); s.appendChild(t0);
    var t1 = svg('text', { x: W - padR, y: H - 6, 'class': 'axis end' }); t1.textContent = timeLabel(pts[pts.length - 1][0], c.range); s.appendChild(t1);
    var cross = svg('line', { y1: padT, y2: H - padB, 'class': 'cross', x1: 0, x2: 0, visibility: 'hidden' }); s.appendChild(cross);
    var tip = h('div', 'ctip'); tip.hidden = true;
    s.addEventListener('mousemove', function (ev) {
      var r = s.getBoundingClientRect(), fx = (ev.clientX - r.left) / r.width * W;
      var i = Math.max(0, Math.min(pts.length - 1, Math.round((fx - padL) / (W - padL - padR) * (pts.length - 1))));
      cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
      tip.textContent = fmtPrice(pts[i][1], S.sel && S.sel.kind) + '  \u00b7  ' + timeLabel(pts[i][0], c.range); tip.hidden = false;
    });
    s.addEventListener('mouseleave', function () { cross.setAttribute('visibility', 'hidden'); tip.hidden = true; });
    add(el, s, tip);
  }
  // the search bar opens an instrument by its ticker
  window.addEventListener('xyron-open-quote', function (ev) {
    var d = ev.detail || {};
    if (!d.symbol) return;
    var kind = ['crypto', 'stock', 'index', 'commodity', 'fx'].indexOf(d.kind) >= 0 ? d.kind : 'stock';
    S.tab = kind; S.sel = null; S.q = ''; S.filter = ''; S.sort = { key: 'default', dir: 1 }; savePrefs();
    if (S.open) render(); else open();
    loadKind(kind).then(function () {
      var q = (S.kinds[kind] || []).filter(function (x) { return x.symbol === d.symbol; })[0];
      if (!S.open) return;
      if (q) choose(q); else render(); // an instrument we do not have just shows the list
    }).catch(function () { /* the list shows its own message */ });
  });
})();
