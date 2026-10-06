import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
static = root / "api" / "app" / "static"
brand = static / "brand"

for name in ("theme.css", "theme.js", "brand.js"):
    if not (brand / name).exists():
        sys.exit(f"STOPPED, nothing changed. {name} is missing. Unpack xyron-theme.zip into ~/xyron first.")

CSS_LINK = '<link rel="stylesheet" href="/static/brand/brand.css">\n'
THEME_CSS = '<link rel="stylesheet" href="/static/brand/theme.css">\n'
THEME_JS = '<script src="/static/brand/theme.js" defer></script>\n'

GRID = '''globe.add(ball);

// faint latitude and longitude grid on the globe, plus a thin targeting ring around it
{
  const grid = [];
  const R = 0.992;
  const SEG = 96;
  for (let lat = -60; lat <= 60; lat += 30) {
    const la = lat * DEG;
    for (let i = 0; i < SEG; i++) {
      const a = (i / SEG) * Math.PI * 2;
      const b = ((i + 1) / SEG) * Math.PI * 2;
      grid.push(R * Math.cos(la) * Math.sin(a), R * Math.sin(la), R * Math.cos(la) * Math.cos(a),
        R * Math.cos(la) * Math.sin(b), R * Math.sin(la), R * Math.cos(la) * Math.cos(b));
    }
  }
  for (let lon = 0; lon < 180; lon += 30) {
    const lo = lon * DEG;
    for (let i = 0; i < SEG; i++) {
      const a = (i / SEG) * Math.PI * 2;
      const b = ((i + 1) / SEG) * Math.PI * 2;
      grid.push(R * Math.cos(a) * Math.sin(lo), R * Math.sin(a), R * Math.cos(a) * Math.cos(lo),
        R * Math.cos(b) * Math.sin(lo), R * Math.sin(b), R * Math.cos(b) * Math.cos(lo));
    }
  }
  const gg = new THREE.BufferGeometry();
  gg.setAttribute('position', new THREE.BufferAttribute(new Float32Array(grid), 3));
  globe.add(new THREE.LineSegments(gg, new THREE.LineBasicMaterial({ color: 0x2a6bd6, transparent: true, opacity: 0.2, depthWrite: false })));

  const ringPts = [];
  const RR = 1.32;
  for (let i = 0; i < 180; i++) {
    const a = (i / 180) * Math.PI * 2;
    const b = ((i + 1) / 180) * Math.PI * 2;
    ringPts.push(RR * Math.cos(a), RR * Math.sin(a), 0, RR * Math.cos(b), RR * Math.sin(b), 0);
  }
  for (let d = 0; d < 360; d += 10) { // tick marks
    const a = d * DEG;
    const len = d % 30 === 0 ? 0.06 : 0.03;
    ringPts.push(RR * Math.cos(a), RR * Math.sin(a), 0, (RR + len) * Math.cos(a), (RR + len) * Math.sin(a), 0);
  }
  const rg = new THREE.BufferGeometry();
  rg.setAttribute('position', new THREE.BufferAttribute(new Float32Array(ringPts), 3));
  stage.add(new THREE.LineSegments(rg, new THREE.LineBasicMaterial({ color: 0x2f81ff, transparent: true, opacity: 0.28, depthWrite: false })));
}
'''

new_text = {}
pages = sorted(static.glob("*.html"))
globe_html = static / "globe.html"
if "brand/brand.css" not in globe_html.read_text():
    sys.exit("STOPPED, nothing changed. The brand step has not been applied yet (globe.html has no brand.css link).")
for page in pages:
    text = page.read_text()
    if "brand/theme.css" in text:
        continue
    if text.count(CSS_LINK) != 1 or text.count("</head>") != 1:
        print("note:", page.name, "looks different from what I expected, so the theme was not added there")
        continue
    text = text.replace(CSS_LINK, CSS_LINK + THEME_CSS).replace("</head>", THEME_JS + "</head>")
    new_text[page] = text

# optional: the grid and ring on the 3D globe
globe_js = static / "globe.js"
if globe_js.exists() and "faint latitude and longitude grid" not in globe_js.read_text():
    js = globe_js.read_text()
    if js.count("globe.add(ball);\n") == 1:
        new_text[globe_js] = js.replace("globe.add(ball);\n", GRID)
    else:
        print("note: globe.js looks different from what I expected, so the grid on the globe was skipped")

if not new_text:
    sys.exit("STOPPED, nothing changed. The theme has already been applied.")
for path, text in new_text.items():
    path.write_text(text)
    print("patched", path.name)
