import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"
brand = static / "brand"

if not (brand / "brand.css").exists() or not (brand / "fonts" / "orbitron-latin-wght-normal.woff2").exists():
    sys.exit("STOPPED, nothing changed. Unpack xyron-brand.zip into ~/xyron first (it creates api/app/static/brand/).")

HEAD_TAGS = (
    '<link rel="icon" type="image/png" sizes="32x32" href="/static/brand/favicon-32.png">\n'
    '<link rel="icon" type="image/png" sizes="16x16" href="/static/brand/favicon-16.png">\n'
    '<link rel="shortcut icon" href="/static/brand/favicon.ico">\n'
    '<link rel="apple-touch-icon" sizes="180x180" href="/static/brand/apple-touch-icon.png">\n'
    '<link rel="manifest" href="/static/brand/site.webmanifest">\n'
    '<link rel="stylesheet" href="/static/brand/brand.css">\n'
)
SPLASH = ('<div id="splash" aria-hidden="true"><img src="/static/brand/splash.webp" alt="">'
          '<p>Initialising</p></div>\n')
HEADER_LOGO = ('<a class="brand" href="/" aria-label="XYRON"><img class="mark" src="/static/brand/logo-mark.webp" alt="">'
               '<img class="word" src="/static/brand/logo-wordmark.webp" alt="XYRON"></a>')
AUTH_LOGO = '<h1 class="logo"><img src="/static/brand/logo-full.webp" alt="XYRON" width="260" height="239"></h1>'

CHIP_HELPERS = r'''const SVG_NS = 'http://www.w3.org/2000/svg';
// One colour per layer, matching what it shows. Aviation is left out on purpose and keeps the default look.
export const CHIP_COLORS = {
  earthquakes: '#ff5a36', weather: '#36d6e7', news: '#a5c8ff', politics: '#b07cff', sports: '#ffc83d', football: '#2ee57a',
};
// Simple icons on a 24 by 24 grid. Lines, except the plane, which is solid.
const CHIP_ICONS = {
  earthquakes: { d: ['M2 12h4l2.5-6 4 12 3-9 1.5 3H22'] },
  weather: { d: ['M7 18a4 4 0 0 1-.4-7.98A5.5 5.5 0 0 1 17.1 9.2 3.9 3.9 0 0 1 17 18H7z'] },
  news: { d: ['M4 5h12v14H5.5A1.5 1.5 0 0 1 4 17.5V5z', 'M16 9h3.5v8.5a1.5 1.5 0 0 1-1.5 1.5H16', 'M7 9h6M7 12.5h6M7 16h4'] },
  politics: { d: ['M3 9.5 12 4l9 5.5H3z', 'M6 12v6M10 12v6M14 12v6M18 12v6', 'M3.5 20.5h17'] },
  sports: { d: ['M8 4h8v5a4 4 0 0 1-8 0V4z', 'M8 6H5v1a3 3 0 0 0 3 3', 'M16 6h3v1a3 3 0 0 1-3 3', 'M12 13v4', 'M9 20.5h6', 'M10 17h4'] },
  football: { circles: [[12, 12, 9]], d: ['M12 8.3l3.3 2.4-1.3 3.9h-4l-1.3-3.9z', 'M12 8.3V3.2', 'M15.3 10.7l4.6-1.5', 'M14 14.6l2.9 3.9', 'M10 14.6l-2.9 3.9', 'M8.7 10.7 4.1 9.2'] },
  aviation: { fill: true, d: ['M12 2c.9 0 1.5.8 1.5 1.7V9l8 5v2.2l-8-2.4V19l2 1.5V22L12 21l-3.5 1v-1.5l2-1.5v-5.2l-8 2.4V14l8-5V3.7C10.5 2.8 11.1 2 12 2z'] },
};
export function chipIcon(id) {
  const spec = CHIP_ICONS[id];
  if (!spec) return '';
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'ico');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('fill', spec.fill ? 'currentColor' : 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', spec.fill ? '0' : '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  for (const [cx, cy, r] of spec.circles || []) {
    const c = document.createElementNS(SVG_NS, 'circle');
    c.setAttribute('cx', cx); c.setAttribute('cy', cy); c.setAttribute('r', r);
    svg.appendChild(c);
  }
  for (const d of spec.d) {
    const p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', d);
    svg.appendChild(p);
  }
  return svg;
}
function hexRgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
}
export function rgbHex(rgb) {
  return '#' + rgb.map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, '0')).join('');
}
// give a chip its colour; no colour means the chip keeps the default look
export function paintChip(b, hex) {
  if (!hex) return;
  b.classList.add('coded');
  b.style.setProperty('--c', hex);
  b.style.setProperty('--cb', hexRgba(hex, 0.45));
  b.style.setProperty('--cbg', hexRgba(hex, 0.16));
  b.style.setProperty('--cg', hexRgba(hex, 0.42));
}

export function init(ctx) {
'''

