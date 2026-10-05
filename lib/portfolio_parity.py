#!/usr/bin/env python3
"""Does the dashboard's preview of an element look like the element on the live dev site?

The Templates tab renders the generalized element with the dashboard's own preview document; the library records the
element's look and geometry as captured from the live site. This renders the former exactly as the dashboard does,
measures it, and compares it with the latter, so a preview that has drifted from the site is a failing check, not
something Gil notices by eye.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_elements as pe  # noqa: E402
import portfolio_templates as pt  # noqa: E402

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"
# how the Templates tab frames each element (see Specimen in PortfolioHub.jsx)
FRAMING = {"project-card": {"context": "grid", "width": 760, "wide": False}}
CHROME_WIDTHS = {"site-header": None, "page-title-bar": None, "site-footer": None, "hub-sidebar": 260, "other-projects": 760}
CHROME_DIR = Path.home() / ".claude" / "portfolio" / "inventory" / "chrome"


def framing_for(element_id: str) -> dict:
    if element_id in FRAMING:
        return FRAMING[element_id]
    if element_id == "other-projects":    # lives INSIDE the page content (a mount in the page body), so it takes the page context
        return {"context": "page", "wide": True, "width": CHROME_WIDTHS[element_id]}
    if element_id in CHROME_WIDTHS:       # parts that sit around the page, outside <main>
        return {"context": "chrome", "wide": True, "width": CHROME_WIDTHS[element_id]}
    return {"context": "page", "width": 340, "wide": False}


def preview_html(element_id: str, project: Path) -> str:
    """What the dashboard puts in the frame: the template's specimen when the element has a template, otherwise the part as
    captured from the live site (the same thing the Templates tab shows for the parts around every page)."""
    try:
        specimen = pt.specimen(element_id, project / "templates")
    except Exception:
        specimen = {"ok": False}
    if specimen.get("ok"):
        return specimen["html"]
    captured = CHROME_DIR / f"{element_id}.html"
    if captured.exists():
        return captured.read_text()
    raise RuntimeError(f"nothing to preview for {element_id!r}")
FRAME_WIDTH = 1100          # the preview iframe is page-wide in the dashboard, so the theme's desktop styles apply


def compare(element: dict, instance: dict) -> list[str]:
    """Differences between the captured element and a measured preview (empty = they match)."""
    diffs = []
    for part, want in (element.get("look") or {}).items():
        have = (instance.get("look") or {}).get(part) or {}
        for prop, value in (want or {}).items():
            if have.get(prop) != value:
                diffs.append(f"{part}.{prop}: site {value!r}, preview {have.get(prop)!r}")
    want_geo, geo = element.get("geometry"), instance.get("geometry")
    if want_geo and geo != want_geo:
        diffs.append(f"geometry: site {want_geo}, preview {geo}")
    return diffs


_FONT_JS = """async (spec) => {
  await Promise.all(spec.map(s => document.fonts.load(s).catch(() => null)));
  return spec.filter(s => !document.fonts.check(s));
}"""


def unloaded_fonts(frame, element: dict) -> list[str]:
    """A computed font-family only NAMES the font; if the web font failed to load (cross-origin, blocked) the browser
    silently draws Arial. Check that each text font the element uses actually loaded in the preview."""
    specs = []
    for part in (element.get("look") or {}).values():
        if part and part.get("fontFamily"):
            family = part["fontFamily"].split(",")[0].strip()
            specs.append(f'{part.get("fontWeight", "400")} {part.get("fontSize", "16px")} {family}')
    bad = frame.evaluate(_FONT_JS, sorted(set(specs)))
    return [f"font did not load in the preview: {b}" for b in bad]


def preview_document(html: str, framing: dict) -> str:
    r = subprocess.run(["node", str(DASHBOARD / "scripts" / "render_preview.mjs")], input=json.dumps({"html": html, **framing}),
                       capture_output=True, text=True, timeout=60, cwd=str(DASHBOARD))
    if r.returncode != 0:
        raise RuntimeError(f"could not build the preview document: {r.stderr[-300:]}")
    return r.stdout


def verify(element_id: str = "project-card", base: str = pe.BASE, project: Path = pe.PROJECT) -> dict:
    from playwright.sync_api import sync_playwright
    element = json.loads((Path(project) / "templates" / "elements" / f"{element_id}.json").read_text())
    doc = preview_document(preview_html(element_id, project), framing_for(element_id))

    def cors(route):                     # the dashboard adds this header to dev-site responses (electron/main/dev_site_cors.js)
        response = route.fetch()
        route.fulfill(response=response, headers={**response.headers, "access-control-allow-origin": "*"})

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1300, "height": 900})
        page.route(base + "/**", cors)
        page.set_content(f"<iframe id='f' style='width:{FRAME_WIDTH}px;height:700px;border:0'></iframe>")
        page.evaluate("(d) => { document.getElementById('f').srcdoc = d }", doc)
        page.wait_for_timeout(2500)
        frame = next(f for f in page.frames if f != page.main_frame)
        instances = pe.page_instances(frame, pe.ELEMENTS[element_id])
        font_diffs = unloaded_fonts(frame, element)
        browser.close()
    if not instances:
        return {"ok": False, "element": element_id, "differences": ["the element does not appear in the preview at all"]}
    diffs = compare(element, instances[0]) + font_diffs
    return {"ok": not diffs, "element": element_id, "differences": diffs}


def main() -> None:
    out = verify(sys.argv[1] if len(sys.argv) > 1 else "project-card")
    print(json.dumps(out))
    sys.exit(0 if out["ok"] else 1)


if __name__ == "__main__":
    main()
