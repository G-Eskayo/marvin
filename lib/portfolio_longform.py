#!/usr/bin/env python3
"""Convert a short project page into a LONG-FORM project page, keeping every word of it.

A short project page keeps the whole story in one card: a lead, then bold headings ("Key Contributions:", "Skills
Demonstrated:", "Links:") over lists. A long-form page gives each of those its own section, with room for figures and
diagrams. This reads a short page, finds its natural sections, and rebuilds it from templates/longform-page.html:

  lead       everything before the first heading
  sections   one per bold heading (a direct <strong>Heading:</strong>, or a block that starts with one), with the blocks
             under it; images stay where they are
  frame      title, subtitle, hero, Stack line and action buttons carry over unchanged

Nothing is invented and nothing is dropped: a conversion that would lose any word is refused, and a page without at least
two headings is left alone (there is nothing to turn into sections). Dev site only; the page is saved to
~/.claude/outbox/migrations/<slug>/before-longform.json first, and --rollback restores it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_apply as pa  # noqa: E402
import portfolio_migrate as pm  # noqa: E402
import portfolio_templates as pt  # noqa: E402

OUTBOX = pm.OUTBOX
BACKUP = "before-longform.json"


class ConversionError(Exception):
    pass


def _heading_of(node) -> tuple[str, list] | None:
    """If `node` starts a section, its heading text and any content it carries along (a block that begins with the heading)."""
    if isinstance(node, Tag) and node.name == "strong":
        t = node.get_text(" ", strip=True)
        if t.endswith(":") and 2 < len(t) < 70:
            return t.rstrip(":").strip(), []
    if isinstance(node, Tag) and node.name in ("h2", "h3", "h4", "h5") and node.get_text(strip=True):
        return node.get_text(" ", strip=True).rstrip(":").strip(), []
    if isinstance(node, Tag) and node.name in ("div", "p", "section"):
        kids = [c for c in node.children if (isinstance(c, Tag) or (isinstance(c, NavigableString) and str(c).strip() and not isinstance(c, Comment)))]
        if kids and isinstance(kids[0], Tag) and kids[0].name == "strong":
            t = kids[0].get_text(" ", strip=True)
            if t.endswith(":") and 2 < len(t) < 70:
                rest = [c for c in node.contents if c is not kids[0]]
                return t.rstrip(":").strip(), rest
    return None


def parse_short_page(content: str) -> dict:
    """The parts of a page built from project-page.html, read back out of its markup."""
    content = pm.strip_sidebar_wrapper(content)
    content = re.sub(r"\[/?fusion_[a-z_]+[^\]]*\]", "", content)
    m = re.fullmatch(r"\s*([A-Za-z0-9+/=\s]+)\s*", content)       # a raw [fusion_code] page is base64: not a short page this tool reads
    soup = BeautifulSoup(content, "html.parser")
    card = soup.select_one(".card-container")
    title, sub = (card.select_one("h1.h2"), card.select_one("h3.pink")) if card else (None, None)
    img = card.find_previous_sibling("img") if card else None
    if not (card and title and sub and img):
        raise ConversionError("not a project-page layout page (no hero, title and subtitle in the expected places)")
    holder = sub.find_parent("div", class_="text-center")
    body = holder.find_next_sibling("div") if holder else None
    if body is None:
        raise ConversionError("could not find the page body")
    stack, actions, nodes = "", [], []
    for child in list(body.children):
        if isinstance(child, Comment):
            continue
        if isinstance(child, Tag) and child.name == "p" and child.find("strong") and child.get_text(strip=True).lower().startswith("stack"):
            stack = re.sub(r"^stack\s*:\s*", "", child.get_text(" ", strip=True), flags=re.I).rstrip(".").strip()
            continue
        if isinstance(child, Tag) and "action-row" in (child.get("class") or []):
            for a in child.find_all("a", class_="btn"):
                href = a.get("href", "").strip()
                actions.append({"template": "button-github", "data": {"REPO_URL": href}} if "github.com" in href
                               else {"template": "button-download", "data": {"FILE_URL": href, "LABEL": a.get_text(strip=True)}})
            continue
        nodes.append(child)
    meaningful = [n for n in nodes if not (isinstance(n, NavigableString) and not str(n).strip())]
    if len(meaningful) == 1 and isinstance(meaningful[0], Tag) and meaningful[0].name == "div":
        nodes = list(meaningful[0].children)                  # the whole body sits in one wrapper div: its contents are the body
    lead, sections = [], []
    for node in nodes:
        if isinstance(node, NavigableString) and not str(node).strip():
            continue
        h = _heading_of(node)
        if h is not None:
            sections.append([h[0], [str(c) for c in h[1]]])
        elif sections:
            sections[-1][1].append(str(node))
        else:
            lead.append(node)

    def lead_html() -> str:
        out = []
        for n in lead:
            if isinstance(n, NavigableString):
                out.append(f"<p>{str(n).strip()}</p>")
            else:
                out.append(str(n))
        return "".join(out)

    return {"title": title.get_text(strip=True), "subtitle": sub.get_text(strip=True), "hero": img["src"], "stack": stack,
            "actions": actions, "lead_html": lead_html(), "sections": [(h, "".join(parts).strip()) for h, parts in sections]}


def build_spec(parsed: dict) -> dict:
    names = [h.lower() for h, _ in parsed["sections"]]
    if len(set(names)) != len(names):
        raise ConversionError("some headings repeat (" + ", ".join(sorted({n for n in names if names.count(n) > 1})) + "): group the blocks by hand")
    if len(parsed["sections"]) < 2:
        raise ConversionError(f"only {len(parsed['sections'])} heading(s) found: not enough structure to make sections from")
    sections = [pt.render("longform-section", {"HEADING": h, "BODY_HTML": pm.tidy_text(b)}, None, raw=False)["html"] for h, b in parsed["sections"]]
    return {"template": "longform-page",
            "fields": {"TITLE": parsed["title"], "SUBTITLE": parsed["subtitle"], "HERO_IMAGE_URL": parsed["hero"], "LEAD_HTML": pm.tidy_text(parsed["lead_html"]),
                       "STACK_CSV": parsed["stack"], "SECTIONS_HTML": "\n".join(sections)},
            "options": {"actions": parsed["actions"]}}


def convert(url: str, *, plan: bool = False, outbox: Path = OUTBOX, runner=pm._run, regenerate=pa.regenerate_pages, project: Path = pa.PROJECT) -> dict:
    page = pm.find_page(url, runner)
    raw = pm._wp(runner, "post", "get", str(page["ID"]), "--field=post_content").stdout
    try:
        parsed = parse_short_page(raw)
        spec = build_spec(parsed)
    except ConversionError as exc:
        return {"ok": False, "stage": "skipped", "url": url, "reason": str(exc)}
    if not spec["fields"]["STACK_CSV"].strip():
        return {"ok": False, "stage": "skipped", "url": url, "reason": "the page has no Stack line to carry over"}
    rendered = pm.render_page(spec)
    if not rendered["ok"]:
        return {"ok": False, "stage": "render", "url": url, "errors": rendered["errors"] + [f"missing {m}" for m in rendered["missing"]]}
    original = pm.strip_sidebar_wrapper(raw)
    lost = pm.lost_words(original, pm.render_page(spec, raw=False)["html"])
    if lost:
        return {"ok": False, "stage": "content-loss", "url": url, "lost_words": len(lost), "sample": sorted(set(lost))[:20]}
    summary = {"url": url, "title": parsed["title"], "lead_words": len(pm.words(parsed["lead_html"])),
               "sections": [h for h, _ in parsed["sections"]], "actions": [a["template"] for a in parsed["actions"]]}
    if plan:
        return {"ok": True, "plan": True, **summary}
    slug = url.strip("/").split("/")[-1]
    backup = Path(outbox) / slug
    backup.mkdir(parents=True, exist_ok=True)
    (backup / BACKUP).write_text(json.dumps({"page_id": page["ID"], "url": url, "content": raw}, indent=2))
    r = pm._wp(runner, "post", "update", str(page["ID"]), "-", input=rendered["html"])
    if r.returncode != 0:
        raise pm.MigrationError(f"updating the page failed: {(r.stderr or r.stdout)[-200:]}")
    log = regenerate(project, runner) if regenerate else []
    return {"ok": True, **summary, "backup": str(backup / BACKUP), "pages_regenerated": len(log)}


def author(url: str, content: dict, *, plan: bool = False, outbox: Path = OUTBOX, runner=pm._run, regenerate=pa.regenerate_pages,
           project: Path = pa.PROJECT) -> dict:
    """Rebuild an existing project page as a long-form page from NEW, authored content (a lead and sections), keeping its
    title, subtitle, hero, Stack line and buttons. For projects whose long form is written, not restructured out of the old
    page. The old page is saved first (before-longform.json), as for a conversion; --rollback restores it."""
    page = pm.find_page(url, runner)
    raw = pm._wp(runner, "post", "get", str(page["ID"]), "--field=post_content").stdout
    try:
        current = parse_short_page(raw)
    except ConversionError as exc:
        return {"ok": False, "stage": "skipped", "url": url, "reason": str(exc)}
    sections = content.get("sections") or []
    if not content.get("lead_html", "").strip() or not sections:
        return {"ok": False, "stage": "invalid", "url": url, "reason": "a lead and at least one section are required"}
    rendered_sections = [pt.render("longform-section", {"HEADING": s["heading"], "BODY_HTML": s["body_html"]}, None, raw=False) for s in sections]
    bad = [e for r in rendered_sections for e in r["errors"] + [f"missing {m}" for m in r["missing"]]]
    if bad:
        return {"ok": False, "stage": "render", "url": url, "errors": bad}
    spec = {"template": "longform-page", "fields": {
        "TITLE": content.get("title") or current["title"], "SUBTITLE": content.get("subtitle") or current["subtitle"],
        "HERO_IMAGE_URL": content.get("hero") or current["hero"], "LEAD_HTML": content["lead_html"], "STACK_CSV": content.get("stack") or current["stack"],
        "SECTIONS_HTML": "\n".join(r["html"] for r in rendered_sections)},
        "options": {"actions": content.get("actions") if content.get("actions") is not None else current["actions"]}}
    rendered = pm.render_page(spec)
    if not rendered["ok"]:
        return {"ok": False, "stage": "render", "url": url, "errors": rendered["errors"] + [f"missing {m}" for m in rendered["missing"]]}
    summary = {"url": url, "sections": [s["heading"] for s in sections], "figures": rendered["html"].count("<img") if False else pm.render_page(spec, raw=False)["html"].count("<img")}
    if plan:
        return {"ok": True, "plan": True, **summary}
    slug = url.strip("/").split("/")[-1]
    backup = Path(outbox) / slug
    backup.mkdir(parents=True, exist_ok=True)
    (backup / BACKUP).write_text(json.dumps({"page_id": page["ID"], "url": url, "content": raw}, indent=2))
    r = pm._wp(runner, "post", "update", str(page["ID"]), "-", input=rendered["html"])
    if r.returncode != 0:
        raise pm.MigrationError(f"updating the page failed: {(r.stderr or r.stdout)[-200:]}")
    log = regenerate(project, runner) if regenerate else []
    return {"ok": True, **summary, "backup": str(backup / BACKUP), "pages_regenerated": len(log)}


def rollback(slug: str, outbox: Path = OUTBOX, runner=pm._run) -> dict:
    saved = json.loads((Path(outbox) / slug / BACKUP).read_text())
    r = pm._wp(runner, "post", "update", str(saved["page_id"]), "-", input=saved["content"])
    if r.returncode != 0:
        raise pm.MigrationError(f"restoring the page failed: {(r.stderr or r.stdout)[-200:]}")
    return {"ok": True, "restored": saved["url"]}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--author", metavar="CONTENT.json", help="rebuild the page from authored content: {lead_html, sections:[{heading, body_html}], stack?, subtitle?}")
    args = ap.parse_args()
    if args.rollback:
        out = rollback(args.url.strip("/").split("/")[-1])
    elif args.author:
        out = author(args.url, json.loads(Path(args.author).read_text()), plan=args.plan)
    else:
        out = convert(args.url, plan=args.plan)
    print(json.dumps(out))
    sys.exit(0 if out.get("ok") else 2)


if __name__ == "__main__":
    main()
