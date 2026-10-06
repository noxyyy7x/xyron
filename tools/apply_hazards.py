import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"

if not (app / "hazards.py").exists() or "def ships_status" not in (app / "ships.py").read_text():
    sys.exit("STOPPED, nothing changed. Unpack xyron-hazards.zip into ~/xyron first (it adds hazards.py and updates ships.py).")
if "hazards.ingest_loop" in (app / "main.py").read_text():
    sys.exit("STOPPED, nothing changed. This patch has already been applied.")

HAZARD_STYLE = r'''const HAZARD_COLORS = {
  wildfires: [1.0, 0.45, 0.1], severeStorms: [0.55, 0.75, 1.0], volcanoes: [1.0, 0.2, 0.2], floods: [0.2, 0.55, 1.0], landslides: [0.7, 0.5, 0.3],
  drought: [0.9, 0.75, 0.3], dustHaze: [0.85, 0.7, 0.5], seaLakeIce: [0.8, 0.95, 1.0], snow: [0.92, 0.96, 1.0], tempExtremes: [1.0, 0.5, 0.75],
  waterColor: [0.3, 0.85, 0.7], manmade: [0.75, 0.75, 0.8],
};
const hazardHours = (e) => {
  const t = e.detail && e.detail.date ? Date.parse(e.detail.date) : NaN;
  return isNaN(t) ? null : Math.max(0, Math.round((Date.now() - t) / 3600000));
};
const hazardAgo = (h) => (h === null ? '' : h < 48 ? h + ' h ago' : Math.round(h / 24) + ' days ago');
const hazardStyle = {
  pulse: (e) => (e.value >= 3 ? 1 : 0),
  color: (e) => HAZARD_COLORS[e.detail.category] || [0.9, 0.9, 0.9],
  size: (e) => 0.026 + Math.min(e.value || 1, 3) * 0.006,
  rank: (e) => (e.value || 1) * 1000 - (hazardHours(e) || 0),
  tip: (e) => [e.title, e.detail.category_label + (hazardHours(e) !== null ? ' \u00b7 reported ' + hazardAgo(hazardHours(e)) : '')],
  rows: (e) => {
    const d = e.detail;
    const h = hazardHours(e);
    return [
      ['Kind', d.category_label],
      ['Status', 'Open, still active'],
      d.date ? ['Last reported', new Date(d.date).toLocaleString() + (h !== null ? ' (' + hazardAgo(h) + ')' : '')] : null,
      typeof d.magnitude === 'number' ? ['Size or strength', d.magnitude.toLocaleString() + (d.unit ? ' ' + d.unit : '')] : null,
      d.description ? ['Notes', d.description] : null,
      d.points > 1 ? ['Reports so far', String(d.points)] : null,
    ];
  },
  links: (e) => (e.detail.sources || [])
    .filter((s) => typeof s.url === 'string' && s.url.startsWith('https://'))
    .map((s) => { try { return { text: s.id || 'Report', url: s.url, domain: new URL(s.url).hostname }; } catch (err) { return null; } })
    .filter(Boolean),
  source: {
    name: 'Natural events from NASA EONET (eonet.gsfc.nasa.gov), a curated list of events reported by agencies such as CAL FIRE, USGS, NOAA and the Smithsonian. It is for awareness, not an emergency warning service.',
    linkLabel: 'NASA EONET',
    prefix: 'about:none',
  },
  summary: (n) => 'Hazards \u00b7 ' + n + ' active natural events (NASA EONET)',
};

export const STYLE = {
  football: matchStyle(true),
  sports: matchStyle(false),
  markets: marketStyle,
  hazards: hazardStyle,
'''

edits = {
    app / "main.py": [
        ("from . import accounts, aviation, events, football, markets, news, pages, ships, sports, weather\n",
         "from . import accounts, aviation, events, football, hazards, markets, news, pages, ships, sports, weather\n"),
        ("        asyncio.create_task(ships.ingest_loop()),\n    ]\n",
         "        asyncio.create_task(ships.ingest_loop()),\n        asyncio.create_task(hazards.ingest_loop()),\n    ]\n"),
    ],
    app / "events.py": [
        ('{"id": "ships", "label": "Ships", "live": True},\n',
         '{"id": "ships", "label": "Ships", "live": True},\n    {"id": "hazards", "label": "Hazards", "live": True},\n'),
        ('        if st.get("count") is not None:\n            item["count"] = st["count"]\n        out.append(item)\n',
         '        if st.get("count") is not None:\n            item["count"] = st["count"]\n'
         '        if st.get("error"):\n            item["error"] = str(st["error"])[:120]\n        out.append(item)\n'),
    ],
    static / "layers.js": [
        ("football: '#2ee57a', markets: '#ff5fd2', ships: '#4f7cff',\n};\n", "football: '#2ee57a', markets: '#ff5fd2', ships: '#4f7cff', hazards: '#b8e62e',\n};\n"),
        ("  ships: { d: ['M3 16h18l-2.5 4h-13z', 'M6 16v-5h12v5', 'M12 11V6', 'M9 6h6'] },\n",
         "  ships: { d: ['M3 16h18l-2.5 4h-13z', 'M6 16v-5h12v5', 'M12 11V6', 'M9 6h6'] },\n"
         "  hazards: { d: ['M12 2c1.2 3.2 5 5.4 5 10a5 5 0 0 1-10 0c0-2 .9-3.4 2-4.6.2 1.2.9 2 1.8 2.4C10.5 7 11 4.5 12 2z'] },\n"),
        ("export const STYLE = {\n  football: matchStyle(true),\n  sports: matchStyle(false),\n  markets: marketStyle,\n", HAZARD_STYLE),
        ("    summary: (n, l) => 'Ships \\u00b7 ' + ((l && l.count) || 0).toLocaleString() + ' vessels (AISstream)',\n",
         "    summary: (n, l) => 'Ships \\u00b7 ' + (l && l.count ? l.count.toLocaleString() + ' vessels (AISstream)' : l && l.error ? 'AISstream problem: ' + l.error : 'waiting for AISstream\\u2026'),\n"),
    ],
}

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
