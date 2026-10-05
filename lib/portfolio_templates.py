#!/usr/bin/env python3
"""Deterministic template rendering for portfolio pages and components.

Gil 2026-10-02: uniformity across the whole site, and plug-and-play so MARVIN supplies DATA
instead of regenerating markup (fewer tokens, nothing to drift). Templates are real markup copied
from the site (templates/ in the portfolio repo); templates.json declares each one's fields and the
ALTERNATIVES its slots accept (a GitHub button, a download button, a link...). Rendering is pure
string work -- no model, no network, no writes.

    render("project-page", data, {"actions": [{"template": "button-github", "data": {...}}]})
    plan_new_project({...})   -> page html + card html + manifest entry, from one data set

CLI:  portfolio_templates.py list | render ID [--data JSON] [--options JSON]
"""
from __future__ import annotations
import base64
import html as _html
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_rules  # noqa: E402

PROJECT = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"
ROOT = PROJECT / "templates"

_PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_SLOT = re.compile(r"\{\{@([a-z0-9_-]+)\}\}")
_URL_OK = re.compile(r"^(https?://\S+|/\S*|mailto:\S+)$", re.IGNORECASE)

CATEGORY_PREFIX = portfolio_rules.load_rules()["categories"]     # the live value comes from portfolio_rules.load_rules()

WRAP_START, WRAP_END = "<!-- hub-sidebar:content-start -->", "<!-- hub-sidebar:content-end -->"


def _load_manifest(root: Path) -> dict:
    return json.loads((Path(root) / "templates.json").read_text())


def _entry(manifest: dict, tid: str) -> dict | None:
    return next((t for t in manifest.get("templates", []) if t["id"] == tid), None)


def _read_template(root: Path, entry: dict) -> str:
    root = Path(root).resolve()
    # Lexical check (not resolve()): a template may be a symlink to its single source elsewhere in the repo
    # (the project card lives in deploy/ because the live site fetches it), but it must not name a path outside.
    path = Path(os.path.abspath(root / entry["file"]))
    if root not in path.parents:                       # a manifest entry must not read outside the templates root
        raise ValueError(f"template file escapes the templates root: {entry['file']}")
    return path.read_text()


def _result(html=None, ok=False, missing=None, errors=None, warnings=None, used=None) -> dict:
    return {"ok": ok, "html": html, "missing": missing or [], "errors": errors or [],
            "warnings": warnings or [], "used_options": used or []}


def render(template_id: str, field_values: dict | None = None, options: dict | None = None, root: Path = ROOT, raw: bool = True) -> dict:
    field_values, options = dict(field_values or {}), dict(options or {})
    try:
        manifest = _load_manifest(root)
    except (OSError, ValueError) as exc:
        return _result(errors=[f"cannot read templates.json: {exc}"])
    entry = _entry(manifest, template_id)
    if entry is None:
        return _result(errors=[f"unknown template: {template_id}"])
    try:
        source = _read_template(root, entry)
    except (OSError, ValueError) as exc:
        return _result(errors=[str(exc)])

    fields = {f["name"]: f for f in entry.get("fields", [])}
    missing, errors, warnings = [], [], []
    values: dict[str, str] = {}
    for name, spec in fields.items():
        given = field_values.get(name)       # (not `raw`: that is the render() parameter)
        value = "" if given is None else str(given)
        if not value.strip():
            if spec.get("required"):
                missing.append(name)
            value = str(spec.get("default", ""))
        else:
            if spec.get("type") == "url" and not _URL_OK.match(value):
                errors.append(f"{name}: not a valid URL ({value[:60]!r})")
            if spec.get("pattern") and not re.search(spec["pattern"], value):
                errors.append(f"{name}: does not match the required pattern")
        values[name] = value if spec.get("type") == "html" else _html.escape(value, quote=True)
    warnings += [f"unknown field ignored: {k}" for k in field_values if k not in fields]

    used: list[str] = []
    slots = entry.get("slots", {})
    slot_html: dict[str, str] = {}
    for slot, spec in slots.items():
        parts = []
        for choice in options.get(slot, []) or []:
            tid = choice.get("template")
            if tid not in spec.get("options", []):
                errors.append(f"slot '{slot}': alternative '{tid}' is not allowed here")
                continue
            sub = render(tid, choice.get("data"), None, root)
            errors += [f"{tid}: {e}" for e in sub["errors"]]
            missing += [f"{tid}.{m}" for m in sub["missing"]]
            warnings += [f"{tid}: {w}" for w in sub["warnings"]]
            if sub["html"] is not None:
                parts.append(sub["html"])
                used.append(tid)
        joined = "\n".join(parts)
        # an optional wrapper (e.g. "<p>{content}</p>") that only exists when the slot has content, so a
        # project with no repo does not get a stray empty paragraph
        slot_html[slot] = spec["wrap"].replace("{content}", joined) if joined and spec.get("wrap") else joined
    warnings += [f"unknown slot ignored: {k}" for k in options if k not in slots]

    # A template's LEADING comment is documentation for template authors, not page content: never emit it
    # (it would otherwise be pasted into every generated page). Comments further down are real markup.
    source = re.sub(r"\A\s*<!--.*?-->\s*", "", source, count=1, flags=re.DOTALL)
    out = _SLOT.sub(lambda m: slot_html.get(m.group(1), ""), source)
    out = _PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), out)
    if entry.get("raw") and raw:
        # Avada runs [fusion_text] through wpautop, which sprinkles empty <p> elements into card markup; [fusion_code] emits
        # its (base64) content untouched. bin/_card.py in the portfolio repo does exactly this step for the page generators.
        out = re.sub(r"\[fusion_text\](.*?)\[/fusion_text\]",
                     lambda m: "[fusion_code]" + base64.b64encode(m.group(1).strip().encode()).decode() + "[/fusion_code]", out, flags=re.DOTALL)
    if entry.get("compact"):
        # WordPress turns whitespace between tags into stray empty paragraphs; a compact template is emitted without any
        out = re.sub(r">\s+<", "><", out).strip()
    return _result(out, ok=not missing and not errors, missing=missing, errors=errors, warnings=warnings, used=used)


