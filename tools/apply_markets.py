import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
api = root / "api"
app = api / "app"
static = app / "static"

for rel in ("markets.py", "markets_data.py", "static/hub/markets.js", "static/hub/markets.css"):
    if not (app / rel).exists():
        sys.exit(f"STOPPED, nothing changed. {rel} is missing. Unpack xyron-markets.zip into ~/xyron first.")
if "markets.router" in (app / "main.py").read_text():
    sys.exit("STOPPED, nothing changed. This patch has already been applied.")

MARKET_STYLE = r'''const marketState = (e) => (e.detail && e.detail.state) || 'closed';
const marketChange = (e) => (e.detail && typeof e.detail.change_pct === 'number' ? e.detail.change_pct : 0);
const marketStyle = {
  pulse: (e) => (marketState(e) === 'open' ? 1 : 0),
  color: (e) => {
    const chg = marketChange(e);
    const k = marketState(e) === 'open' ? 1 : marketState(e) === 'closed' ? 0.4 : 0.7;
    const base = chg >= 0.005 ? [0.18, 0.9, 0.48] : chg <= -0.005 ? [1.0, 0.17, 0.24] : [1.0, 0.37, 0.82];
    return [base[0] * k, base[1] * k, base[2] * k];
  },
  size: (e) => 0.03 + Math.min(Math.abs(marketChange(e)), 3) * 0.008 + (marketState(e) === 'open' ? 0.01 : 0),
  rank: (e) => Math.abs(marketChange(e)) + (marketState(e) === 'open' ? 100 : 0),
  tip: (e) => [e.title, String(e.detail.state || '').toUpperCase() + (e.detail.label ? ' \u00b7 ' + e.detail.label : '')],
  rows: (e) => {
    const d = e.detail;
    return [
      ['Exchange', d.exchange],
      ['City', d.city + ', ' + d.country],
      ['Index', d.index],
      typeof d.level === 'number' ? ['Level', d.level.toLocaleString(undefined, { maximumFractionDigits: 2 }) + (d.currency ? ' ' + d.currency : '')] : null,
      typeof d.change_pct === 'number' ? ['Today', (d.change_pct >= 0 ? '+' : '') + d.change_pct.toFixed(2) + '%'] : null,
      ['Status', String(d.state || '').toUpperCase() + (d.label ? ' \u00b7 ' + d.label : '')],
      ['Local time', d.local_time],
      ['Hours', d.hours],
    ];
  },
  links: () => [],
  source: {
    name: 'Index levels from Yahoo Finance, which can run 10 to 15 minutes behind. Opening hours follow the normal timetable; public holidays are not listed.',
    linkLabel: 'Yahoo Finance',
    prefix: 'about:none',
  },
  summary: (n) => 'Markets \u00b7 ' + n + ' exchanges',
};

export const STYLE = {
  football: matchStyle(true),
  sports: matchStyle(false),
  markets: marketStyle,
'''

edits = {
    app / "main.py": [
        ("from . import accounts, aviation, events, football, news, pages, sports, weather\n",
         "from . import accounts, aviation, events, football, markets, news, pages, sports, weather\n"),
        ("        asyncio.create_task(sports.ingest_loop()),\n    ]\n",
         "        asyncio.create_task(sports.ingest_loop()),\n        asyncio.create_task(markets.ingest_loop()),\n    ]\n"),
        ("app.include_router(football.router)\n", "app.include_router(football.router)\napp.include_router(markets.router)\n"),
    ],
    app / "events.py": [
        ('{"id": "football", "label": "Football", "live": True},\n',
         '{"id": "football", "label": "Football", "live": True},\n    {"id": "markets", "label": "Markets", "live": True},\n'),
    ],
    static / "globe.html": [
        ('<link rel="stylesheet" href="/static/hub/football.css">\n',
         '<link rel="stylesheet" href="/static/hub/football.css">\n<link rel="stylesheet" href="/static/hub/markets.css">\n'),
        ('<script src="/static/hub/football.js" defer></script>\n',
         '<script src="/static/hub/football.js" defer></script>\n<script src="/static/hub/markets.js" defer></script>\n'),
    ],
    static / "layers.js": [
        ("  earthquakes: '#ff5a36', weather: '#36d6e7', news: '#a5c8ff', politics: '#b07cff', sports: '#ffc83d', football: '#2ee57a',\n};\n",
         "  earthquakes: '#ff5a36', weather: '#36d6e7', news: '#a5c8ff', politics: '#b07cff', sports: '#ffc83d', football: '#2ee57a', markets: '#ff5fd2',\n};\n"),
        ("const CHIP_ICONS = {\n", "const CHIP_ICONS = {\n  markets: { d: ['M3 17l6-6 4 4 8-8', 'M15 7h6v6'] },\n"),
        ("export const STYLE = {\n  football: matchStyle(true),\n  sports: matchStyle(false),\n", MARKET_STYLE),
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

# time zone data for the exchange clocks, in case the container has none
req = api / "requirements.txt"
if req.exists() and not any(line.strip().lower().startswith("tzdata") for line in req.read_text().splitlines()):
    body = req.read_text()
    new_text[req] = body + ("" if body.endswith("\n") else "\n") + "tzdata\n"

for path, text in new_text.items():
    path.write_text(text)
    print("patched", path.name if path.name != "requirements.txt" else "requirements.txt (added tzdata)")
