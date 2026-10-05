#!/usr/bin/env python3
"""Capture PAGE LAYOUTS from the live dev site and say which pages follow them.

A page layout is the frame of a page type: which zones appear, in which order, made of which elements. It is not the
words. Each page's frame is reduced to a skeleton (structure only: tags and the structural classes, the elements it
embeds as tokens, the authored body as one opaque token) and compared with the skeleton of the template for that page
type. A page whose skeleton equals the template's follows the layout; any other is a legacy or hand-built page, with the
difference spelled out. Stored as templates/elements/layout-<type>.json beside the other elements.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_templates as pt  # noqa: E402

HOME = Path.home()
PROJECT = HOME / "Documents" / "Projects" / "portfolio-website-updater"
INVENTORY = HOME / ".claude" / "portfolio" / "inventory" / "inventory.json"
BASE = "http://localhost:8080"

# inventory page type -> (layout id, template id)
LAYOUTS = {
    "project": [("layout-project-page", "project-page"), ("layout-longform-page", "longform-page")],
    "hub": [("layout-hub-page", "hub-page")],
    "all-projects": [("layout-all-projects-page", "all-projects-page")],
}
# the part of the live page that holds the authored content (outside the theme's own header / footer)
ROOT_JS = """() => {
  const side = document.querySelector('.hub-sidebar-content');
  const col = side || document.querySelector('.fusion-column-wrapper') || document.querySelector('.post-content');
  return col ? col.outerHTML : null;
}"""

_STRUCTURAL = re.compile(
    r"^(container|row|col-[a-z]+-\d+|sm-2-items|text-center|h1|h2|h3|pink|section-container|card-container|other|img-responsive|"
    r"btn|btn-default|equal|s12|action-row)$")
_SKIP_TAGS = {"script", "style", "noscript", "br", "svg", "link", "meta"}


def _classes(tag: Tag) -> str:
    return ".".join(sorted(c for c in (tag.get("class") or []) if _STRUCTURAL.match(c)))


def _has_class(tag: Tag, name: str) -> bool:
    return name in (tag.get("class") or [])


def _token(tag: Tag) -> str | None:
    """Elements the layout EMBEDS are tokens: their insides belong to the element, not to the layout."""
    if tag.get("id") == "other-projects-mount":
        return "{other-projects}"
    if _has_class(tag, "col-md-6") and tag.select_one(".card-container-lg"):
        return "{card}"
    if tag.name == "section" and _has_class(tag, "longform-section"):
        return "{section}"                       # a long-form section: the repeating zone; its insides are the author's
    if tag.name == "a" and _has_class(tag, "btn"):
        return "{button}"
    if tag.name == "nav" and _has_class(tag, "hub-sidebar"):
        return "{hub-sidebar}"
    return None


def _is_stack(tag: Tag) -> bool:
    s = tag.find("strong")
    return tag.name == "p" and s is not None and s.get_text(strip=True).lower().startswith("stack")


def _is_action_row(tag: Tag) -> bool:
    """The row of action buttons: the marked action-row, or (older pages) a bare paragraph holding only button links."""
    if _has_class(tag, "action-row"):
        return True
    buttons = tag.find_all("a", class_="btn")
    if tag.name not in ("p", "div") or not buttons:
        return False
    squash = lambda t: re.sub(r"\s+", "", t)
    return squash(tag.get_text()) == squash("".join(b.get_text() for b in buttons))


def _is_blank(tag: Tag) -> bool:
    return tag.name in ("p", "div", "span") and not tag.get_text(strip=True) and not tag.find(["img", "a", "input", "iframe"])


def _walk(node: Tag, body_container: bool = False) -> list[str]:
    """Skeleton lines for a node's children, indented by depth. `body_container` marks the one container whose children
    are the authored body: everything in it collapses to {body}, except the recognised Stack line and action row."""
    out: list[str] = []
    for child in node.children:
        if isinstance(child, (Comment, NavigableString)) or not isinstance(child, Tag):
            continue
        if child.name in _SKIP_TAGS:
            continue
        tok = _token(child)              # an embedded element counts even when it is still empty (the footer mount is filled by script)
        if tok:
            out.append(tok)
            continue
        if _is_blank(child):
            continue
        if body_container:
            if _is_stack(child):
                out.append("{stack}")
            elif _is_action_row(child):
                out.append("{actions}")
            else:
                out.append("{body}")
            continue
        name = child.name + (("." + _classes(child)) if _classes(child) else "")
        # the body container: the div that follows the subtitle block inside the title card
        is_body = child.name == "div" and not _classes(child) and any(_has_class(s, "text-center") and s.find("h3") for s in child.find_previous_siblings("div")[:1])
        inner = _walk(child, body_container=is_body)
        out.append(name + (" [" + " ".join(inner) + "]" if inner else ""))
    return _collapse(out)


def _collapse(items: list[str]) -> list[str]:
    """Runs of identical siblings (a grid of cards, many body blocks) become one entry with a star; a repeating PAIR
    (a category heading followed by its card grid, once per category) becomes one starred pair."""
    out: list[str] = []
    for item in items:
        if out and (out[-1] == item or out[-1] == item + "*"):
            out[-1] = item + "*"
        else:
            out.append(item)
    pairs: list[str] = []
    for item in out:
        pairs.append(item)
        if len(pairs) >= 4 and pairs[-2:] == pairs[-4:-2]:
            unit = f"({pairs[-4]} {pairs[-3]})*"
            del pairs[-4:]
            pairs.append(unit)
        elif len(pairs) >= 3 and pairs[-3].startswith("(") and pairs[-3].endswith(")*") and f"{pairs[-2]} {pairs[-1]}" == pairs[-3][1:-2]:
            del pairs[-2:]                  # one more repetition of an already-starred pair
    return pairs


def skeleton(html: str) -> str:
    """Structure-only form of an authored page frame (see module docstring). Whitespace, text, styling and the theme's own
    wrappers do not matter; the zones and the elements in them do."""
    html = re.sub(r"\[/?fusion_[a-z_]+[^\]]*\]", "", html)             # shortcode tokens are not markup
    soup = BeautifulSoup(f"<root>{html}</root>", "html.parser")
    root = soup.find("root")
    # the theme's builder wrappers and the sidebar wrapper are not part of the page's own frame: descend through them
    node = root
    for _ in range(8):
        kids = [c for c in node.children if isinstance(c, Tag) and c.name not in _SKIP_TAGS and not _is_blank(c)]
        if len(kids) == 1 and not _classes(kids[0]) and kids[0].name in ("div", "section") and not _token(kids[0]):
            node = kids[0]
        elif len(kids) == 1 and any(c.startswith("fusion-") or c in ("hub-sidebar-content",) for c in (kids[0].get("class") or [])):
            node = kids[0]
        else:
            break
    # the authored body is one zone however many blocks it holds
    return re.sub(r"\{(body|section)\}\*", r"{\1}", "\n".join(_walk(node)))


OPTIONAL = ("{actions}",)      # zones a page may omit: a project with no repo or file gets no button row, never an invented one


def _without_optional(sk: str) -> str:
    for token in OPTIONAL:
        sk = re.sub(r"\s?" + re.escape(token), "", sk)
    return sk


def diff_summary(master: str, got: str) -> str:
    """A short human sentence about how a page's skeleton differs from the layout's."""
    master, got = _without_optional(master), _without_optional(got)
    m, g = master.split("\n"), got.split("\n")
    if m == g:
        return ""
    ms, gs = set(re.findall(r"\{[a-z-]+\}", master)), set(re.findall(r"\{[a-z-]+\}", got))
    parts = []
    if ms - gs:
        parts.append("missing " + ", ".join(sorted(ms - gs)))
    if gs - ms:
        parts.append("extra " + ", ".join(sorted(gs - ms)))
    if not parts:
        parts.append("different structure around the same elements")
    return "; ".join(parts)


def master_skeleton(template_id: str, project: Path = PROJECT) -> str:
    spec = pt.specimen(template_id, project / "templates")
    if not spec["ok"]:
        raise RuntimeError(f"the specimen for {template_id} did not render: {spec['errors']}")
    return skeleton(spec["html"])


def capture(base: str = BASE, project: Path = PROJECT, inventory: Path = INVENTORY) -> dict:
    """A page follows the first of its type's layouts whose skeleton it matches (a project page: the short layout or the
    long-form one). A page that follows none is listed under the type's first layout with the reason."""
    from playwright.sync_api import sync_playwright
    pages = json.loads(Path(inventory).read_text())["pages"]
    skeletons: dict[str, tuple[str, str]] = {}                     # url -> (page type, skeleton)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for entry in pages:
            if entry["type"] not in LAYOUTS:
                continue
            page.goto(base + entry["url"], wait_until="networkidle")
            page.wait_for_timeout(300)
            skeletons[entry["url"]] = (entry["type"], skeleton(page.evaluate(ROOT_JS) or ""))
        browser.close()
    masters = {lid: (tid, master_skeleton(tid, project)) for cands in LAYOUTS.values() for lid, tid in cands}
    records: dict[str, dict] = {lid: {} for lid in masters}
    for url, (ptype, sk) in skeletons.items():
        cands = LAYOUTS[ptype]
        followed = next((lid for lid, _ in cands if not diff_summary(masters[lid][1], sk)), None)
        if followed:
            records[followed][url] = {"conforms": True}
        else:
            first = cands[0][0]
            records[first][url] = {"conforms": False, "why": diff_summary(masters[first][1], sk)}
    out_dir = Path(project) / "templates" / "elements"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for lid, verdicts in records.items():
        tid, master = masters[lid]
        record = {
            "id": lid, "kind": "layout", "template": tid,
            "name": tid.replace("-", " ").capitalize() + " layout",
            "description": "The frame of this page type: its zones in order, made of the library's elements. The authored body is free; the zones around it are not.",
            "markup": None, "master_skeleton": master,
            "pages": verdicts, "conforming": sum(1 for v in verdicts.values() if v["conforms"]), "total": len(verdicts),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        (out_dir / f"{lid}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        written[lid] = record
    return written


def main() -> None:
    for lid, r in capture().items():
        print(f"{lid}: {r['conforming']}/{r['total']} pages follow it")
        for url, v in r["pages"].items():
            if not v["conforms"]:
                print(f"   {url}: {v['why']}")


if __name__ == "__main__":
    main()
