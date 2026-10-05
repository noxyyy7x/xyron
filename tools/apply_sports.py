import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"

MATCH_STYLE = r'''const SPORT_COLORS = {
  football: [0.25, 1.0, 0.55], basketball: [1.0, 0.62, 0.2], 'american-football': [0.85, 0.6, 0.35],
  baseball: [1.0, 0.4, 0.4], hockey: [0.6, 0.85, 1.0], f1: [1.0, 0.25, 0.25], mma: [0.82, 0.45, 1.0],
  rugby: [0.6, 0.9, 0.4], volleyball: [1.0, 0.85, 0.3],
};
const matchState = (e) => (e.detail && e.detail.state) || 'pre';
const matchStyle = (isFootball) => ({
  pulse: (e) => (matchState(e) === 'in' ? 1 : 0),
  color: (e) => {
    const base = SPORT_COLORS[e.detail.sport] || [0.8, 0.9, 1.0];
    const k = matchState(e) === 'in' ? 1 : matchState(e) === 'pre' ? 0.75 : 0.45;
    return [base[0] * k, base[1] * k, base[2] * k];
  },
  size: (e) => (isFootball ? 1.25 : 1) * (matchState(e) === 'in' ? 0.055 : matchState(e) === 'pre' ? 0.032 : 0.026),
  rank: (e) => (matchState(e) === 'in' ? 2e12 : 1e12) - Math.abs(e.time - Date.now()),
  tip: (e) => [e.title, [e.detail.league, e.detail.status].filter(Boolean).join(' \u00b7 ')],
  rows: (e) => {
    const d = e.detail;
    return [
      ['Match', e.title],
      ['Status', d.status || (matchState(e) === 'in' ? 'Live' : matchState(e) === 'post' ? 'Finished' : 'Scheduled')],
      d.league ? ['Competition', d.league] : null,
      d.sport_label ? ['Sport', d.sport_label] : null,
      Array.isArray(d.competitors) && d.competitors.length ? ['Competitors', d.competitors.map((c) => c.name).join(', ')] : null,
      ['Start', new Date(e.time).toLocaleString()],
      d.venue ? ['Venue', d.venue + (d.city ? ', ' + d.city : '')] : null,
    ];
  },
  links: (e) => (typeof e.url === 'string' && e.url.startsWith('https://www.espn.com/')
    ? [{ text: 'Match page on ESPN', url: e.url, domain: 'espn.com' }] : []),
  source: {
    name: 'Scores from ESPN public scoreboards (an unofficial feed). The map position is the venue city, so it is approximate.',
    linkLabel: 'ESPN',
    prefix: 'about:none',
  },
  summary: (n) => (isFootball ? 'Football \u00b7 ' + n + ' matches' : 'Sports \u00b7 ' + n + ' games') + ' (ESPN)',
});

export const STYLE = {
  football: matchStyle(true),
  sports: matchStyle(false),
'''

HELPERS = r'''const SPORTS_OFF_KEY = 'xyron.sportsoff';
function loadSportsOff() {
  try {
    const v = JSON.parse(localStorage.getItem(SPORTS_OFF_KEY));
    if (Array.isArray(v)) return new Set(v.filter((x) => typeof x === 'string'));
  } catch (e) { /* storage unavailable */ }
  return new Set();
}
function saveSportsOff(set) {
  try { localStorage.setItem(SPORTS_OFF_KEY, JSON.stringify([...set])); } catch (e) { /* ignore */ }
}
// is this event switched on? (layers are chips; the sports layer also has one chip per sport)
export function eventVisible(e, enabled, sportsOff) {
  if (!enabled.has(e.layer)) return false;
  return !(e.layer === 'sports' && e.detail && sportsOff.has(e.detail.sport));
}
// the sports present in the data, biggest first, for the sport chips
export function sportList(events) {
  const m = new Map();
  for (const e of events) {
    if (e.layer !== 'sports' || !e.detail || !e.detail.sport) continue;
    const cur = m.get(e.detail.sport) || { id: e.detail.sport, label: e.detail.sport_label || e.detail.sport, n: 0, live: 0 };
    cur.n += 1;
    if (e.detail.state === 'in') cur.live += 1;
    m.set(e.detail.sport, cur);
  }
  return [...m.values()].sort((a, b) => b.live - a.live || b.n - a.n);
}

export function init(ctx) {
'''