def _resolve_sample(value, root: Path, depth: int):
    """A specimen value is literal text, or "@template-id" meaning that template's own specimen (so a hub
    page's card list is made of real cards), or a list of those, joined."""
    if isinstance(value, list):
        return "\n".join(_resolve_sample(v, root, depth) for v in value)
    if isinstance(value, str) and value.startswith("@") and depth < 4:
        sub = specimen(value[1:], root, depth + 1)
        return sub["html"] or ""
    return value


def specimen(template_id: str, root: Path = ROOT, depth: int = 0) -> dict:
    """The template rendered with the sample content its manifest entry declares, so the Templates tab can
    show every template as what it IS rather than an empty form."""
    try:
        entry = _entry(_load_manifest(root), template_id)
    except (OSError, ValueError) as exc:
        return _result(errors=[f"cannot read templates.json: {exc}"])
    if entry is None:
        return _result(errors=[f"unknown template: {template_id}"])
    sample = entry.get("specimen") or {}
    data = {k: _resolve_sample(v, root, depth) for k, v in (sample.get("data") or {}).items()}
    options = {
        slot: [{"template": c["template"], "data": {k: _resolve_sample(v, root, depth) for k, v in (c.get("data") or {}).items()}} for c in choices]
        for slot, choices in (sample.get("options") or {}).items()
    }
    first = render(template_id, data, options, root, raw=False)     # the dashboard previews the readable form
    # Some elements are best shown by several samples (a card with a long title and description beside one with short
    # text), so the preview proves the size does not depend on the words.
    extra = [render(template_id, {k: _resolve_sample(v, root, depth) for k, v in d.items()}, options, root, raw=False) for d in sample.get("variants", [])]
    if not extra:
        return first
    parts = [first, *extra]
    return {**first, "ok": all(r["ok"] for r in parts), "html": "".join(r["html"] or "" for r in parts),
            "errors": [e for r in parts for e in r["errors"]], "missing": [m for r in parts for m in r["missing"]]}


def list_templates(root: Path = ROOT) -> list[dict]:
    return _load_manifest(root).get("templates", [])


# ── reference pages: every existing page, for reference ─────────────────────

def extract_page_content(raw: str) -> str:
    """A live page is its own content wrapped by the Hub Sidebar generator. The reference template is
    the page's OWN content: what sits between the generator's content markers, or the raw text."""
    if WRAP_START in raw and WRAP_END in raw:
        return raw.split(WRAP_START, 1)[1].split(WRAP_END, 1)[0].strip()
    return raw


_SHORTCODE = re.compile(r"\[/?[a-zA-Z_][^\]]*\]")


def is_shortcode_only(text: str) -> bool:
    """True when a page's raw markup is nothing but shortcodes (the WP-Coder generations store
    [wp_wow_coder id="5"] and nothing else; the real markup lives in the database)."""
    return len(_SHORTCODE.sub("", text or "").strip()) < 20


