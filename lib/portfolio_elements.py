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
    "*": _TEXT + _BOX,          # any other part (header, sidebar item, heading ...)
}
LOOK_PROPS = sorted({p for props in PART_PROPS.values() for p in props})
# What to ask the browser who set (CSS property names)
PROVENANCE_PROPS = ["font-family", "color", "filter", "margin-top", "height", "object-fit", "display"]

ELEMENTS = {
    "project-card": {
        "template": "project-card",
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
    "button-github": {
        "name": "GitHub button", "template": "button-github",
        "description": "The project's own repository. First button in a project page's action row.",
        "selector": 'main a.btn[href*="github.com/G-Eskayo"]', "parts": {"button": ""},
        "rules": [{"attr": "href", "value": "{{REPO_URL}}"}, {"text": "{{LABEL}}"}],
        "sample_pages": ["/ai-projects/marvin/"],
        "fields": [{"name": "REPO_URL", "label": "Repository URL", "type": "url"}, {"name": "LABEL", "label": "Label", "type": "text"}],
    },
    "button-download": {
        "name": "Download button", "template": "button-download",
        "description": "A file attached to a project (report, paper). After the GitHub button, same row.",
        "selector": "main a.btn[download]", "parts": {"button": ""},
        "rules": [{"attr": "href", "value": "{{FILE_URL}}"}, {"text": "{{LABEL}}"}],
        "sample_pages": ["/ai-projects/marvin/"],
        "fields": [{"name": "FILE_URL", "label": "File URL", "type": "url"}, {"name": "LABEL", "label": "Label", "type": "text"}],
    },
    "site-header": {
        "name": "Site header", "description": "Logo and main menu. Global: identical on every page.",
        "selector": ".fusion-header-wrapper", "parts": {"header": "", "menu": ".fusion-main-menu > ul > li:first-child > a"}, "rules": [],
        "part_props": {"header": ["display", "backgroundColor", "paddingTop", "paddingBottom"], "menu": _TEXT + ["textTransform"]},
        "sample_pages": ["/ai-projects/marvin/"], "fields": [],
    },
    "page-title-bar": {
        "name": "Page title bar", "description": "The dark bar with the page's own title; comes from the page title.",
        "selector": ".avada-page-titlebar-wrapper", "parts": {"bar": ".fusion-page-title-bar", "title": ".entry-title"},
        "part_props": {"bar": ["display", "backgroundColor", "paddingTop", "paddingBottom"],
                       # size and line height are written by Avada's responsive-typography script per page, not by us
                       "title": ["fontFamily", "fontWeight", "letterSpacing", "textTransform", "textAlign", "color"]},
        "rules": [{"select": ".entry-title", "text": "{{TITLE}}"}],
        "sample_pages": ["/ai-projects/marvin/"], "fields": [{"name": "TITLE", "label": "Page title", "type": "text"}],
    },
    "hub-sidebar": {
        "name": "Category sidebar", "description": "The category's project list on hub and project pages; the current page is highlighted.",
        "selector": "nav.hub-sidebar", "parts": {"sidebar": "", "heading": "nav > div:first-child", "item": ".list-group-item:not(.active)", "active": ".list-group-item.active"},
        "part_props": {"sidebar": ["display", "backgroundColor"], "heading": ["fontSize", "textTransform", "letterSpacing", "color"],
                       "item": ["fontFamily", "fontSize", "color", "backgroundColor", "paddingTop", "paddingLeft", "borderTopColor"],
                       "active": ["fontFamily", "fontSize", "color", "backgroundColor", "paddingTop", "paddingLeft", "borderTopColor"]},
        "rules": [{"select": "nav > div:first-child", "text": "{{CATEGORY}}"}, {"select": ".list-group", "inner": "{{ITEMS_HTML}}"}],
        "sample_pages": ["/ai-projects/mancala/"],
        "fields": [{"name": "CATEGORY", "label": "Category", "type": "text"}, {"name": "ITEMS_HTML", "label": "One link per project", "type": "html"}],
    },
    "other-projects": {
        "name": "Other Projects section", "description": "Two project cards under a heading, filled in the browser from the manifest.",
        "selector": "#other-projects-mount", "parts": {"section": "", "heading": "h2"},
        "part_props": {"section": ["display"], "heading": _TEXT},
        "rules": [{"inner": "", "select": ""}, {"attr": "data-category", "value": "{{CATEGORY}}"}, {"attr": "id", "value": "other-projects-mount"}],
        "sample_pages": ["/ai-projects/mancala/"], "fields": [{"name": "CATEGORY", "label": "Category (only needed outside category URLs)", "type": "text"}],
    },
    "site-footer": {
        "name": "Site footer", "description": "The copyright bar. Global.",
        "selector": ".fusion-footer", "parts": {"footer": ".fusion-footer-copyright-area", "notice": ".fusion-copyright-notice"},
        "part_props": {"footer": ["backgroundColor", "paddingTop", "paddingBottom"], "notice": ["fontSize", "color", "textAlign"]},
        "rules": [{"select": ".fusion-copyright-notice > div", "inner": "© Copyright {{YEAR}} Gil Eskayo"}],
        "sample_pages": ["/ai-projects/marvin/"], "fields": [],
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


def normalize_look(props: dict | None) -> dict | None:
    """A font stack is compared by the family actually drawn (the first), since the order of the fallbacks behind it
    differs between page generations and changes nothing the visitor sees."""
    if not props:
        return props
    out = dict(props)
    if out.get("fontFamily"):
        out["fontFamily"] = out["fontFamily"].split(",")[0].strip()
    return out


def geometry_close(a: dict | None, b: dict | None, tol: int = 1) -> bool:
    """Two measured geometries agree when every dimension is within a pixel (sub-pixel layout rounds either way)."""
    if not a or not b:
        return a == b
    return a.keys() == b.keys() and all(abs(a[k] - b[k]) <= tol for k in a)


EDGE_GAP = 14      # the text box keeps this much clear of each side of its photo (--card-edge-gap in other-projects.css)


def geometry_matches(want: dict | None, got: dict | None, tol: int = 1) -> bool:
    """A measured placement matches the element's geometry. The box is at most `want.boxWidth` wide and never reaches its
    photo's borders, so its expected width on THIS placement is min(boxWidth, photoWidth - 2 x EDGE_GAP); every other
    dimension must agree to the pixel."""
    if not want or not got:
        return want == got
    expect = dict(want)
    if "photoWidth" in got and "boxWidth" in expect:
        expect["boxWidth"] = min(expect["boxWidth"], got["photoWidth"] - 2 * EDGE_GAP)
    have = {k: v for k, v in got.items() if k != "photoWidth"}
    return expect.keys() == have.keys() and all(abs(expect[k] - have[k]) <= tol for k in expect)


def master_geometry(geoms: list[dict]) -> dict | None:
    """The element's geometry from its placements: the most common, with the box width taken as the widest seen (narrow
    columns shrink the box, they do not define it)."""
    if not geoms:
        return None
    base = json.loads(_most_common([{k: v for k, v in g.items() if k not in ("photoWidth", "boxWidth")} for g in geoms]))
    base["boxWidth"] = max(g["boxWidth"] for g in geoms)
    return dict(sorted(base.items()))


def normalize_markup(markup: str) -> str:
    """Whitespace-insensitive form of generalized markup, so a captured element and its template compare equal."""
    out = re.sub(r"\s+", " ", markup)
    out = re.sub(r">\s+<", "><", out)
    return out.strip()


def template_markup(template_id: str, project: Path = PROJECT) -> str | None:
    """The authored markup of a template (leading doc comment dropped), normalized: the master for any element that
    has a template, because the template is what the generators and the pipeline emit."""
    root = project / "templates"
    try:
        entry = next(t for t in json.loads((root / "templates.json").read_text())["templates"] if t["id"] == template_id)
        text = (root / entry["file"]).read_text()
    except (OSError, StopIteration, ValueError):
        return None
    return normalize_markup(re.sub(r"\A\s*<!--.*?-->\s*", "", text, count=1, flags=re.DOTALL))


def distinct_looks(looks: list[dict]) -> list[dict]:
    seen, out = set(), []
    for look in looks:
        key = json.dumps(look, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(look)
    return out


def find_deviations(instances: list[tuple[str, dict]], markup: str | None, look: dict | None, geometry: dict | None, normalize=None) -> list[dict]:
    """Placements that are not the element: hand-built markup, a different computed look, or different geometry.
    These are what the library surfaces for fixing -- the element itself is never changed to fit them."""
    found: dict[str, set] = {}
    for url, inst in instances:
        why = set()
        try:
            got = normalize(inst) if normalize else generalize_card(inst["html"])
            if markup and got != markup:
                why.add("hand-built markup (differs from the element)")
        except ValueError:
            why.add("not recognisable as the element")
        if look and inst["look"] != look:
            why.add("different computed look")
        if geometry and inst["geometry"] and not geometry_matches(geometry, inst["geometry"]):
            why.add(f"different geometry {inst['geometry']}")
        if why:
            found.setdefault(url, set()).update(why)
    return [{"page": u, "why": sorted(w)} for u, w in sorted(found.items())]


# ── browser capture ─────────────────────────────────────────────────────────

_GEOM_JS = """([sel, photoSel, boxSel]) => [...document.querySelectorAll(sel)].map(el => {
  const ph = el.querySelector(photoSel), bx = el.querySelector(boxSel);
  if (!ph || !bx) return null;
  const pr = ph.getBoundingClientRect(), br = bx.getBoundingClientRect();
  return {photoHeight: Math.round(pr.height), photoWidth: Math.round(pr.width), boxWidth: Math.round(br.width), boxHeight: Math.round(br.height), overlap: Math.round(pr.bottom - br.top)};
})"""

_LOOK_JS = """([sel, parts, partProps, rules]) => [...document.querySelectorAll(sel)].map(el => {
  const out = {};
  for (const [name, psel] of Object.entries(parts)) {
    const e = psel === '' ? el : el.querySelector(psel);
    if (!e) { out[name] = null; continue; }
    const cs = getComputedStyle(e);
    out[name] = Object.fromEntries((partProps[name] || partProps['*'] || []).map(p => [p, cs[p]]));
  }
  // Generalize a COPY: apply the element's placeholder rules, then drop what the theme and its scripts add at runtime.
  const c = el.cloneNode(true);
  for (const r of (rules || [])) {
    const nodes = r.select ? [...c.querySelectorAll(r.select)] : [c];
    for (const n of nodes) {
      if (r.remove) n.remove();
      else if (r.attr) n.setAttribute(r.attr, r.value);
      else if (r.inner !== undefined) n.innerHTML = r.inner;
      else if (r.text !== undefined) n.textContent = r.text;
    }
  }
  c.querySelectorAll('script, style, noscript').forEach(n => n.remove());
  const walker = document.createTreeWalker(c, NodeFilter.SHOW_COMMENT);
  const comments = []; while (walker.nextNode()) comments.push(walker.currentNode);
  comments.forEach(n => n.remove());
  const noise = ['lazyloaded', 'lazyload', 'lazyloading', 'ls-is-cached', 'fusion-responsive-typography-calculated'];
  for (const n of [c, ...c.querySelectorAll('*')]) {
    for (const a of ['data-fontsize', 'data-lineheight', 'decoding', 'data-orig-src', 'data-orig-sizes', 'srcset', 'sizes', 'loading']) n.removeAttribute(a);
    if ((n.getAttribute('style') || '').startsWith('--fontSize')) n.removeAttribute('style');
    noise.forEach(k => n.classList.remove(k));
    // per-page STATE, not part of the element: the menu item for the page you are on, numbered menu-item classes
    [...n.classList].filter(k => /^(current[-_]|menu-item-\\d+$|fusion-mobile-menu-item-\\d+$|page_item$|page-item-\\d+$|fusion-mobile-current-nav-item$)/.test(k)).forEach(k => n.classList.remove(k));
    if (n.getAttribute('class') === '') n.removeAttribute('class');
  }
  return {look: out, html: el.outerHTML, markup: c.outerHTML};
})"""


def _page_looks(page, definition: dict) -> list[dict]:
    found = page.evaluate(_LOOK_JS, [definition["selector"], definition["parts"], definition.get("part_props") or PART_PROPS, definition.get("rules")])
    for f in found:
        f["look"] = {part: normalize_look(props) for part, props in f["look"].items()}
    return found


def page_instances(page, definition: dict) -> list[dict]:
    """Every placement of the element on the current page: its look (part by part), geometry and generalized markup."""
    looks = _page_looks(page, definition)
    if "photo" in definition["parts"] and "box" in definition["parts"]:
        geoms = page.evaluate(_GEOM_JS, [definition["selector"], definition["parts"]["photo"], definition["parts"]["box"]])
    else:
        geoms = [None] * len(looks)
    return [{"look": l["look"], "geometry": g, "html": l["html"], "markup": normalize_markup(l["markup"]) if definition.get("rules") is not None else None}
            for l, g in zip(looks, geoms)]


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


def _cluster(geoms: list[dict]) -> list[dict]:
    """Geometries that agree to the pixel are one: the representatives of each cluster."""
    reps: list[dict] = []
    for g in geoms:
        g = {k: v for k, v in g.items() if k != "photoWidth"}
        if not any(geometry_close(g, r) for r in reps):
            reps.append(g)
    return reps


def _most_common(items: list):
    from collections import Counter
    return Counter(json.dumps(i, sort_keys=True) for i in items).most_common(1)[0][0] if items else None


def capture(element_id: str = "project-card", base: str = BASE, project: Path = PROJECT, inventory: Path = INVENTORY) -> dict:
    return capture_many([element_id], base, project, inventory)[element_id]


def capture_many(element_ids: list[str], base: str = BASE, project: Path = PROJECT, inventory: Path = INVENTORY) -> dict[str, dict]:
    """Capture several elements in ONE pass over the site (each page is loaded once, not once per element)."""
    from playwright.sync_api import sync_playwright
    pages = [p["url"] for p in json.loads(Path(inventory).read_text())["pages"]]
    acc = {i: {"usage": {}, "geoms": [], "instances": [], "first": None} for i in element_ids}
    provenance: dict[str, dict] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for url in pages:
            page.goto(base + url, wait_until="networkidle")
            page.wait_for_timeout(300)
            for eid in element_ids:
                found = page_instances(page, ELEMENTS[eid])
                if found:
                    a = acc[eid]
                    a["usage"][url] = len(found)
                    a["geoms"] += [f["geometry"] for f in found if f["geometry"]]
                    a["instances"] += [(url, f) for f in found]
                    a["first"] = a["first"] or url
        for eid in element_ids:
            if acc[eid]["first"]:
                page.goto(base + ELEMENTS[eid]["sample_pages"][0], wait_until="networkidle")
                provenance[eid] = _provenance(page, ELEMENTS[eid])
        browser.close()
    return {eid: _finish(eid, acc[eid], provenance.get(eid, {}), project) for eid in element_ids}


def _finish(element_id: str, a: dict, provenance: dict, project: Path) -> dict:
    definition = ELEMENTS[element_id]
    generic = definition.get("rules") is not None            # generalized in the page; the card keeps its own regex path
    instances = a["instances"]
    normalize = (lambda inst: inst["markup"]) if generic else None
    live_markups = [(normalize(i) if normalize else generalize_card(i["html"])) for _, i in instances]
    # The master is the template when the element has one (it is what the generators and the pipeline emit); otherwise
    # the form most placements share.
    master = (template_markup(definition["template"], project) if definition.get("template") else None) \
        or (json.loads(_most_common(live_markups)) if live_markups else None)
    conforming = [i for (_, i), m in zip(instances, live_markups) if m == master]
    looks = distinct_looks([i["look"] for _, i in instances])
    look = json.loads(_most_common([i["look"] for i in conforming] or [i["look"] for _, i in instances])) if instances else None
    geometry = master_geometry(a["geoms"])
    deviations = find_deviations(instances, master, look, geometry, normalize)
    result = {
        "id": element_id, "name": definition["name"], "description": definition["description"],
        "fields": definition["fields"], "markup": master, "look": look,
        "distinct_looks": len(looks), "geometry": geometry,
        "distinct_geometries": 1 + len(_cluster([g for g in a["geoms"] if not geometry_matches(geometry, g)])) if geometry else 0, "deviations": deviations, "provenance": provenance,
        "usage": {"pages": a["usage"], "placements": sum(a["usage"].values())},
        "captured_from": a["first"], "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    out = Path(project) / "templates" / "elements"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{element_id}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def main() -> None:
    ids = sys.argv[1:] or list(ELEMENTS)
    for i, r in capture_many(ids).items():
        print(f"{i}: {r['usage']['placements']} placements on {len(r['usage']['pages'])} pages, {r['distinct_looks']} distinct look(s)")


if __name__ == "__main__":
    main()