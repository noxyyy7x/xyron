const msg = document.getElementById('msg');
const rows = document.getElementById('rows');
let me = null;

function show(text, ok) { msg.textContent = text; msg.className = 'msg ' + (ok ? 'ok' : 'err'); }

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } }, opts || {}));
  if (r.status === 401) { location.href = '/login'; throw new Error('redirect'); }
  if (r.status === 403) { location.href = '/'; throw new Error('redirect'); }
  if (!r.ok) {
    let d = 'Request failed';
    try { const j = await r.json(); if (typeof j.detail === 'string') d = j.detail; } catch (e) {}
    throw new Error(d);
  }
  return r.json();
}

function button(label, cls, onclick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'small ' + cls;
  b.textContent = label;
  b.addEventListener('click', onclick);
  return b;
}

function roleSelect(options, current) {
  const s = document.createElement('select');
  s.className = 'small';
  for (const o of options) {
    const opt = document.createElement('option');
    opt.value = o;
    opt.textContent = o;
    if (o === current) opt.selected = true;
    s.appendChild(opt);
  }
  return s;
}

async function act(path, body) {
  try {
    await api(path, { method: 'POST', body: JSON.stringify(body || {}) });
    show('Done.', true);
    await load();
  } catch (e) {
    if (e.message !== 'redirect') show(e.message, false);
  }
}

function render(users) {
  const isOwner = me.role === 'owner';
  const assignable = isOwner ? ['viewer', 'analyst', 'admin'] : ['viewer', 'analyst'];
  rows.replaceChildren();
  for (const u of users) {
    const tr = document.createElement('tr');
    const cells = [
      u.email, u.role, u.status, u.email_verified ? 'Yes' : 'No',
      u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '-',
    ];
    for (const c of cells) {
      const td = document.createElement('td');
      td.textContent = c;
      tr.appendChild(td);
    }
    const actions = document.createElement('td');
    const protectedRow = u.role === 'owner' || u.email === me.email || (u.role === 'admin' && !isOwner);
    if (protectedRow) {
      actions.textContent = '-';
    } else if (u.status === 'pending') {
      if (!u.email_verified) {
        actions.textContent = 'Waiting for email confirmation';
      } else {
        const sel = roleSelect(assignable, 'viewer');
        actions.appendChild(sel);
        actions.appendChild(button('Approve', '', () => act('/admin/users/' + u.id + '/approve', { role: sel.value })));
      }
    } else if (u.status === 'suspended') {
      actions.appendChild(button('Reactivate', '', () => act('/admin/users/' + u.id + '/reactivate')));
    } else {
      actions.appendChild(button('Suspend', 'danger', () => act('/admin/users/' + u.id + '/suspend')));
      if (isOwner) {
        const sel = roleSelect(assignable, u.role);
        actions.appendChild(sel);
        actions.appendChild(button('Set role', 'secondary', () => act('/admin/users/' + u.id + '/role', { role: sel.value })));
      }
    }
    tr.appendChild(actions);
    rows.appendChild(tr);
  }
}

async function load() {
  try {
    me = await api('/auth/me');
    render(await api('/admin/users'));
  } catch (e) {
    if (e.message !== 'redirect') show(e.message, false);
  }
}

document.getElementById('logout').addEventListener('click', async () => {
  await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' });
  location.href = '/login';
});

load();
