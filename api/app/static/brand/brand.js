// Loading screen with a typed boot log. It waits for the real things (your session, the live layers) and has fail-safes.
(function () {
  var splash = document.getElementById('splash');
  if (!splash) return;
  var speed = window.XYRON_FX_SPEED || 1;
  var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var stored = null;
  try { stored = localStorage.getItem('xyron.fx'); } catch (e) { /* storage unavailable */ }
  var effects = stored === null ? !reduce : stored === 'on';
  var seen = false;
  try { seen = sessionStorage.getItem('xyron.booted') === '1'; } catch (e) { /* storage unavailable */ }
  var started = performance.now();
  var finished = false;

  var old = splash.querySelector('p');
  if (old) old.remove();
  var log = document.createElement('pre');
  log.id = 'bootlog';
  splash.appendChild(log);

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function pause(ms) { return sleep(ms * speed); }
  function present(sel) { return !!document.querySelector(sel); }
  function operator() { var w = document.getElementById('who'); return !!(w && w.textContent.trim()); }
  async function waitFor(test, ms) {
    var t0 = performance.now();
    while (!finished && performance.now() - t0 < ms * speed) {
      if (test()) return true;
      await sleep(Math.max(5, 80 * speed));
    }
    return test();
  }
  function addLine(cls) {
    var d = document.createElement('div');
    if (cls) d.className = cls;
    log.appendChild(d);
    return d;
  }
  async function type(node, text, per) {
    if (!effects) { node.textContent += text; return; }
    node.classList.add('caret');
    for (var i = 0; i < text.length && !finished; i++) {
      node.textContent += text.charAt(i);
      await pause(per * (0.6 + Math.random()));
    }
    node.classList.remove('caret');
  }
  function token(node, text, cls) {
    var s = document.createElement('span');
    s.className = cls;
    s.textContent = text;
    node.appendChild(s);
  }

  async function boot() {
    if (seen) { // quick resume inside the same browser session
      await type(addLine(), '> XYRON // NODE-01 // RESUMING', 12);
      await waitFor(function () { return present('#layers .chip'); }, 5000);
      return;
    }
    var good = true;
    await type(addLine(), '> XYRON // NODE-01 // BLACKROOM', 16);
    var l2 = addLine();
    await type(l2, '> SECURE SESSION ........ ', 12);
    var s = await waitFor(operator, 4000);
    token(l2, s ? 'VERIFIED' : 'PENDING', s ? 'ok' : 'warn');
    good = good && s;
    var l3 = addLine();
    await type(l3, '> LIVE LAYERS ........... ', 12);
    var c = await waitFor(function () { return present('#layers .chip'); }, 5000);
    token(l3, c ? 'ONLINE (' + document.querySelectorAll('#layers .chip').length + ')' : 'DEGRADED', c ? 'ok' : 'warn');
    good = good && c;
    await type(addLine('dim'), '> FEEDS: USGS . OPEN-METEO . OPENSKY . ESPN . NEWS RSS', 8);
    var l5 = addLine();
    await type(l5, '> ', 10);
    token(l5, good ? 'ACCESS GRANTED' : 'ACCESS GRANTED (DEGRADED)', good ? 'ok' : 'warn');
  }

  function finish() {
    if (finished) return;
    finished = true;
    try { sessionStorage.setItem('xyron.booted', '1'); } catch (e) { /* ignore */ }
    var img = splash.querySelector('img');
    if (img && effects) img.classList.add('glitch');
    setTimeout(function () { splash.classList.add('done'); }, (effects ? 380 : 0) * speed);
    setTimeout(function () {
      splash.remove();
      window.dispatchEvent(new Event('xyron-booted'));
    }, (effects ? 1200 : 900) * speed);
  }

  splash.addEventListener('click', finish); // click, tap or any key skips
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' || e.key === ' ' || e.key === 'Enter') finish(); });
  setTimeout(finish, 14000 * speed); // hard fail-safe

  boot().then(function () {
    var hold = (effects ? (seen ? 700 : 2400) : 900) - (performance.now() - started);
    return sleep(Math.max(300, hold) * speed);
  }).then(finish);
})();
