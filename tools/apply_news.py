import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"

STYLE_NEW = r'''const placeStyle = (color, summaryLabel) => ({
  pulse: 0,
  color: () => color,
  size: (e) => Math.min(0.085, 0.018 + 0.017 * Math.log10(Math.max(1, e.value))),
  rank: (e) => e.value,
  tip: (e) => {
    const a = (e.detail.articles || [])[0];
    return [
      e.detail.place || e.title,
      Math.round(e.value).toLocaleString() + ' mentions in 24 h' + (a ? ' \u00b7 ' + a.title.slice(0, 70) + (a.title.length > 70 ? '\u2026' : '') : ''),
    ];
  },
  rows: (e) => [
    ['Location', e.detail.place || e.title],
    ['Mentions in the last 24 hours', Math.round(e.value).toLocaleString()],
    ['Updated', ago(e.time)],
  ],
  links: (e) => (e.detail.articles || [])
    .filter((a) => /^https?:\/\//.test(a.url))
    .map((a) => ({ text: a.title, url: a.url, domain: a.domain })),
  source: {
    name: 'Coverage mapped by the GDELT Project (gdeltproject.org). A location is where GDELT placed a mention in the news, not necessarily where something happened.',
    linkLabel: 'GDELT Project',
    prefix: 'https://www.gdeltproject.org/',
  },
  summary: (n) => summaryLabel + ' \u00b7 ' + n + ' places (GDELT)',
});

export const STYLE = {
  news: placeStyle([0.8, 0.92, 1.0], 'News'),
  politics: placeStyle([0.85, 0.5, 1.0], 'Politics'),
'''

SHOW_OLD = r'''    listEl.replaceChildren();
    evTitleEl.hidden = !st.source;
    if (st.source) {
      evTitleEl.textContent = 'Source';
'''
SHOW_NEW = r'''    listEl.replaceChildren();
    const links = st.links ? st.links(e) : [];
    evTitleEl.hidden = !(st.source || links.length);
    for (const l of links) {
      const row = document.createElement('div');
      row.className = 'ev';
      const a = document.createElement('a');
      a.href = l.url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = l.text;
      row.appendChild(a);
      if (l.domain) {
        const d = document.createElement('div');
        d.className = 'when';
        d.textContent = l.domain;
        row.appendChild(d);
      }
      listEl.appendChild(row);
    }
    if (st.source) {
      evTitleEl.textContent = links.length ? 'Headlines and source' : 'Source';
'''

edits = {
    app / "events.py": [
        # fix: a refreshed row must also get its new timestamp, or it ages out of the 24-hour window
        ("  title = EXCLUDED.title, lat = EXCLUDED.lat, lon = EXCLUDED.lon,\n",
         "  title = EXCLUDED.title, lat = EXCLUDED.lat, lon = EXCLUDED.lon, occurred_at = EXCLUDED.occurred_at,\n"),
        ('{"id": "news", "label": "News", "live": False},', '{"id": "news", "label": "News", "live": True},'),
        ('{"id": "politics", "label": "Politics", "live": False},', '{"id": "politics", "label": "Politics", "live": True},'),
    ],
    app / "main.py": [
        ("from . import accounts, aviation, events, pages, weather\n",
         "from . import accounts, aviation, events, news, pages, weather\n"),
        ("        asyncio.create_task(aviation.ingest_loop()),\n    ]\n",
         "        asyncio.create_task(aviation.ingest_loop()),\n        asyncio.create_task(news.ingest_loop()),\n    ]\n"),
    ],
    static / "layers.js": [
        ("export const STYLE = {\n", STYLE_NEW),
        (SHOW_OLD, SHOW_NEW),
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
