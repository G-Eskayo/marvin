#!/usr/bin/env python3
"""Deterministic visual-consistency evaluation for the portfolio site (dev).

Why: the site's project pages drift apart because they are hand-built and nothing
checks them -- measured 2026-10-02: footer cards of differing height overlapping their
heading, 6 GitHub-link wordings in 4 looks, one thumbnail reused by 6 projects. This
is the "Evaluation" in the MARVIN dashboard's Portfolio tab: a headless browser measures
real element geometry and pure rule functions judge it. No model, no tokens.

The "Other Projects" pair is randomised per view, so every rule measures each element
against a rule; none compares to a fixed expected layout.

Rules live in the portfolio repo's templates/design-rules.json (edited from the Portfolio
tab); anything missing falls back to DEFAULT_RULES.

CLI:  portfolio_eval.py [--base http://localhost:8080] [--out PATH] [--json]
"""
from __future__ import annotations
import copy
import json
import sys
from pathlib import Path

PROJECT = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"
RULES_PATH = PROJECT / "templates" / "design-rules.json"
MANIFEST_PATH = PROJECT / "deploy" / "other-projects" / "manifest.json"
RESULT_PATH = Path.home() / ".claude" / "portfolio" / "eval-latest.json"

DEFAULT_RULES = {
    "tolerance_px": 2,
    "footer": {"expected_cards": 2},
    # one card design everywhere: the photo frame height and how far the card overlays the photo (px)
    "card": {"image_height": 240, "overlap": 56},
    "github_button": {"text": "View on GitHub", "classes": ["btn", "btn-default"], "owner": "G-Eskayo"},
    "viewports": [1440, 1100, 390],
    "hub_pages": ["/ai-projects/", "/cybersecurity-projects/", "/software-engineering/", "/all-projects/"],
}


def load_rules(path: Path = RULES_PATH) -> dict:
    """DEFAULT_RULES with the file's values merged over them (one level deep)."""
    rules = copy.deepcopy(DEFAULT_RULES)
    try:
        override = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return rules
    if not isinstance(override, dict):
        return rules
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(rules.get(key), dict):
            rules[key].update(value)
        else:
            rules[key] = value
    return rules


def _finding(rule: str, detail: str, severity: str = "error") -> dict:
    return {"rule": rule, "severity": severity, "detail": detail}


def _overlaps(card: dict, box: dict) -> bool:
    return (card["y"] < box["y"] + box["h"] - 2 and card["y"] + card["h"] > box["y"]
            and card["x"] < box["x"] + box["w"] and card["x"] + card["w"] > box["x"])


def check_footer(cards: list[dict], heading: dict | None, rules: dict) -> list[dict]:
    tol = rules["tolerance_px"]
    out = []
    expected = rules["footer"]["expected_cards"]
    if len(cards) != expected:
        out.append(_finding("footer-card-count", f"{len(cards)} footer card(s), expected {expected}"))
    if len(cards) < 2:
        return out
    heights = [c["h"] for c in cards]
    if max(heights) - min(heights) > tol:
        out.append(_finding("footer-card-height", f"card heights differ: {heights}"))
    tops = [c["y"] for c in cards]
    if max(tops) - min(tops) > tol:
        out.append(_finding("footer-card-alignment", f"cards start at different heights: {tops}"))
    if heading and any(_overlaps(c, heading) for c in cards):
        out.append(_finding("footer-heading-overlap", "a footer card overlaps the 'Other Projects' heading"))
    return out


def check_card_geometry(geoms: list[dict], rules: dict) -> list[dict]:
    """Every project card -- hub grid, All Projects, Other Projects footer -- is the same design: same photo
    frame, same overlay. (Found 2026-10-02: a stray empty paragraph made hub cards overlay 36px, project pages 56px.)"""
    tol, want = rules["tolerance_px"], rules["card"]
    out = []
    for g in geoms:
        if abs(g["overlap"] - want["overlap"]) > tol:
            out.append(_finding("card-overlap", f"card overlays its photo by {g['overlap']}px, expected {want['overlap']}px"))
        if abs(g["imgH"] - want["image_height"]) > tol:
            out.append(_finding("card-photo-frame", f"card photo frame is {g['imgH']}px tall, expected {want['image_height']}px"))
    return out


