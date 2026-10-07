// Security: recovery codes, changing your password or authenticator app, and signing out other devices.
// Everything from the server is written with textContent, never as HTML. Secrets are cleared from the page as soon as they have been used.
(function () {
  'use strict';
  var bar = document.getElementById('bar');
  if (!bar) return;
  var NS = 'http://www.w3.org/2000/svg';
  var S = { open: false, data: null, codes: null, setup: null };

  function h(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; }
  function add(parent) { for (var i = 1; i < arguments.length; i++) if (arguments[i]) parent.appendChild(arguments[i]); return parent; }
  function svg(tag, attrs) { var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); return e; }
  function icon() {
    var s = svg('svg', { viewBox: '0 0 24 24', 'class': 'ico', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
    s.appendChild(svg('rect', { x: '5', y: '11', width: '14', height: '9', rx: '1' })); s.appendChild(svg('path', { d: 'M8 11V8a4 4 0 0 1 8 0v3' })); return s;
  }
  function send(method, path, body) {
    return fetch(path, { method: method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; throw new Error('auth'); }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) { var e = new Error(path); e.status = r.status; e.detail = typeof j.detail === 'string' ? j.detail : (r.status === 422 ? 'Check what you typed and try again.' : null); throw e; } return j; });
    });
  }
  function say(el, text, kind) { el.textContent = text || ''; el.className = 'sx-msg' + (kind ? ' ' + kind : ''); }
  function when(iso) { var d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString([], { day: 'numeric', month: 'short', year: 'numeric' }); }
  function field(label, type, auto, opts) {
    var inp = h('input'); inp.type = type; inp.autocomplete = auto; inp.required = true; opts = opts || {};
    if (opts.digits) { inp.inputMode = 'numeric'; inp.maxLength = 6; inp.pattern = '[0-9]{6}'; }
    if (opts.min) inp.minLength = opts.min;
    return { wrap: add(h('label', 'sx-field'), h('span', null, label), inp), input: inp };
  }
  function button(label, cls, onclick) { var b = h('button', 'sx-btn' + (cls ? ' ' + cls : ''), label); b.type = 'button'; if (onclick) b.addEventListener('click', onclick); return b; }

  // ---------- the header button ----------
  var btn = h('button', 'secbtn'); btn.id = 'secbtn'; btn.type = 'button'; btn.title = 'Security';
  add(btn, icon(), h('span', 'lbl', 'SECURITY'));
  var after = document.getElementById('alertbtn') || document.getElementById('searchbtn') || document.getElementById('mktbtn') || document.getElementById('hubbtn') || bar.querySelector('.brand');
  if (after && after.nextSibling) bar.insertBefore(btn, after.nextSibling); else bar.appendChild(btn);
  btn.addEventListener('click', function () { if (S.open) close(); else open(); });
  ['hubbtn', 'mktbtn', 'searchbtn', 'alertbtn'].forEach(function (id) { var b = document.getElementById(id); if (b) b.addEventListener('click', function () { if (S.open) close(); }); });

  var root = h('div'); root.id = 'security'; root.hidden = true; root.setAttribute('role', 'dialog'); root.setAttribute('aria-modal', 'true'); root.setAttribute('aria-label', 'Security');
  var head = h('div', 'sx-head'), title = h('div', 'sx-title'), closeBtn = h('button', 'sx-close', '\u00d7'); closeBtn.type = 'button'; closeBtn.setAttribute('aria-label', 'Close');
  add(title, icon(), h('span', null, 'SECURITY')); add(head, title, closeBtn);
  var body = h('div', 'sx-body'); add(root, head, body); document.body.appendChild(root);
  closeBtn.addEventListener('click', function () { close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && S.open) close(); });

  function open() {
    ['hub', 'mkt', 'alerts'].forEach(function (id) { var el = document.getElementById(id); if (el && !el.hidden) { var c = el.querySelector('.hub-close, .mk-close, .a-close'); if (c) c.click(); } });
    S.open = true; root.hidden = false; document.body.classList.add('security-open'); load(true);
  }
  function close() { S.open = false; root.hidden = true; document.body.classList.remove('security-open'); S.codes = null; S.setup = null; body.replaceChildren(); }

  function dot() {
    var has = btn.querySelector('.dot'), need = S.data && S.data.recovery.remaining === 0;
    if (need && !has) btn.appendChild(h('i', 'dot')); else if (!need && has) has.remove();
    btn.title = need ? 'Security: you have no recovery codes yet' : 'Security';
  }
  function load(render) {
    if (render) body.replaceChildren(h('p', 'sx-note', 'Loading\u2026'));
    return fetch('/account/security', { credentials: 'same-origin' }).then(function (r) { if (!r.ok) throw new Error('x'); return r.json(); }).then(function (d) { S.data = d; dot(); if (render && S.open) build(); })
      .catch(function () { if (render && S.open) body.replaceChildren(h('p', 'sx-note err', 'Security settings are unavailable right now.')); });
  }
  setTimeout(function () { if (!document.getElementById('login')) load(false); }, 1500); // a quiet check, so the button can show a dot when you have no recovery codes

  // ---------- the cards ----------
  function card(t, blurb) { var c = h('section', 'sx-card'); add(c, h('h3', null, t)); if (blurb) c.appendChild(h('p', 'sx-blurb', blurb)); return c; }
  function build() {
    var d = S.data; body.replaceChildren();
    add(body, accountCard(d), codesCard(d), passwordCard(), authenticatorCard(d), devicesCard());
  }
  function accountCard(d) {
    var c = card('YOUR ACCOUNT');
    add(c, h('p', 'sx-line', d.email + ' \u00b7 ' + d.role), h('p', 'sx-blurb', d.password_changed_at ? 'Password last changed on ' + when(d.password_changed_at) + '.' : 'The password has not been changed here yet.'),
      h('p', 'sx-blurb', d.telegram ? 'Security notices reach you by email and Telegram.' : 'Security notices reach you by email. Connect Telegram under ALERTS to get them instantly there too.'));
    return c;
  }

  // ----- recovery codes -----
  function codesCard(d) {
    var c = card('RECOVERY CODES', 'If you lose your phone, a recovery code lets you sign in or reset your password. Each code works once. Keep them somewhere safe, not only on the same phone.');
    var left = d.recovery.remaining, status = h('p', 'sx-status ' + (left === 0 ? 'bad' : left <= 3 ? 'warn' : 'ok'));
    status.textContent = left === 0 ? 'You have no recovery codes. If you lose your phone, only the owner can get you back in.' : left + ' of ' + d.recovery.size + ' unused' + (left <= 3 ? '. Create new ones soon.' : '.');
    var holder = h('div'), msg = h('div', 'sx-msg');
    add(c, status, holder, msg);
    var go = button(left ? 'CREATE NEW CODES' : 'CREATE RECOVERY CODES', 'primary', function () { go.hidden = true; holder.appendChild(codeForm(function (res) { showCodes(c, holder, res.codes); }, msg)); });
    c.insertBefore(go, holder);
    return c;
  }
  function codeForm(done, msg) {
    var f = h('form', 'sx-form'), pw = field('Your password', 'password', 'current-password'), cd = field('Authenticator code', 'text', 'one-time-code', { digits: true });
    var go = h('button', 'sx-btn primary', 'CREATE'); go.type = 'submit';
    add(f, h('p', 'sx-blurb', 'New codes replace all your old ones, which stop working.'), pw.wrap, cd.wrap, go);
    f.addEventListener('submit', function (e) {
      e.preventDefault(); go.disabled = true; say(msg, 'Creating\u2026');
      send('POST', '/account/recovery-codes', { password: pw.input.value, code: cd.input.value.trim() }).then(function (res) { pw.input.value = cd.input.value = ''; say(msg, ''); f.remove(); done(res); })
        .catch(function (err) { go.disabled = false; cd.input.value = ''; say(msg, err.detail || 'That did not work.', 'err'); });
    });
    return f;
  }
  function showCodes(c, holder, codes) {
    S.codes = codes.slice();
    var box = h('div', 'sx-codes'), grid = h('div', 'sx-grid');
    codes.forEach(function (x) { grid.appendChild(h('code', null, x)); });
    var note = h('p', 'sx-status warn', 'Save these now. They are shown only once.');
    var copy = button('COPY', '', function () {
      var text = S.codes.join('\n');
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { copy.textContent = 'COPIED'; }, function () { copy.textContent = 'SELECT AND COPY'; });
      else { copy.textContent = 'SELECT AND COPY'; var r = document.createRange(); r.selectNodeContents(grid); var s = window.getSelection(); if (s) { s.removeAllRanges(); s.addRange(r); } }
    });
    var dl = h('a', 'sx-btn', 'DOWNLOAD'); dl.download = 'xyron-recovery-codes.txt'; dl.href = 'data:text/plain;charset=utf-8,' + encodeURIComponent('XYRON recovery codes\nEach works once.\n\n' + codes.join('\n') + '\n');
    var saved = h('input'); saved.type = 'checkbox'; saved.id = 'sx-saved';
    var fin = button('DONE', 'primary'); fin.disabled = true;
    saved.addEventListener('change', function () { fin.disabled = !saved.checked; });
    fin.addEventListener('click', function () { S.codes = null; load(true); });
    add(box, note, grid, add(h('div', 'sx-row'), copy, dl), add(h('label', 'sx-check'), saved, h('span', null, 'I have saved these codes somewhere safe')), fin);
    holder.appendChild(box);
  }

  // ----- change password -----
  function passwordCard() {
    var c = card('CHANGE PASSWORD', 'You will stay signed in here; your other devices are signed out.');
    var f = h('form', 'sx-form'), cur = field('Current password', 'password', 'current-password'), cd = field('Authenticator code', 'text', 'one-time-code', { digits: true });
    var n1 = field('New password (at least 14 characters)', 'password', 'new-password', { min: 14 }), n2 = field('Repeat the new password', 'password', 'new-password', { min: 14 });
    var go = h('button', 'sx-btn primary', 'CHANGE PASSWORD'), msg = h('div', 'sx-msg'); go.type = 'submit';
    add(f, cur.wrap, cd.wrap, n1.wrap, n2.wrap, go); add(c, f, msg);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (n1.input.value.length < 14) return say(msg, 'Use a password of at least 14 characters.', 'err');
      if (n1.input.value !== n2.input.value) return say(msg, 'The new passwords do not match.', 'err');
      go.disabled = true; say(msg, 'Saving\u2026');
      send('POST', '/account/password', { password: cur.input.value, code: cd.input.value.trim(), new_password: n1.input.value }).then(function () {
        cur.input.value = cd.input.value = n1.input.value = n2.input.value = ''; go.disabled = false; say(msg, 'Password changed. Your other devices were signed out.', 'ok'); load(false);
      }).catch(function (err) { go.disabled = false; cd.input.value = ''; say(msg, err.detail || 'That did not work.', 'err'); });
    });
    return c;
  }

  // ----- change authenticator -----
  function authenticatorCard(d) {
    var c = card('AUTHENTICATOR APP', 'Moving to a new phone? Add the new key to your authenticator app, confirm it with a code, and the old one stops working.');
    var holder = h('div'), msg = h('div', 'sx-msg');
    var start = button('CHANGE AUTHENTICATOR', '', function () { start.hidden = true; holder.appendChild(startForm()); });
    function startForm() {
      var f = h('form', 'sx-form'), pw = field('Your password', 'password', 'current-password'), cd = field('Current authenticator code', 'text', 'one-time-code', { digits: true });
      var go = h('button', 'sx-btn primary', 'CONTINUE'); go.type = 'submit'; add(f, pw.wrap, cd.wrap, go);
      f.addEventListener('submit', function (e) {
        e.preventDefault(); go.disabled = true; say(msg, 'Working\u2026');
        send('POST', '/account/authenticator/start', { password: pw.input.value, code: cd.input.value.trim() }).then(function (res) { pw.input.value = cd.input.value = ''; say(msg, ''); f.remove(); holder.appendChild(confirmBox(res)); })
          .catch(function (err) { go.disabled = false; cd.input.value = ''; say(msg, err.detail || 'That did not work.', 'err'); });
      });
      return f;
    }
    function confirmBox(res) {
      S.setup = res.secret;
      var box = h('div', 'sx-codes'), key = h('code', 'sx-key', res.secret.replace(/(.{4})/g, '$1 ').trim());
      var open = h('a', 'sx-btn', 'OPEN IN AUTHENTICATOR APP'); open.href = res.uri;
      var f = h('form', 'sx-form'), cd = field('First code from the new app', 'text', 'one-time-code', { digits: true }); var go = h('button', 'sx-btn primary', 'CONFIRM'); go.type = 'submit';
      var cancel = button('CANCEL', '', function () { send('POST', '/account/authenticator/cancel').catch(function () { /* nothing to undo */ }); S.setup = null; box.remove(); start.hidden = false; say(msg, ''); });
      add(f, cd.wrap, add(h('div', 'sx-row'), go, cancel));
      add(box, h('p', 'sx-blurb', 'In your authenticator app choose \u201center a setup key\u201d and add this key for ' + res.account + ':'), key, add(h('div', 'sx-row'), open), f);
      f.addEventListener('submit', function (e) {
        e.preventDefault(); go.disabled = true;
        send('POST', '/account/authenticator/confirm', { code: cd.input.value.trim() }).then(function () { S.setup = null; box.remove(); start.hidden = false; say(msg, 'Done. Your new authenticator app is now the one that works. Your other devices were signed out.', 'ok'); load(false); })
          .catch(function (err) { go.disabled = false; cd.input.value = ''; say(msg, err.detail || 'That did not work.', 'err'); });
      });
      return box;
    }
    add(c, d.totp_pending ? h('p', 'sx-status warn', 'A change was started earlier and not finished. Start again to continue.') : null, start, holder, msg);
    return c;
  }

  // ----- other devices -----
  function devicesCard() {
    var c = card('OTHER DEVICES', 'Signs out every other browser and device. You stay signed in here.');
    var msg = h('div', 'sx-msg'), b = button('SIGN OUT OTHER DEVICES', '', function () {
      b.disabled = true;
      send('POST', '/account/sessions/revoke').then(function () { b.disabled = false; say(msg, 'Done. Every other device was signed out.', 'ok'); }).catch(function (err) { b.disabled = false; say(msg, err.detail || 'That did not work.', 'err'); });
    });
    add(c, b, msg); return c;
  }
})();
