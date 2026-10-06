// XYRON blackroom effects: scanlines and HUD corners, UTC clock, FX switch, typed and decoded text, sign-in terminal.
(function () {
  'use strict';
  var FX_KEY = 'xyron.fx';
  var speed = window.XYRON_FX_SPEED || 1;
  var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
  var GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&@$<>/';

  function fxWanted() {
    var v = null;
    try { v = localStorage.getItem(FX_KEY); } catch (e) { /* storage unavailable */ }
    return v === null ? !reduce : v === 'on';
  }
  function fxOn() { return !document.body.classList.contains('fx-off'); }
  function el(tag, props) {
    var e = document.createElement(tag);
    for (var k in props) e[k] = props[k];
    return e;
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms * speed); }); }

  // types text into an element one character at a time (all at once when effects are off)
  function typeInto(node, text, perChar) {
    return new Promise(function (resolve) {
      if (!fxOn()) { node.textContent = text; resolve(); return; }
      var i = 0;
      (function step() {
        node.textContent = text.slice(0, ++i);
        if (i >= text.length) { resolve(); return; }
        setTimeout(step, (perChar || 22) * speed * (0.6 + Math.random() * 0.9));
      })();
    });
  }

  function setFx(on) {
    document.body.classList.toggle('fx-off', !on);
    try { localStorage.setItem(FX_KEY, on ? 'on' : 'off'); } catch (e) { /* ignore */ }
    var b = document.getElementById('fxbtn');
    if (b) b.setAttribute('aria-pressed', on ? 'true' : 'false');
  }

  function buildOverlay() {
    if (document.getElementById('fx')) return;
    var fx = el('div', { id: 'fx' });
    fx.setAttribute('aria-hidden', 'true');
    fx.appendChild(document.createElement('b'));
    var hud = el('div', { id: 'hud' });
    hud.setAttribute('aria-hidden', 'true');
    ['tl', 'tr', 'bl', 'br'].forEach(function (c) { hud.appendChild(el('i', { className: c })); });
    hud.appendChild(el('span', { className: 'tag l', textContent: 'NODE-01 // BLACKROOM' }));
    hud.appendChild(el('span', { className: 'tag r', textContent: 'XYRON // PRIVATE NODE' }));
    document.body.appendChild(fx);
    document.body.appendChild(hud);
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function buildHeader() {
    var bar = document.getElementById('bar');
    if (!bar || document.getElementById('utc')) return;
    var utc = el('span', { id: 'utc' });
    var d = el('span', { className: 'd' });
    var t = el('span', { className: 't' });
    utc.appendChild(d);
    utc.appendChild(t);
    var btn = el('button', { id: 'fxbtn', type: 'button', textContent: 'FX', title: 'Switch the screen effects on or off' });
    btn.setAttribute('aria-pressed', fxOn() ? 'true' : 'false');
    var anchor = document.getElementById('adminlink') || document.getElementById('logout');
    bar.insertBefore(utc, anchor);
    bar.insertBefore(btn, anchor);
    function tick() {
      var now = new Date();
      d.textContent = pad(now.getUTCDate()) + ' ' + MONTHS[now.getUTCMonth()] + ' ' + now.getUTCFullYear();
      t.textContent = pad(now.getUTCHours()) + ':' + pad(now.getUTCMinutes()) + ':' + pad(now.getUTCSeconds()) + ' UTC';
    }
    tick();
    setInterval(tick, 1000);
    btn.addEventListener('click', function () { setFx(!fxOn()); });
  }

  // when a title changes it decodes from random characters, like a terminal unscrambling it
  function watchDecode(node) {
    if (!node) return;
    var current = node.textContent;
    var timer = null;
    var ob = new MutationObserver(function () {
      var text = node.textContent;
      if (text === current) return;
      current = text;
      if (!text || !fxOn()) return;
      if (timer) clearInterval(timer);
      var frames = 0;
      var total = Math.min(14, 6 + Math.round(text.length / 2));
      timer = setInterval(function () {
        frames++;
        var reveal = Math.floor((frames / total) * text.length);
        var out = '';
        for (var i = 0; i < text.length; i++) {
          out += (i < reveal || text.charAt(i) === ' ') ? text.charAt(i) : GLYPHS.charAt(Math.floor(Math.random() * GLYPHS.length));
        }
        node.textContent = frames >= total ? text : out;
        ob.takeRecords(); // our own writes are not new text
        if (frames >= total) { clearInterval(timer); timer = null; }
      }, 32 * speed);
    });
    ob.observe(node, { childList: true, characterData: true, subtree: true });
  }

  // error messages turn red
  function watchAlert(node) {
    if (!node) return;
    function check() {
      node.classList.toggle('alert', /unavailable|could not|cannot|failed|error/i.test(node.textContent || ''));
    }
    new MutationObserver(check).observe(node, { childList: true, characterData: true, subtree: true });
    check();
  }

  function typeHint() {
    var hint = document.getElementById('hint');
    if (!hint) return;
    var full = hint.textContent;
    if (!full || hint.classList.contains('alert')) return;
    hint.classList.add('typing');
    typeInto(hint, full, 18).then(function () {
      setTimeout(function () { hint.classList.remove('typing'); }, 2500 * speed);
    });
  }

  function buildTerminal() {
    var form = document.getElementById('f');
    var main = document.querySelector('main');
    if (!form || !main || document.getElementById('term')) return;
    var lines = /register/.test(location.pathname)
      ? ['XYRON ACCESS REQUEST', 'EVERY REQUEST IS REVIEWED BY THE OWNER', 'ENTER YOUR DETAILS']
      : ['XYRON ACCESS TERMINAL', 'AUTHORISED OPERATORS ONLY', 'IDENTIFY YOURSELF'];
    var pre = el('pre', { id: 'term' });
    form.parentNode.insertBefore(pre, form);
    (async function () {
      for (var i = 0; i < lines.length; i++) {
        var line = el('div', { className: 'caret' });
        pre.appendChild(line);
        await typeInto(line, '> ' + lines[i], 24);
        line.className = '';
        await sleep(160);
      }
      pre.lastChild.className = 'caret';
    })();
  }

  document.body.classList.toggle('fx-off', !fxWanted());
  buildOverlay();
  buildHeader();
  watchDecode(document.getElementById('pname'));
  watchAlert(document.getElementById('status'));
  watchAlert(document.getElementById('hint'));
  buildTerminal();
  if (document.getElementById('splash')) window.addEventListener('xyron-booted', typeHint, { once: true });
  else typeHint();
})();