SPORT_ROW = r'''  const enabled = loadEnabled();
  const sportsOff = loadSportsOff();
  const sportRow = document.createElement('div');
  sportRow.id = 'sportchips';
  sportRow.hidden = true;
  chipsEl.after(sportRow);
'''

SPORT_FN = r'''  function renderSportChips() {
    sportRow.replaceChildren();
    const list = sportList(events);
    sportRow.hidden = !(enabled.has('sports') && list.length);
    for (const s of list) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'chip small' + (sportsOff.has(s.id) ? '' : ' on');
      b.append(s.label);
      const c = document.createElement('small');
      c.textContent = (s.live ? s.live + ' live \u00b7 ' : '') + s.n;
      b.append(c);
      b.addEventListener('click', () => {
        if (sportsOff.has(s.id)) sportsOff.delete(s.id); else sportsOff.add(s.id);
        saveSportsOff(sportsOff);
        renderSportChips();
        rebuildMarkers();
        renderList();
        hideTip();
      });
      sportRow.appendChild(b);
    }
  }

  function renderStatus() {
'''

edits = {
    app / "events.py": [
        ('{"id": "sports", "label": "Sports", "live": False},', '{"id": "sports", "label": "Sports", "live": True},'),
        ('{"id": "football", "label": "Football", "live": False},', '{"id": "football", "label": "Football", "live": True},'),
    ],
    app / "main.py": [
        ("from . import accounts, aviation, events, news, pages, weather\n",
         "from . import accounts, aviation, events, news, pages, sports, weather\n"),
        ("        asyncio.create_task(news.ingest_loop()),\n    ]\n",
         "        asyncio.create_task(news.ingest_loop()),\n        asyncio.create_task(sports.ingest_loop()),\n    ]\n"),
        ("app.include_router(news.router)\n", "app.include_router(news.router)\napp.include_router(sports.router)\n"),
    ],
    static / "layers.js": [
        ("export const STYLE = {\n", MATCH_STYLE),
        ("export function init(ctx) {\n", HELPERS),
        ("  const enabled = loadEnabled();\n", SPORT_ROW),
        ("    shown = events.filter((e) => enabled.has(e.layer));\n",
         "    shown = events.filter((e) => eventVisible(e, enabled, sportsOff));\n"),
        ("        .filter((e) => e.layer === l.id && e.country === selected)\n",
         "        .filter((e) => e.layer === l.id && e.country === selected && eventVisible(e, enabled, sportsOff))\n"),
        ("          country: nearestCountry(r.lat, r.lon), pulse: st.pulse,\n        };\n        e.size = st.size(e);\n",
         "          country: nearestCountry(r.lat, r.lon), pulse: 0,\n        };\n        e.pulse = typeof st.pulse === 'function' ? st.pulse(e) : st.pulse;\n        e.size = st.size(e);\n"),
        ("      b.className = 'chip' + (l.live && enabled.has(l.id) ? ' on' : '');\n",
         "      b.className = 'chip' + (l.live && enabled.has(l.id) ? ' on' : '') + (l.id === 'football' ? ' football' : '');\n"),
        ("      b.append(l.label);\n", "      b.append((l.id === 'football' ? '\\u26bd ' : '') + l.label);\n"),
        ("  function renderStatus() {\n", SPORT_FN),
        ("      renderChips();\n      rebuildMarkers();\n      renderList();\n      renderStatus();\n      broadcast();\n",
         "      renderChips();\n      renderSportChips();\n      rebuildMarkers();\n      renderList();\n      renderStatus();\n      broadcast();\n"),
        ("          renderChips();\n          rebuildMarkers();\n          renderList();\n          renderStatus();\n          hideTip();\n",
         "          renderChips();\n          renderSportChips();\n          rebuildMarkers();\n          renderList();\n          renderStatus();\n          hideTip();\n"),
    ],
}

# check everything first, so a mismatch changes nothing
new_text = {}
for path, pairs in edits.items():
    text = path.read_text()
    for old, new in pairs:
        if text.count(old) != 1:
            sys.exit(f"STOPPED, nothing changed. Could not find exactly one match in {path.name} for:\n{old[:200]!r}")
        text = text.replace(old, new)
    new_text[path] = text
for path, text in new_text.items():
    path.write_text(text)
    print("patched", path.name)
