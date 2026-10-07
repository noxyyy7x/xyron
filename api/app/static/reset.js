// Forgot password: ask for a link, then (from the emailed link) choose a new password with an authenticator code or a recovery code.
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var params = new URLSearchParams(location.search);
  var token = params.get('token');
  if (token) { try { history.replaceState(null, '', '/reset'); } catch (e) { /* the address bar keeps the token: harmless */ } } // keep the link out of the history

  function say(el, text, ok) { el.textContent = text; el.className = 'msg ' + (ok ? 'ok' : 'err'); }
  function post(path, body) {
    return fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify(body) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { status: r.status, body: j }; }); });
  }
  function detail(res, fallback) { return typeof res.body.detail === 'string' ? res.body.detail : fallback; }

  if (!token) {
    $('ask').hidden = false;
    $('ask').addEventListener('submit', function (e) {
      e.preventDefault();
      var msg = $('msg1'); msg.className = 'msg';
      post('/auth/reset/request', { email: $('email').value.trim() }).then(function (res) {
        if (res.status === 202) say(msg, 'If that address has an account, a reset link has been sent. It works for one hour. You will need your authenticator app or a recovery code to finish.', true);
        else if (res.status === 429) say(msg, 'Too many attempts. Try again later.', false);
        else say(msg, 'Please check the email address.', false);
      }).catch(function () { say(msg, 'Could not reach the server.', false); });
    });
    return;
  }

  $('sub').textContent = 'Choose a new password';
  post('/auth/reset/check', { token: token }).then(function (res) {
    if (res.status === 200 && res.body.valid) {
      $('who').textContent = 'Resetting the password for ' + res.body.email;
      $('set').hidden = false;
    } else if (res.status === 429) {
      $('bad').hidden = false; $('bad').querySelector('.msg').textContent = 'Too many attempts. Try again later.';
    } else { $('bad').hidden = false; }
  }).catch(function () { $('bad').hidden = false; $('bad').querySelector('.msg').textContent = 'Could not reach the server.'; });

  $('set').addEventListener('submit', function (e) {
    e.preventDefault();
    var msg = $('msg2'); msg.className = 'msg';
    var p1 = $('pw1').value, p2 = $('pw2').value, code = $('code').value.trim();
    if (p1.length < 14) return say(msg, 'Use a password of at least 14 characters.', false);
    if (p1 !== p2) return say(msg, 'The passwords do not match.', false);
    post('/auth/reset/confirm', { token: token, new_password: p1, code: code }).then(function (res) {
      if (res.status === 200) { $('set').hidden = true; $('done').hidden = false; $('sub').textContent = 'Done'; return; }
      $('code').value = '';
      if (res.status === 429) say(msg, detail(res, 'Too many attempts. Request a new reset link.'), false);
      else if (res.status === 422) say(msg, 'Check the password (at least 14 characters) and the code.', false);
      else say(msg, detail(res, 'That did not work.'), false);
    }).catch(function () { say(msg, 'Could not reach the server.', false); });
  });
})();
