// Adds two things to the sign-in page: a "Forgot your password?" link, and a way to sign in with a recovery code instead of the authenticator code.
(function () {
  'use strict';
  var form = document.getElementById('f'), code = document.getElementById('code'), msg = document.getElementById('msg');
  if (!form || !code) return;
  var label = form.querySelector('label[for="code"]');
  var original = { label: label ? label.textContent : '', pattern: code.getAttribute('pattern'), max: code.getAttribute('maxlength'), mode: code.getAttribute('inputmode'), auto: code.getAttribute('autocomplete') };
  var recovery = false;

  var toggle = document.createElement('a'); toggle.href = '#'; toggle.id = 'use-recovery'; toggle.setAttribute('role', 'button'); toggle.textContent = 'Lost your phone? Use a recovery code';
  var row = document.createElement('p'); row.className = 'sub'; row.style.margin = '14px 0 0'; row.appendChild(toggle);
  form.insertBefore(row, msg);
  var forgot = document.createElement('p'); forgot.className = 'sub'; forgot.style.margin = '6px 0 0';
  var fa = document.createElement('a'); fa.href = '/reset'; fa.id = 'forgot'; fa.textContent = 'Forgot your password?'; forgot.appendChild(fa);
  form.insertBefore(forgot, msg);

  toggle.addEventListener('click', function (e) {
    e.preventDefault();
    recovery = !recovery;
    if (recovery) {
      code.removeAttribute('pattern'); code.setAttribute('maxlength', '32'); code.setAttribute('inputmode', 'text'); code.setAttribute('autocomplete', 'off'); code.placeholder = 'abcde-fghjk';
      if (label) label.textContent = 'Recovery code';
      toggle.textContent = 'Use my authenticator app instead';
    } else {
      if (original.pattern) code.setAttribute('pattern', original.pattern);
      code.setAttribute('maxlength', original.max || '6'); if (original.mode) code.setAttribute('inputmode', original.mode); if (original.auto) code.setAttribute('autocomplete', original.auto); code.placeholder = '';
      if (label) label.textContent = original.label;
      toggle.textContent = 'Lost your phone? Use a recovery code';
    }
    code.value = ''; code.focus();
  });

  // This listener is added before the page's own, so in recovery mode it takes over the submit.
  form.addEventListener('submit', function (e) {
    if (!recovery) return;
    e.preventDefault(); e.stopImmediatePropagation();
    msg.className = 'msg';
    var body = { email: document.getElementById('email').value.trim(), password: document.getElementById('password').value, recovery_code: code.value.trim() };
    fetch('/auth/login-recovery', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify(body) })
      .then(function (r) {
        if (r.ok) { location.href = '/'; return; }
        msg.textContent = r.status === 429 ? 'Too many attempts. Try again later.' : 'Invalid credentials.';
        msg.className = 'msg err'; document.getElementById('password').value = ''; code.value = '';
      }).catch(function () { msg.textContent = 'Could not reach the server.'; msg.className = 'msg err'; });
  });
})();