REQUIRED = {
    app / "pages.py": [
        ("\"img-src 'self' data:; connect-src 'self'; form-action 'self'; \"\n",
         "\"img-src 'self' data:; font-src 'self'; manifest-src 'self'; connect-src 'self'; form-action 'self'; \"\n"),
    ],
    static / "globe.html": [
        ('<span class="brand">XYRON</span>', HEADER_LOGO),
        ('<body>\n<div id="stage">\n', '<body>\n' + SPLASH + '<div id="stage">\n'),
    ],
    static / "layers.js": [
        ("export function init(ctx) {\n", CHIP_HELPERS),
        ("      b.append((l.id === 'football' ? '\\u26bd ' : '') + l.label);\n",
         "      paintChip(b, CHIP_COLORS[l.id]);\n      b.append(chipIcon(l.id), l.label);\n"),
        ("      b.className = 'chip small' + (sportsOff.has(s.id) ? '' : ' on');\n",
         "      b.className = 'chip small' + (sportsOff.has(s.id) ? '' : ' on');\n"
         "      paintChip(b, rgbHex(SPORT_COLORS[s.id] || [0.8, 0.9, 1.0]));\n"),
    ],
}
# nice to have: the full logo on the sign-in and register pages; skipped with a note if the page looks different
OPTIONAL = {
    static / "login.html": ("<h1>XYRON</h1>", AUTH_LOGO),
    static / "register.html": ("<h1>XYRON</h1>", AUTH_LOGO),
}

new_text = {}
if "CHIP_COLORS" in (static / "layers.js").read_text():
    sys.exit("STOPPED, nothing changed. This patch has already been applied.")
for path, pairs in REQUIRED.items():
    text = path.read_text()
    for old, new in pairs:
        if text.count(old) != 1:
            sys.exit(f"STOPPED, nothing changed. Could not find exactly one match in {path.name} for:\n{old[:200]!r}")
        text = text.replace(old, new)
    new_text[path] = text
for path, (old, new) in OPTIONAL.items():
    if not path.exists():
        print("note:", path.name, "not found, logo not added there")
        continue
    text = path.read_text()
    if text.count(old) == 1:
        new_text[path] = text.replace(old, new)
    else:
        print("note:", path.name, "has a different heading, so the logo was not added there")

# favicon, font and styles on every page; the loading-screen script only on the globe page
for page in sorted(static.glob("*.html")):
    text = new_text.get(page, page.read_text())
    if "brand/brand.css" in text:
        continue
    if text.count("</head>") != 1:
        print("note:", page.name, "has no single </head>, so favicon and font were not added there")
        continue
    extra = '<script src="/static/brand/brand.js" defer></script>\n' if page.name == "globe.html" else ""
    new_text[page] = text.replace("</head>", HEAD_TAGS + extra + "</head>")

for path, text in new_text.items():
    path.write_text(text)
    print("patched", path.name)
