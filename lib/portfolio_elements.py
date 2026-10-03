#!/usr/bin/env python3
"""Capture ELEMENTS from the live dev site into the element library (a one-time job, then edited deliberately).

The dev site is the master for how an element looks (Gil approved it). An element is captured from the rendered
site, generalized (its content swapped for placeholders) and stored with:

  markup       the generalized element, ready to copy
  fields       what a person fills in
  look         the element's computed look, part by part (fonts, colours, spacing, photo treatment): the reference
               that every placement, and the dashboard's own preview, is compared against
  provenance   which stylesheet and rule sets each key property (so nobody has to hunt for where the look comes from)
  usage        every page that carries the element, and how many times
  placements   how many distinct looks the live site actually has (1 means every placement is the same element)

Stored as templates/elements/<id>.json in the portfolio repo, beside the templates. Read-only to the dev site.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HOME = Path.home()
PROJECT = HOME / "Documents" / "Projects" / "portfolio-website-updater"
INVENTORY = HOME / ".claude" / "portfolio" / "inventory" / "inventory.json"
BASE = "http://localhost:8080"

# Context-independent properties: widths and heights that depend on the column are left out on purpose, and each part
# records only what it can actually show (a photo has no font worth comparing).
_TEXT = ["fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "textTransform", "textAlign", "color"]
_BOX = ["backgroundColor", "borderTopWidth", "borderTopColor", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "display"]
PART_PROPS = {
    "photo": ["display", "filter", "objectFit"],
    "box": _TEXT + _BOX + ["flexDirection"],
    "title": _TEXT + ["display"],
    "description": _TEXT,
    "button": _TEXT + _BOX,
}
LOOK_PROPS = sorted({p for props in PART_PROPS.values() for p in props})
# What to ask the browser who set (CSS property names)
PROVENANCE_PROPS = ["font-family", "color", "filter", "margin-top", "height", "object-fit", "display"]

ELEMENTS = {
    "project-card": {
        "name": "Project card",
        "description": "A project's card: its photo in a fixed frame with the text box overlaying the bottom of it. "
                       "Used on the category hubs, All Projects and the Other Projects footer.",
        "selector": ".col-md-6:has(> .card-container-lg)",
        # part name -> selector inside the element
        "parts": {"photo": ".black-image-project-hover img", "box": ".card-container-lg", "title": ".card-title",
                  "description": ".equal p", "button": ".btn"},
        # the live page each placement is read from (a hub, All Projects, a project page's footer)
        "sample_pages": ["/ai-projects/", "/all-projects/", "/ai-projects/mancala/"],
        "fields": [
            {"name": "URL", "label": "Project page path", "type": "url"},
            {"name": "TITLE", "label": "Title", "type": "text"},
            {"name": "THUMBNAIL", "label": "Photo", "type": "url"},
            {"name": "DESCRIPTION", "label": "Description", "type": "text"},
            {"name": "ALSO_HTML", "label": "\"Also: ...\" line (two-category projects only)", "type": "html"},
        ],
    },
}


# ── pure helpers (tested without a browser) ─────────────────────────────────

_NOISE = re.compile(r"\s*\b(lazyloaded|lazyload|lazyloading|ls-is-cached|fusion-responsive-typography-calculated)\b")


def generalize_card(markup: str) -> str:
    """Swap one live card's content for placeholders. The live DOM differs from the template only by lazy-load and
    theme-added classes and attributes, which are stripped, so a generalized capture equals the template."""
    out = _NOISE.sub("", markup)
    out = re.sub(r'class="\s+', 'class="', out)                   # a removed first class leaves a leading space
    out = re.sub(r'\s+"', '"', out)
    out = re.sub(r'\s(decoding|data-orig-src|data-orig-sizes|srcset|sizes|loading|width|height|data-fontsize|data-lineheight)="[^"]*"', "", out)
    out = re.sub(r'\sstyle="--fontSize[^"]*"', "", out)          # Avada's responsive-typography script writes this onto titles
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r">\s+<", "><", out).strip()
    m = re.search(r'<a href="([^"]*)" class="black-image-project-hover"><img src="([^"]*)"', out)
    if not m:
        raise ValueError("not a project card: the photo link was not found")
    url, photo = m.group(1), m.group(2)
    title = re.search(r'<h3 class="card-title">(.*?)</h3>', out)
    desc = re.search(r'<div class="equal"><p>(.*?)</p>(.*?)</div>', out)
    if not title or not desc:
        raise ValueError("not a project card: title or description not found")
    out = out.replace(f'href="{url}"', 'href="{{URL}}"').replace(f'src="{photo}"', 'src="{{THUMBNAIL}}"')
    out = out.replace(f'title="{title.group(1)}"', 'title="{{TITLE}}"')
    out = out.replace(f'<h3 class="card-title">{title.group(1)}</h3>', '<h3 class="card-title">{{TITLE}}</h3>')
    out = out.replace(f'<div class="equal"><p>{desc.group(1)}</p>{desc.group(2)}</div>', '<div class="equal"><p>{{DESCRIPTION}}</p>{{ALSO_HTML}}</div>')
    return out


def distinct_looks(looks: list[dict]) -> list[dict]:
    seen, out = set(), []
    for look in looks:
        key = json.dumps(look, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(look)
    return out


def find_deviations(instances: list[tuple[str, dict]], markup: str | None, look: dict | None, geometry: dict | None) -> list[dict]:
    """Placements that are not the element: hand-built markup, a different computed look, or different geometry.
    These are what the library surfaces for fixing -- the element itself is never changed to fit them."""
    found: dict[str, set] = {}
    for url, inst in instances:
        why = set()
        try:
            if markup and generalize_card(inst["html"]) != markup:
                why.add("hand-built markup (differs from the element)")
        except ValueError:
            why.add("not recognisable as the element")
        if look and inst["look"] != look:
            why.add("different computed look")
        if geometry and inst["geometry"] and inst["geometry"] != geometry:
            why.add(f"different geometry {inst['geometry']}")
        if why:
            found.setdefault(url, set()).update(why)
    return [{"page": u, "why": sorted(w)} for u, w in sorted(found.items())]


# ── browser capture ─────────────────────────────────────────────────────────

_GEOM_JS = """([sel, photoSel, boxSel]) => [...document.querySelectorAll(sel)].map(el => {
  const ph = el.querySelector(photoSel), bx = el.querySelector(boxSel);
  if (!ph || !bx) return null;
  const pr = ph.getBoundingClientRect(), br = bx.getBoundingClientRect();
  return {photoHeight: Math.round(pr.height), boxHeight: Math.round(br.height), overlap: Math.round(pr.bottom - br.top)};
})"""

_LOOK_JS = """([sel, parts, partProps]) => [...document.querySelectorAll(sel)].map(el => {
  const out = {};
  for (const [name, psel] of Object.entries(parts)) {
    const e = psel === '' ? el : el.querySelector(psel);
    if (!e) { out[name] = null; continue; }
    const cs = getComputedStyle(e);
    out[name] = Object.fromEntries((partProps[name] || []).map(p => [p, cs[p]]));
  }
  return {look: out, html: el.outerHTML};
})"""


def _page_looks(page, definition: dict) -> list[dict]:
    return page.evaluate(_LOOK_JS, [definition["selector"], definition["parts"], PART_PROPS])


def page_instances(page, definition: dict) -> list[dict]:
    """Every placement of the element on the current page: its look (part by part), geometry and generalized markup."""
    looks = _page_looks(page, definition)
    geoms = page.evaluate(_GEOM_JS, [definition["selector"], definition["parts"]["photo"], definition["parts"]["box"]])
    return [{"look": l["look"], "geometry": g, "html": l["html"]} for l, g in zip(looks, geoms)]


def _provenance(page, definition: dict) -> dict:
    """Which stylesheet + selector sets each key property for each part (the winning, i.e. last-matched, rule)."""
    cdp = page.context.new_cdp_session(page)
    sheets: dict[str, str] = {}
    cdp.on("CSS.styleSheetAdded", lambda e: sheets.__setitem__(e["header"]["styleSheetId"], e["header"].get("sourceURL") or "(inline <style>)"))
    cdp.send("DOM.enable")
    cdp.send("CSS.enable")
    page.reload(wait_until="networkidle")
    doc = cdp.send("DOM.getDocument", {"depth": 0})
    root = doc["root"]["nodeId"]
    result: dict[str, dict] = {}
    for name, psel in definition["parts"].items():
        full = definition["selector"] + (" " + psel if psel else "")
        try:
            node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": full})["nodeId"]
            matched = cdp.send("CSS.getMatchedStylesForNode", {"nodeId": node})["matchedCSSRules"]
        except Exception:
            continue
        found: dict[str, dict] = {}
        for entry in matched:                      # later rules win, so overwrite as we go
            rule = entry["rule"]
            for prop in rule["style"]["cssProperties"]:
                if prop["name"] in PROVENANCE_PROPS and not prop.get("disabled"):
                    src = sheets.get(rule.get("styleSheetId", ""), "(unknown)")
                    found[prop["name"]] = {"selector": rule["selectorList"]["text"], "value": prop["value"], "source": urlparse(src).path or src}
        if found:
            result[name] = found
    return result


def capture(element_id: str = "project-card", base: str = BASE, project: Path = PROJECT, inventory: Path = INVENTORY) -> dict:
    from playwright.sync_api import sync_playwright
    definition = ELEMENTS[element_id]
    pages = [p["url"] for p in json.loads(Path(inventory).read_text())["pages"]]
    usage, all_looks, all_geoms, instances, markup, first_page = {}, [], [], [], None, None
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for url in pages:
            page.goto(base + url, wait_until="networkidle")
            page.wait_for_timeout(300)
            found = page_instances(page, definition)
            if found:
                usage[url] = len(found)
                all_looks += [f["look"] for f in found]
                all_geoms += [f["geometry"] for f in found if f["geometry"]]
                instances += [(url, f) for f in found]
                if markup is None:
                    markup, first_page = generalize_card(found[0]["html"]), url
        provenance = {}
        if first_page:
            page.goto(base + definition["sample_pages"][0], wait_until="networkidle")
            provenance = _provenance(page, definition)
        browser.close()
    looks = distinct_looks(all_looks)
    deviations = find_deviations(instances, markup, looks[0] if looks else None, distinct_looks(all_geoms)[0] if all_geoms else None)
    result = {
        "id": element_id, "name": definition["name"], "description": definition["description"],
        "fields": definition["fields"], "markup": markup, "look": looks[0] if looks else None,
        "distinct_looks": len(looks), "geometry": distinct_looks(all_geoms)[0] if all_geoms else None,
        "distinct_geometries": len(distinct_looks(all_geoms)), "deviations": deviations, "provenance": provenance,
        "usage": {"pages": usage, "placements": sum(usage.values())},
        "captured_from": first_page, "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    out = Path(project) / "templates" / "elements"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{element_id}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def main() -> None:
    ids = sys.argv[1:] or list(ELEMENTS)
    for i in ids:
        r = capture(i)
        print(f"{i}: {r['usage']['placements']} placements on {len(r['usage']['pages'])} pages, {r['distinct_looks']} distinct look(s)")


if __name__ == "__main__":
    main()
