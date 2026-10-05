#!/usr/bin/env python3
"""Migrate a LEGACY project page onto the project-page layout, on the DEV site.

Nine project pages are still the old "WP Coder sandwich": an opening WP Coder block (hero, title card, subtitle),
the authored body in a text element, and a closing WP Coder block (footer mount). They look like the layout but are not
built from it, so a change to the layout never reaches them. This extracts what the author wrote (hero, title, subtitle,
body, the project's repository link) and rebuilds the page from templates/project-page.html, which is what every new page
is built from.

Safe by construction: dev site only; the original page and its WP Coder blocks are saved to
~/.claude/outbox/migrations/<slug>/ first and --rollback puts them back; --plan shows the result and writes nothing.
What a human must still supply (a Stack line, if the page never had one) is reported, never invented.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_apply as pa  # noqa: E402
import portfolio_templates as pt  # noqa: E402

OUTBOX = Path.home() / ".claude" / "outbox" / "migrations"
WRAPPER = re.compile(r"<!-- hub-sidebar:wrapper -->.*?<!-- hub-sidebar:content-start -->(.*?)<!-- hub-sidebar:content-end -->.*?<!-- /hub-sidebar:wrapper -->", re.S)
WP_CODE = re.compile(r'\[wp_code id="(\d+)"\]')
GITHUB = re.compile(r'github\.com/G-Eskayo/', re.I)


class MigrationError(Exception):
    pass


def strip_sidebar_wrapper(content: str) -> str:
    m = WRAPPER.search(content)
    return m.group(1).strip() if m else content


def split_sandwich(content: str) -> tuple[list[str], str]:
    """The WP Coder ids in order, and the authored body: the text-element content BETWEEN the first and last block."""
    ids = WP_CODE.findall(content)
    if len(ids) < 2:
        raise MigrationError("not a WP Coder sandwich (expected an opening and a closing [wp_code] block)")
    first = content.index(f'[wp_code id="{ids[0]}"]')
    last = content.rindex(f'[wp_code id="{ids[-1]}"]')
    middle = content[first + len(f'[wp_code id="{ids[0]}"]'):last]
    middle = re.sub(r"\[/?fusion_[a-z_]+[^\]]*\]", "", middle)          # builder shortcodes between the blocks are not content
    return ids, middle.strip()


def read_hero_block(html: str) -> dict:
    """Hero image, title and subtitle from the opening WP Coder block (the markup the layout also uses)."""
    soup = BeautifulSoup(html, "html.parser")
    img = soup.select_one(".col-xs-12 > img") or soup.select_one("img.img-responsive") or soup.select_one("img")
    title = soup.select_one(".card-container .text-center h1, .card-container .text-center h2")
    sub = soup.select_one("h3.pink")
    if not (img and title and sub):
        raise MigrationError("the opening block has no hero image, title and subtitle in the expected places")
    return {"hero_old": img["src"], "title": title.get_text(strip=True), "subtitle": sub.get_text(strip=True)}


def single_block_body(html: str) -> str:
    """Pages built as ONE WP Coder block keep the body inside the block's card: everything in it except the title and the
    subtitle (which the layout supplies). Nothing is dropped; wrapper divs the layout already has are unwrapped."""
    soup = BeautifulSoup(html, "html.parser")
    card = soup.select_one(".card-container")
    if card is None:
        raise MigrationError("could not find the card inside the single WP Coder block")
    title = card.select_one(".text-center h1, .text-center h2")
    sub = card.select_one("h3.pink")
    for el in (title, sub):
        holder = el.find_parent(class_="text-center") if el is not None else None
        if holder is not None and holder.get_text(strip=True) == el.get_text(strip=True):
            holder.decompose()
    node = card
    for _ in range(4):                              # unwrap wrapper divs that hold nothing but the next level
        kids = [c for c in node.children if isinstance(c, Tag) and c.name]
        stray = [c for c in node.children if isinstance(c, NavigableString) and str(c).strip() and not isinstance(c, Comment)]
        if len(kids) == 1 and kids[0].name == "div" and not stray and not kids[0].get("class"):
            node = kids[0]
        else:
            break
    inner = "".join(str(c) for c in node.contents)
    inner = re.sub(r"<!--.*?-->", "", inner, flags=re.S)                # the author's "body goes here" markers
    return inner.strip()


def _meaningful(node) -> bool:
    if isinstance(node, Comment):
        return False
    if isinstance(node, NavigableString):
        return bool(str(node).strip())
    return isinstance(node, Tag) and not (node.name in ("script", "style")) and not node.get("id") == "other-projects-mount" \
        and (bool(node.get_text(strip=True)) or node.find(["img", "video", "iframe", "svg", "figure"]) is not None)


def _heading_text(node) -> str | None:
    """A section heading in the old markup: a centred block holding just an h2."""
    if isinstance(node, Tag) and node.name == "div" and "text-center" in (node.get("class") or []):
        h = node.find("h2")
        if h is not None and node.get_text(strip=True) == h.get_text(strip=True):
            return h.get_text(" ", strip=True)
    return None


def parse_longform_block(html: str) -> dict:
    """A long legacy page held in ONE WP Coder block: the hero and title card, then sections that may sit inside the card
    AND outside it (image/text rows, captions). Returns the hero, the lead (everything before the first heading) and the
    sections in document order, each heading with the blocks under it. No block is dropped."""
    hero = read_hero_block(html)
    soup = BeautifulSoup(html, "html.parser")
    card = soup.select_one(".card-container")
    if card is None:
        raise MigrationError("could not find the card inside the WP Coder block")
    col = card.find_parent(class_="col-xs-12")
    row = col.find_parent(class_="row") if col else None
    container = row.find_parent(class_="container") if row else None
    section = container.find_parent(class_="section-container") if container else None
    after = []
    if row is not None and container is not None:
        after += list(row.next_siblings)
    if container is not None and section is not None:
        after += list(container.next_siblings)
    title = card.select_one(".text-center h1, .text-center h2")      # the FIRST centred h1/h2 is the title; later h2s are sections
    sub = card.select_one("h3.pink")
    for el in (title, sub):                                          # the title and subtitle belong to the layout's frame
        holder = el.find_parent(class_="text-center") if el is not None else None
        if holder is not None and holder.get_text(strip=True) == el.get_text(strip=True):
            holder.decompose()
    node = card
    for _ in range(4):
        kids = [c for c in node.children if isinstance(c, Tag)]
        stray = [c for c in node.children if isinstance(c, NavigableString) and str(c).strip() and not isinstance(c, Comment)]
        if len(kids) == 1 and kids[0].name == "div" and not stray and not kids[0].get("class"):
            node = kids[0]
        else:
            break
    nodes = [c for c in list(node.contents) + after if _meaningful(c)]
    lead, sections = [], []
    for n in nodes:
        heading = _heading_text(n)
        if heading is not None:
            sections.append([heading, []])
        elif sections:
            sections[-1][1].append(str(n))
        else:
            lead.append(str(n))
    if not sections:
        raise MigrationError("no section headings found: a long-form page needs at least one")
    clean = lambda h: re.sub(r"<!--.*?-->", "", h, flags=re.S).strip()
    return {"hero": hero, "lead_html": clean("".join(lead)), "sections": [(h, clean("".join(parts))) for h, parts in sections]}


def own_repo_link(body: str) -> str | None:
    for a in BeautifulSoup(body, "html.parser").find_all("a", href=True):
        if GITHUB.search(a["href"].strip()):
            return a["href"].strip()
    return None


def remove_repo_item(body: str, url: str) -> str:
    """The project's repo link becomes the action button, so its list item leaves the body's Links list (a Links list left
    empty goes too, with its heading)."""
    soup = BeautifulSoup(body, "html.parser")
    for a in soup.find_all("a", href=True):
        if a["href"].strip() == url:
            li = a.find_parent("li")
            if li:
                ul = li.find_parent("ul")
                li.decompose()
                if ul is not None and not ul.find("li"):
                    heading = ul.find_previous_sibling("strong")
                    ul.decompose()
                    if heading is not None and heading.get_text(strip=True).lower().startswith("links"):
                        heading.decompose()
            else:
                parent = a.parent
                a.decompose()
                # "Project Website: <link>" -- the label goes with the link that became the button
                if parent is not None and parent.name in ("div", "p", "span") and re.fullmatch(
                        r"(project website|github|repo(sitory)?|source( code)?)\s*:?", parent.get_text(" ", strip=True), re.I):
                    parent.decompose()
            break
    return str(soup).strip()


def suggest_stack(body: str) -> str | None:
    """A Stack line only if the author already wrote one somewhere; otherwise None (a person supplies it)."""
    m = re.search(r"(?:stack|tools|technologies)\s*:\s*([^<\n]+)", BeautifulSoup(body, "html.parser").get_text("\n"), re.I)
    return m.group(1).strip().rstrip(".") if m else None


def tidy_text(body: str) -> str:
    """Hard-wrapped source text ("...a Real\\n    World\\n    Pentest lab...") becomes ordinary running text. WordPress turns the
    newlines of a page's content into <br> tags, which broke every line mid-sentence. Code, preformatted text and the like
    keep their line breaks."""
    soup = BeautifulSoup(body, "html.parser")
    for node in soup.find_all(string=True):
        if isinstance(node, Comment) or node.find_parent(["pre", "code", "textarea", "script", "style"]):
            continue
        text = str(node)
        if "\n" in text:
            node.replace_with(re.sub(r"[ \t]*\n\s*", " ", text))
    return str(soup)


def build_fields(hero: dict, body: str, slug: str, stack: str | None, hero_url: str | None) -> dict:
    repo = own_repo_link(body)
    actions = [{"template": "button-github", "data": {"REPO_URL": repo}}] if repo else []
    return {
        "fields": {"TITLE": hero["title"], "SUBTITLE": hero["subtitle"], "HERO_IMAGE_URL": hero_url or hero["hero_old"],
                   "BODY_HTML": tidy_text(remove_repo_item(body, repo) if repo else body), "STACK_CSV": stack or suggest_stack(body) or ""},
        "options": {"actions": actions},
    }


def words(html: str) -> list[str]:
    html = re.sub(r"\[/?[a-z_]+[^\]]*\]", "", html)                       # shortcode tokens are not content
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    return re.findall(r"\w+", soup.get_text(" ").lower())


def lost_words(original_html: str, new_html: str) -> list[str]:
    """Words the author wrote that the rebuilt page no longer has (a multiset difference, order ignored)."""
    from collections import Counter
    return list((Counter(words(original_html)) - Counter(words(new_html))).elements())


MAX_LOST = 8        # the removed repo link's own words ("View on GitHub", the label) and nothing more


def render_page(spec: dict, root: Path | None = None, raw: bool = True) -> dict:
    kw = {"root": root} if root else {}
    return pt.render(spec.get("template", "project-page"), spec["fields"], spec["options"], raw=raw, **kw)


def build_longform_fields(parsed: dict, stack: str | None, hero_url: str | None) -> dict:
    """Fields for longform-page.html from a parsed long legacy page: every block kept, the repo link becoming the button."""
    all_html = parsed["lead_html"] + "".join(b for _, b in parsed["sections"])
    repo = own_repo_link(all_html)
    fix = (lambda h: tidy_text(remove_repo_item(h, repo))) if repo else tidy_text
    sections = [pt.render("longform-section", {"HEADING": h, "BODY_HTML": fix(b)}, None, raw=False)["html"] for h, b in parsed["sections"]]
    hero = parsed["hero"]
    return {
        "template": "longform-page",
        "fields": {"TITLE": hero["title"], "SUBTITLE": hero["subtitle"], "HERO_IMAGE_URL": hero_url or hero["hero_old"],
                   "LEAD_HTML": fix(parsed["lead_html"]), "STACK_CSV": stack or suggest_stack(all_html) or "",
                   "SECTIONS_HTML": "\n".join(sections)},
        "options": {"actions": [{"template": "button-github", "data": {"REPO_URL": repo}}] if repo else []},
    }


# ── dev site I/O ────────────────────────────────────────────────────────────

def _wp(runner, *args, input=None):
    return runner(["docker", "exec", "-i", pa.WPCLI, "wp", "--path=/var/www/html", *args], input=input)


def _run(cmd, input=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, input=input)


def find_page(url: str, runner=_run) -> dict:
    r = _wp(runner, "post", "list", "--post_type=page", "--post_status=publish", "--fields=ID,post_name,post_parent", "--format=json")
    if r.returncode != 0:
        raise MigrationError("could not reach the dev site's WordPress (is it running?)")
    pages = json.loads(r.stdout)
    by_id = {str(p["ID"]): p for p in pages}
    for p in pages:
        parts, cur = [p["post_name"]], p
        while str(cur["post_parent"]) != "0" and str(cur["post_parent"]) in by_id:
            cur = by_id[str(cur["post_parent"])]
            parts.append(cur["post_name"])
        if "/" + "/".join(reversed(parts)) + "/" == url:
            return p
    raise MigrationError(f"no page at {url} on the dev site")


def read_wp_code(block_id: str, runner=_run) -> str:
    r = _wp(runner, "eval", f'global $wpdb; echo $wpdb->get_var($wpdb->prepare("SELECT html_code FROM wp_wow_coder WHERE id=%d", {int(block_id)}));')
    if r.returncode != 0:
        raise MigrationError(f"could not read WP Coder block {block_id}")
    return r.stdout


def extract(url: str, stack: str | None = None, runner=_run, layout: str = "project") -> dict:
    page = find_page(url, runner)
    raw = _wp(runner, "post", "get", str(page["ID"]), "--field=post_content").stdout
    content = strip_sidebar_wrapper(raw)
    if layout == "long-form":
        ids = WP_CODE.findall(content)
        if len(ids) != 1:
            raise MigrationError("long-form migration expects the page to be ONE WP Coder block")
        block = read_wp_code(ids[0], runner)
        slug = url.strip("/").split("/")[-1]
        generated = pa.DEV_HTML / pa.UPLOAD_SUBDIR / f"{slug}-hero.jpg"
        hero_url = f"/{pa.UPLOAD_SUBDIR}/{slug}-hero.jpg" if generated.exists() else None
        spec = build_longform_fields(parse_longform_block(block), stack, hero_url)
        return {"page": page, "slug": slug, "url": url, "raw": raw, "blocks": {ids[0]: block}, "wp_code_ids": ids,
                "hero_old": parse_longform_block(block)["hero"]["hero_old"], "spec": spec}
    try:
        ids, body = split_sandwich(content)
        hero = read_hero_block(read_wp_code(ids[0], runner))
    except MigrationError:
        # one WP Coder block holds the whole page (hero, body and closing markup)
        ids = WP_CODE.findall(content)
        if len(ids) != 1:
            raise
        block = read_wp_code(ids[0], runner)
        hero, body = read_hero_block(block), single_block_body(block)
    slug = url.strip("/").split("/")[-1]
    generated = pa.DEV_HTML / pa.UPLOAD_SUBDIR / f"{slug}-hero.jpg"
    hero_url = f"/{pa.UPLOAD_SUBDIR}/{slug}-hero.jpg" if generated.exists() else None
    spec = build_fields(hero, body, slug, stack, hero_url)
    blocks = {i: read_wp_code(i, runner) for i in ids}
    return {"page": page, "slug": slug, "url": url, "raw": raw, "blocks": blocks, "wp_code_ids": ids, "hero_old": hero["hero_old"], "spec": spec}


def migrate(url: str, *, stack: str | None = None, plan: bool = False, outbox: Path = OUTBOX, runner=_run,
            regenerate=pa.regenerate_pages, project: Path = pa.PROJECT, layout: str = "project") -> dict:
    e = extract(url, stack, runner, layout)
    needs = []
    if not e["spec"]["fields"]["STACK_CSV"].strip():
        needs.append("STACK_CSV: the page never had a Stack line; give one with --stack")
    if needs:
        return {"ok": False, "stage": "needs-input", "url": url, "needs": needs}
    rendered = render_page(e["spec"])
    if not rendered["ok"]:
        return {"ok": False, "stage": "render", "url": url, "errors": rendered["errors"] + [f"missing {m}" for m in rendered["missing"]]}
    original = strip_sidebar_wrapper(e["raw"])
    for bid, html in e["blocks"].items():
        original = original.replace(f'[wp_code id="{bid}"]', html)
    readable = render_page(e["spec"], raw=False)["html"]          # the guard reads the page as a visitor does (not the base64 form)
    lost = lost_words(original, readable)
    if len(lost) > MAX_LOST:           # never rebuild a page that would lose what the author wrote
        return {"ok": False, "stage": "content-loss", "url": url, "lost_words": len(lost), "sample": sorted(set(lost))[:25]}
    summary = {"url": url, "page_id": e["page"]["ID"], "title": e["spec"]["fields"]["TITLE"], "subtitle": e["spec"]["fields"]["SUBTITLE"],
               "stack": e["spec"]["fields"]["STACK_CSV"], "hero": e["spec"]["fields"]["HERO_IMAGE_URL"],
               "actions": [a["template"] for a in e["spec"]["options"]["actions"]], "chars_before": len(e["raw"]), "chars_after": len(rendered["html"])}
    if plan:
        return {"ok": True, "plan": True, **summary}
    backup = Path(outbox) / e["slug"]
    backup.mkdir(parents=True, exist_ok=True)
    if not (backup / "before.json").exists():     # the FIRST backup is the original; never overwrite it with an already-migrated page
        (backup / "before.json").write_text(json.dumps({"page_id": e["page"]["ID"], "url": url, "content": e["raw"], "wp_code": e["blocks"]}, indent=2))
    r = _wp(runner, "post", "update", str(e["page"]["ID"]), "-", input=rendered["html"])
    if r.returncode != 0:
        raise MigrationError(f"updating the page failed: {(r.stderr or r.stdout)[-200:]}")
    log = regenerate(project, runner) if regenerate else []          # re-wraps the page with its category sidebar
    return {"ok": True, **summary, "backup": str(backup / "before.json"), "pages_regenerated": len(log)}


def rollback(slug: str, outbox: Path = OUTBOX, runner=_run) -> dict:
    saved = json.loads((Path(outbox) / slug / "before.json").read_text())
    r = _wp(runner, "post", "update", str(saved["page_id"]), "-", input=saved["content"])
    if r.returncode != 0:
        raise MigrationError(f"restoring the page failed: {(r.stderr or r.stdout)[-200:]}")
    return {"ok": True, "restored": saved["url"]}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url", help="the page's URL path, e.g. /ai-projects/anomaly-detection/")
    ap.add_argument("--stack", help="the Stack line, when the page never had one")
    ap.add_argument("--layout", choices=["project", "long-form"], default="project", help="the layout to build the page on")
    ap.add_argument("--plan", action="store_true", help="show what would change; write nothing")
    ap.add_argument("--rollback", action="store_true", help="restore the page saved before migration")
    args = ap.parse_args()
    if args.rollback:
        out = rollback(args.url.strip("/").split("/")[-1])
    else:
        try:
            out = migrate(args.url, stack=args.stack, plan=args.plan, layout=args.layout)
        except MigrationError as exc:                        # a page this tool cannot handle is a normal outcome, not a crash
            out = {"ok": False, "stage": "unsupported", "url": args.url, "reason": str(exc)}
    print(json.dumps(out))
    sys.exit(0 if out.get("ok") else 2)


if __name__ == "__main__":
    main()