def check_card_consistency(per_page: dict[str, list[dict]]) -> list[dict]:
    """One card design: across EVERY page, every card has the same RENDERED element structure (elements the CSS
    hides, such as WordPress's empty auto-paragraphs, do not count; extra visible wrappers do) and the same computed typography/button. The most common form is taken as the standard;
    each deviation is reported against it."""
    from collections import Counter
    out: list[dict] = []
    for key, rule in (("sig", "card-markup"), ("look", "card-typography")):
        values = [g[key] for geoms in per_page.values() for g in geoms]
        if not values:
            continue
        standard = Counter(values).most_common(1)[0][0]
        for page, geoms in per_page.items():
            bad = sum(1 for g in geoms if g[key] != standard)
            if bad:
                out.append({"page": page, **_finding(rule, f"{bad} card(s) differ from the site's standard card ({key}): {next(g[key] for g in geoms if g[key] != standard)[:160]}")})
    return out


def load_element(element_id: str, project: Path = PROJECT) -> dict | None:
    """The captured element (templates/elements/<id>.json), or None when it has not been captured yet."""
    try:
        return json.loads((Path(project) / "templates" / "elements" / f"{element_id}.json").read_text())
    except (OSError, ValueError):
        return None


def load_elements(project: Path = PROJECT) -> dict[str, dict]:
    """Every captured element in the library, by id."""
    out = {}
    for f in sorted((Path(project) / "templates" / "elements").glob("*.json")):
        try:
            e = json.loads(f.read_text())
            out[e["id"]] = e
        except (OSError, ValueError, KeyError):
            continue
    return out


def check_element_instances(instances: list[dict], element: dict) -> list[dict]:
    """Every placement of an element must BE the element: the same generalized markup, the same computed look part by
    part, the same geometry. The reference is the captured element (the approved dev-site look), not numbers someone
    typed into a rules file."""
    import portfolio_elements as pe
    out: list[dict] = []
    for inst in instances:
        try:
            got = inst.get("markup") if inst.get("markup") is not None else (pe.generalize_card(inst["html"]) if inst.get("html") else None)
            if got is not None and element.get("markup") and got != element["markup"]:
                out.append(_finding("element-markup", f"a {element['name']} on this page is hand-built, not the element"))
        except ValueError:
            out.append(_finding("element-markup", f"a {element['name']} on this page is not recognisable as the element"))
        want = element.get("look") or {}
        for part, props in want.items():
            have = (inst.get("look") or {}).get(part)
            if props and have != props:
                diff = sorted(k for k in props if (have or {}).get(k) != props[k])
                out.append(_finding("element-look", f"{element['name']} {part} differs from the element: {', '.join(diff) or 'missing'}"))
        geo, want_geo = inst.get("geometry"), element.get("geometry")
        if want_geo and geo and geo != want_geo:
            out.append(_finding("element-geometry", f"{element['name']} geometry {geo} differs from the element's {want_geo}"))
    return out


