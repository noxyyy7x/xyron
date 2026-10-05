const form = document.getElementById('f');
const msg = document.getElementById('msg');
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  msg.className = 'msg';
  const body = {
    email: document.getElementById('email').value.trim(),
    password: document.getElementById('password').value,
    code: document.getElementById('code').value.trim(),
  };
  try {
    const r = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body),
    });
    if (r.ok) { location.href = '/'; return; }
    msg.textContent = r.status === 429 ? 'Too many attempts. Try again later.' : 'Invalid credentials.';
  } catch (err) {
    msg.textContent = 'Could not reach the server.';
  }
  msg.className = 'msg err';
  document.getElementById('password').value = '';
  document.getElementById('code').value = '';
});
