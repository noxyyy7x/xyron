const form = document.getElementById('f');
const msg = document.getElementById('msg');
function show(text, ok) { msg.textContent = text; msg.className = 'msg ' + (ok ? 'ok' : 'err'); }
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const pw = document.getElementById('pw1').value;
  if (pw.length < 14) { show('Use a password of at least 14 characters.', false); return; }
  if (pw !== document.getElementById('pw2').value) { show('The passwords do not match.', false); return; }
  try {
    const r = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: document.getElementById('email').value.trim(), password: pw }),
    });
    if (r.status === 202) {
      show('Check your inbox for a confirmation email. After you confirm it you will be shown your two-factor setup key, and your account then waits for approval.', true);
      form.reset();
    } else if (r.status === 429) {
      show('Too many attempts. Try again later.', false);
    } else {
      show('Please check the email address and password and try again.', false);
    }
  } catch (err) {
    show('Could not reach the server.', false);
  }
});