def export_reference(inventory_dir: Path, templates_root: Path = ROOT) -> list[dict]:
    """Write one reference template per crawled page (templates/reference/<slug>.html) plus an index.
    Pages whose raw markup could not be read are skipped, never faked."""
    inventory_dir, out = Path(inventory_dir), Path(templates_root) / "reference"
    out.mkdir(parents=True, exist_ok=True)
    pages = json.loads((inventory_dir / "inventory.json").read_text())["pages"]
    index, seen = [], set()
    for p in pages:
        if not p.get("raw") or p["slug"] in seen:
            continue
        seen.add(p["slug"])
        raw = extract_page_content((inventory_dir / p["raw"]).read_text())
        source, content = "raw", raw
        # A shortcode-only page (legacy WP-Coder) tells nobody anything as a reference: use what visitors actually get.
        if is_shortcode_only(raw) and p.get("rendered") and (inventory_dir / p["rendered"]).exists():
            source, content = "rendered", (inventory_dir / p["rendered"]).read_text()
        (out / f"{p['slug']}.html").write_text(content)
        # a page that is only a navigation parent (e.g. /education/) has genuinely empty content: listed, flagged, not faked
        index.append({"slug": p["slug"], "url": p["url"], "title": p["title"], "type": p["type"],
                      "file": f"reference/{p['slug']}.html", "source": source, "empty": not content.strip() or (source == "raw" and is_shortcode_only(content))})
    (out / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    return index


# ── plug-and-play: a whole new project from one data set ────────────────────

def plan_new_project(project: dict, root: Path = ROOT, rules_path: Path | None = None) -> dict:
    """Page content, card markup and the manifest entry for a new project -- deterministic, no writes.
    Applying the manifest entry (it lives in deploy/) stays a reviewed repo change."""
    rules = portfolio_rules.load_rules(rules_path) if rules_path else portfolio_rules.load_rules()
    prefixes = rules["categories"]
    errors = [f"missing {k}" for k in rules["project_spec"]["required"] if not str(project.get(k, "")).strip()]
    if project.get("category") and project["category"] not in prefixes:
        errors.append(f"category must be one of {sorted(prefixes)}")
    if project.get("slug") and not re.fullmatch(rules["project_spec"]["slug_pattern"], project["slug"]):
        errors.append("slug must be lowercase letters, digits and hyphens")
    if errors:
        return {"ok": False, "errors": errors, "page_html": None, "card_html": None, "manifest_entry": None}
    url = f"/{prefixes[project['category']]}/{project['slug']}/"
    page = render("project-page", {"TITLE": project["title"], "SUBTITLE": project["subtitle"], "HERO_IMAGE_URL": project["hero_image_url"],
                                   "BODY_HTML": project["body_html"], "STACK_CSV": project.get("stack_csv", "")},
                  {"actions": project.get("actions", [])}, root)
    card = render("project-card", {"URL": url, "TITLE": project["title"], "THUMBNAIL": project["thumbnail"], "DESCRIPTION": project["description"]}, None, root)
    errors = page["errors"] + card["errors"] + [f"missing {m}" for m in page["missing"] + card["missing"]]
    if errors:
        return {"ok": False, "errors": errors, "page_html": None, "card_html": None, "manifest_entry": None}
    return {"ok": True, "errors": [], "warnings": page["warnings"] + card["warnings"], "page_html": page["html"], "card_html": card["html"],
            "url": url, "manifest_entry": {"title": project["title"], "url": url, "category": project["category"],
                                           "secondary_categories": list(project.get("secondary_categories", [])),
                                           "thumbnail": project["thumbnail"], "description": project["description"]}}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("render"); r.add_argument("id"); r.add_argument("--data", default="{}"); r.add_argument("--options", default="{}")
    sp = sub.add_parser("specimen"); sp.add_argument("id")
    n = sub.add_parser("plan"); n.add_argument("--data", required=True)
    args = ap.parse_args()
    if args.cmd == "list":
        print(json.dumps(list_templates(), indent=2))
    elif args.cmd == "render":
        print(json.dumps(render(args.id, json.loads(args.data), json.loads(args.options))))
    elif args.cmd == "specimen":
        print(json.dumps(specimen(args.id)))
    else:
        print(json.dumps(plan_new_project(json.loads(args.data))))


if __name__ == "__main__":
    main()