def check_grid(cards: list[dict], rules: dict) -> list[dict]:
    """Cards in the same row (same top within tolerance) must share one height."""
    tol = rules["tolerance_px"]
    rows: list[list[dict]] = []
    for c in sorted(cards, key=lambda c: c["y"]):
        if rows and abs(rows[-1][0]["y"] - c["y"]) <= tol:
            rows[-1].append(c)
        else:
            rows.append([c])
    out = []
    for row in rows:
        heights = [c["h"] for c in row]
        if len(row) > 1 and max(heights) - min(heights) > tol:
            out.append(_finding("grid-row-height", f"row at y={row[0]['y']} has unequal card heights: {heights}"))
    return out


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def check_github_links(links: list[dict], rules: dict) -> list[dict]:
    """The project's own repository is shown by ONE canonical button. A page with no repo link is fine -- a project
    without a public repo must not be given a fabricated one. Links into other accounts are references and exempt unless
    they wear the canonical button (that would send visitors to the wrong project). Further plain links into the
    project's own repo (a folder, a notebook, "GitHub" in a reference list) are references too: the rule is that the
    page HAS the canonical button, and that nothing else is styled as a button without being one."""
    want_text = _norm(rules["github_button"]["text"])
    want_cls = set(rules["github_button"]["classes"])
    owner = str(rules["github_button"].get("owner", "")).lower()
    out: list[dict] = []
    own: list[dict] = []
    for link in links:
        if owner and link.get("href") and f"github.com/{owner}/" not in str(link["href"]).lower():
            if (_norm(link.get("text", "")) == want_text and want_cls <= set(str(link.get("cls", "")).split())):
                out.append(_finding("github-button-target", f"'View on GitHub' button points at another account's repo: {link['href']}"))
            continue
        own.append(link)

    def canonical(link):
        return _norm(link.get("text", "")) == want_text and want_cls <= set(str(link.get("cls", "")).split())

    if own and not any(canonical(l) for l in own):
        first = own[0]      # the page has an own-repo link but no canonical button: the first one should become it
        if _norm(first.get("text", "")) != want_text:
            out.append(_finding("github-button-text", f"link says {first.get('text')!r}, expected {rules['github_button']['text']!r}"))
        if not want_cls <= set(str(first.get("cls", "")).split()):
            out.append(_finding("github-button-style", f"link {first.get('text')!r} is not styled as the canonical button (classes: {first.get('cls') or 'none'})"))
    for link in own:        # a button-styled own-repo link must be the canonical one, whatever it says
        if "btn" in str(link.get("cls", "")).split() and not canonical(link):
            out.append(_finding("github-button-text", f"button-styled link says {link.get('text')!r}, expected {rules['github_button']['text']!r}"))
    return out


def check_unique_images(thumbnails: dict[str, str]) -> list[dict]:
    by_url: dict[str, list[str]] = {}
    for name, url in thumbnails.items():
        by_url.setdefault(url, []).append(name)
    return [_finding("image-reused", f"{url.rsplit('/', 1)[-1]} is used by {len(names)} projects: {', '.join(names)}")
            for url, names in by_url.items() if len(names) > 1]


def check_overflow(viewport_width: int, scroll_width: int) -> list[dict]:
    if scroll_width - viewport_width > 1:
        return [_finding("page-overflow", f"page is {scroll_width}px wide in a {viewport_width}px viewport")]
    return []


def summarize(findings: list[dict], pages: list[str]) -> dict:
    by_rule: dict[str, int] = {}
    for f in findings:
        by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
    bad_pages = {f["page"] for f in findings if "page" in f}
    return {"by_rule": by_rule, "pages_checked": len(pages), "pages_with_findings": len(bad_pages),
            "clean_pages": [p for p in pages if p not in bad_pages]}


# ── browser collector (thin: measures, never judges) ────────────────────────

_MEASURE_JS = """() => {
  const rect = el => { const r = el.getBoundingClientRect(); return {x: Math.round(r.left), y: Math.round(r.top + scrollY), w: Math.round(r.width), h: Math.round(r.height)}; };
  const heading = [...document.querySelectorAll('h1,h2,h3,h4,div,span')].filter(e => (e.innerText||'').trim() === 'Other Projects' && e.children.length < 2).pop();
  const mount = document.querySelector('#other-projects-mount');
  const cards = [...document.querySelectorAll('.card-container-lg')];
  const inFooter = c => mount && mount.contains(c);
  return {
    viewport: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth,
    heading: heading ? rect(heading) : null,
    cardGeom: cards.map(c => {
      const col = c.parentElement, im = col.querySelector('img'); if (!im) return null;
      const ir = im.getBoundingClientRect(), cs = getComputedStyle(c), btn = c.querySelector('.btn'), desc = c.querySelector('.equal p');
      const noise = /(^| )(lazyloaded|lazyload|lazyloading|ls-is-cached|fusion-responsive-typography-calculated)(?= |$)/g;
      return {
        overlap: Math.round(ir.bottom - c.getBoundingClientRect().top), imgH: Math.round(ir.height),
        sig: [...col.querySelectorAll('*')].filter(e => getComputedStyle(e).display !== 'none' && !e.classList.contains('card-also')).map(e => e.tagName.toLowerCase() + '.' + String(e.className || '').replace(noise, '').trim().replace(/ +/g, '.')).join(' '),
        look: [cs.fontFamily, cs.color, cs.lineHeight, btn ? getComputedStyle(btn).display : '', desc ? getComputedStyle(desc).fontSize : ''].join(' | '),
      };
    }).filter(Boolean),
    footerCards: cards.filter(inFooter).map(rect),
    gridCards: cards.filter(c => !inFooter(c)).map(rect),
    github: [...document.querySelectorAll('a')].filter(a => /github\\.com/.test(a.href) && !a.closest('nav, header, footer, .hub-sidebar'))
              .map(a => ({text: a.innerText.trim(), cls: a.className, href: a.href})),
  };
}"""


