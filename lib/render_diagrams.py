#!/usr/bin/env python3
"""Render Mermaid sources to standalone SVG files (for pages and READMEs that need a diagram as a file).

    render_diagrams.py out_dir name=source.mmd [name=source.mmd ...]
    render_diagrams.py --spec figures.json        # {"out_dir": "...", "diagrams": {"name": "mermaid source"}}

Mermaid is loaded from a pinned CDN build into a headless browser and the SVG is saved with a white background. Nothing
else leaves the machine: only the library is fetched, never the diagram text.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
THEME = {"theme": "base", "themeVariables": {"fontFamily": "Roboto Mono, Menlo, monospace", "fontSize": "15px", "primaryColor": "#ffffff",
                                             "primaryBorderColor": "#1c1c1c", "primaryTextColor": "#1c1c1c", "lineColor": "#1c1c1c",
                                             "secondaryColor": "#fff0f7", "tertiaryColor": "#ffffff", "clusterBkg": "#faf7f2", "clusterBorder": "#bdb6a8"}}


def render(diagrams: dict[str, str], out_dir: Path) -> dict[str, Path]:
    from playwright.sync_api import sync_playwright
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.set_content("<html><body style='background:#fff'><div id='host'></div></body></html>")
        page.add_script_tag(url=MERMAID)
        page.evaluate("(cfg) => mermaid.initialize({startOnLoad: false, securityLevel: 'strict', flowchart: {htmlLabels: false, curve: 'basis', nodeSpacing: 30, rankSpacing: 38, padding: 8}, htmlLabels: false, ...cfg})", THEME)
        for name, source in diagrams.items():
            svg = page.evaluate("async ([id, src]) => { const r = await mermaid.render(id, src); return r.svg }", [f"d-{re.sub('[^a-z0-9]', '', name)}", source])
            root = re.match(r"<svg\b[^>]*>", svg).group(0)
            fixed = re.sub(r'style="', 'style="background:#ffffff;', root, 1) if 'style="' in root else root.replace("<svg", '<svg style="background:#ffffff"', 1)
            vb = re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"', fixed)
            if vb:                       # an image needs a size of its own: width="100%" has no intrinsic size, so it filled any column
                fixed = re.sub(r'width="100%"', f'width="{round(float(vb.group(1)))}" height="{round(float(vb.group(2)))}"', fixed, 1)
            svg = svg.replace(root, fixed, 1)
            if "http://" in re.sub(r'xmlns[^=]*="[^"]*"', "", svg) or "https://" in svg:
                raise RuntimeError(f"{name}: the rendered SVG references an external resource")
            import xml.etree.ElementTree as ET
            try:
                ET.fromstring(svg)               # a file used as <img> must be well-formed XML, not just HTML-tolerant markup
            except ET.ParseError as exc:
                raise RuntimeError(f"{name}: the SVG is not well-formed XML ({exc}); it would not load as an image") from exc
            path = out_dir / f"{name}.svg"
            path.write_text(svg)
            written[name] = path
        browser.close()
    return written


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--spec":
        spec = json.loads(Path(sys.argv[2]).read_text())
        out = render(spec["diagrams"], Path(spec["out_dir"]))
    else:
        out_dir, *pairs = sys.argv[1:]
        out = render({p.split("=", 1)[0]: Path(p.split("=", 1)[1]).read_text() for p in pairs}, Path(out_dir))
    for n, p in out.items():
        print(f"{n}: {p} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
