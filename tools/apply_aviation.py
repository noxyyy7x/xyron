import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
app = root / "api" / "app"
static = app / "static"

edits = {
    app / "events.py": [
        ('{"id": "aviation", "label": "Aviation", "live": False},',
         '{"id": "aviation", "label": "Aviation", "live": True},'),
        ('        item["updated"] = st["last_ok"].isoformat() if st.get("last_ok") else None\n',
         '        item["updated"] = st["last_ok"].isoformat() if st.get("last_ok") else None\n'
         '        if st.get("count") is not None:\n            item["count"] = st["count"]\n'),
    ],
    app / "main.py": [
        ("from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response\n",
         "from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response\n"
         "from fastapi.middleware.gzip import GZipMiddleware\n"),
        ("from . import accounts, events, pages, weather\n",
         "from . import accounts, aviation, events, pages, weather\n"),
        ("        asyncio.create_task(weather.ingest_loop()),\n    ]\n",
         "        asyncio.create_task(weather.ingest_loop()),\n"
         "        asyncio.create_task(aviation.ingest_loop()),\n    ]\n"),
        ("app.include_router(events.router)\n",
         "app.include_router(events.router)\napp.include_router(aviation.router)\n"),
        ("pages.setup(app)\n",
         "pages.setup(app)\napp.add_middleware(GZipMiddleware, minimum_size=1000)\n"),
    ],
    static / "layers.js": [
        ("export const STYLE = {\n",
         "export const STYLE = {\n"
         "  aviation: {\n"
         "    pulse: 0,\n    color: () => [0.4, 0.8, 1.0],\n    size: () => 0.02,\n    rank: () => 0,\n"
         "    tip: (e) => [e.title, ''],\n    rows: () => [],\n    source: null,\n"
         "    summary: (n, l) => 'Aircraft \\u00b7 ' + ((l && l.count) || 0) + ' airborne (OpenSky Network)',\n"
         "  },\n"),
        ("    const parts = on.map((l) => styleOf(l.id).summary(events.filter((e) => e.layer === l.id).length));\n",
         "    const parts = on.map((l) => styleOf(l.id).summary(events.filter((e) => e.layer === l.id).length, l));\n"),
        ("  function renderChips() {\n",
         "  function broadcast() {\n"
         "    window.dispatchEvent(new CustomEvent('xyron-layers', { detail: [...enabled] }));\n  }\n\n"
         "  function renderChips() {\n"),
        ("          saveEnabled(enabled);\n",
         "          saveEnabled(enabled);\n          broadcast();\n"),
        ("      renderStatus();\n    } catch (err) {\n",
         "      renderStatus();\n      broadcast();\n    } catch (err) {\n"),
    ],
    static / "globe.js": [
        ("let layerHooks = {};\n",
         "let layerHooks = {};\nlet aviationHooks = {};\n"),
        ("  selC = i >= 0 ? data.c[i] : -1;\n",
         "  selC = i >= 0 ? data.c[i] : -1;\n  if (aviationHooks.clear) aviationHooks.clear();\n"),
        ("    if (layerHooks.onClick && layerHooks.onClick(e.clientX, e.clientY)) return; // an event marker was tapped\n",
         "    if (layerHooks.onClick && layerHooks.onClick(e.clientX, e.clientY)) return; // an event marker was tapped\n"
         "    if (aviationHooks.onClick && aviationHooks.onClick(e.clientX, e.clientY)) return; // an aircraft was tapped\n"),
        ("} catch (e) {\n  console.error('Live layers failed to load', e);\n}\n",
         "} catch (e) {\n  console.error('Live layers failed to load', e);\n}\n"
         "try {\n  const mod = await import('/static/aviation.js');\n"
         "  aviationHooks = mod.init({\n    THREE, globe, camera, renderer, canvas,\n"
         "    deselect: () => select(-1), flyTo, openPanel,\n  }) || {};\n"
         "} catch (e) {\n  console.error('Aviation layer failed to load', e);\n}\n"),
        ("    const overEvent = layerHooks.onHover ? layerHooks.onHover(pendingHover[0], pendingHover[1]) : false;\n",
         "    const overMarker = layerHooks.onHover ? layerHooks.onHover(pendingHover[0], pendingHover[1]) : false;\n"
         "    const overPlane = !overMarker && aviationHooks.onHover ? aviationHooks.onHover(pendingHover[0], pendingHover[1]) : false;\n"
         "    const overEvent = overMarker || overPlane;\n"),
        ("  if (layerHooks.onFrame) layerHooks.onFrame(now, dt);\n",
         "  if (layerHooks.onFrame) layerHooks.onFrame(now, dt);\n  if (aviationHooks.onFrame) aviationHooks.onFrame(now, dt);\n"),
    ],
}

# check everything first, so a mismatch changes nothing
new_text = {}
for path, pairs in edits.items():
    text = path.read_text()
    for old, new in pairs:
        if text.count(old) != 1:
            sys.exit(f"STOPPED, nothing changed. Could not find exactly one match in {path.name} for:\n{old!r}")
        text = text.replace(old, new)
    new_text[path] = text
for path, text in new_text.items():
    path.write_text(text)
    print("patched", path.name)
