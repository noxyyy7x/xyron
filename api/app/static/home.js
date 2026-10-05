(async () => {
  const r = await fetch('/auth/me', { credentials: 'same-origin' });
  if (r.status === 401) { location.href = '/login'; return; }
  if (!r.ok) { document.getElementById('who').textContent = 'Something went wrong.'; return; }
  const me = await r.json();
  document.getElementById('who').textContent = me.email + ' \u00b7 ' + me.role;
  if (me.role === 'owner' || me.role === 'admin') {
    const a = document.createElement('a');
    a.href = '/admin';
    a.textContent = 'Open admin';
    document.getElementById('links').appendChild(a);
  }
})();
document.getElementById('logout').addEventListener('click', async () => {
  await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' });
  location.href = '/login';
});
