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
    """Every GitHub link must be the one canonical button. A page with no repo link is
    fine -- a project without a public repo must not be given a fabricated one."""
    want_text = _norm(rules["github_button"]["text"])
    want_cls = set(rules["github_button"]["classes"])
    owner = str(rules["github_button"].get("owner", "")).lower()
    out = []
    for link in links:
        # Links into OTHER accounts are references (e.g. "AIMA Python Reference"), not the
        # project's own repo, so the canonical-button rule does not apply to them.
        if owner and link.get("href") and f"github.com/{owner}/" not in str(link["href"]).lower():
            # Not the project's own repo. Normally a reference and exempt -- but if it WEARS the
            # canonical button (text + style), a bulk rewrite has relabelled someone else's repo
            # as "View on GitHub" and sent visitors to the wrong project.
            if (_norm(link.get("text", "")) == want_text and want_cls <= set(str(link.get("cls", "")).split())):
                out.append(_finding("github-button-target", f"'View on GitHub' button points at another account's repo: {link['href']}"))
            continue
        if _norm(link.get("text", "")) != want_text:
            out.append(_finding("github-button-text", f"link says {link.get('text')!r}, expected {rules['github_button']['text']!r}"))
        if not want_cls <= set(str(link.get("cls", "")).split()):
            out.append(_finding("github-button-style", f"link {link.get('text')!r} is not styled as the canonical button (classes: {link.get('cls') or 'none'})"))
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
    pages = list(projects.values()) + list(rules["hub_pages"])

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
                    if url in projects.values():
                        per_page += check_footer(m["footerCards"], m["heading"], rules)
                        per_page += check_github_links(m["github"], rules)
                    else:
                        per_page += check_grid(m["gridCards"], rules)
                findings += [{"page": label, **f} for f in per_page]
            page.close()
        browser.close()

    labels = [f"{u} @{w}" for w in rules["viewports"] for u in pages] + ["(manifest)"]
    return {"base": base, "rules": rules, "findings": findings, "summary": summarize(findings, labels)}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--out", default=str(RESULT_PATH))
    args = ap.parse_args()
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