def run(base: str = "http://localhost:8080", rules: dict | None = None, manifest_path: Path = MANIFEST_PATH) -> dict:
    """Measure the dev site and return {findings, summary, ...}. Needs Playwright."""
    from playwright.sync_api import sync_playwright
    rules = rules or load_rules()
    manifest = json.loads(Path(manifest_path).read_text())
    projects = {p["title"]: p["url"] for p in manifest}
    findings: list[dict] = []
    library = load_elements()
    element = library.get("project-card")
    pages = list(projects.values()) + list(rules["hub_pages"])
    off_manifest: list[str] = []
    if element:   # pages that carry the card but are not in the manifest (e.g. top-level project pages) get the card rules too
        off_manifest = [u for u in element["usage"]["pages"] if u not in pages]
        pages += off_manifest
    project_like = set(projects.values()) | set(off_manifest)
    # every other element is checked wherever the library saw it (the header and footer: on every page)
    element_pages = {u for e in library.values() for u in e["usage"]["pages"]}
    pages += sorted(element_pages - set(pages))

    card_geoms: dict[str, list[dict]] = {}
    for f in check_unique_images({p["title"]: p["thumbnail"] for p in manifest}):
        findings.append({"page": "(manifest)", **f})

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in rules["viewports"]:
            page = browser.new_page(viewport={"width": width, "height": 900})
            for url in pages:
                page.goto(base + url, wait_until="networkidle")
                m = page.evaluate(_MEASURE_JS)
                label = f"{url} @{width}"
                per_page = check_overflow(m["viewport"], m["scrollWidth"])
                if width >= 1100:   # card geometry rules apply to the desktop layouts
                    import portfolio_elements as pe
                    for eid, el in library.items():
                        if url in el["usage"]["pages"] and eid in pe.ELEMENTS:
                            per_page += check_element_instances(pe.page_instances(page, pe.ELEMENTS[eid]), el)
                    if not element:
                        per_page += check_card_geometry(m["cardGeom"], rules)
                    card_geoms[label] = m["cardGeom"]
                    if url in project_like:
                        per_page += check_footer(m["footerCards"], m["heading"], rules)
                        per_page += check_github_links(m["github"], rules)
                    else:
                        per_page += check_grid(m["gridCards"], rules)
                findings += [{"page": label, **f} for f in per_page]
            page.close()
        browser.close()

    findings += check_card_consistency(card_geoms)
    labels = [f"{u} @{w}" for w in rules["viewports"] for u in pages] + ["(manifest)"]
    return {"base": base, "rules": rules, "findings": findings, "summary": summarize(findings, labels)}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--out", default=str(RESULT_PATH))
    ap.add_argument("--print-rules", action="store_true", help="print the effective rules as JSON and exit")
    args = ap.parse_args()
    if args.print_rules:
        print(json.dumps(load_rules(RULES_PATH)))
        return
    result = run(args.base)
    from datetime import datetime, timezone
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    s = result["summary"]
    print(f"checked {s['pages_checked']} page/viewport combos: {s['pages_with_findings']} with findings")
    for rule, n in sorted(s["by_rule"].items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {rule}")
    print(f"results: {out}")
    sys.exit(1 if result["findings"] else 0)


if __name__ == "__main__":
    main()
