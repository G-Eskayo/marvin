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
import html as _html
import json
import re
import sys
from pathlib import Path

PROJECT = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"
ROOT = PROJECT / "templates"

_PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_SLOT = re.compile(r"\{\{@([a-z0-9_-]+)\}\}")
_URL_OK = re.compile(r"^(https?://\S+|/\S*|mailto:\S+)$", re.IGNORECASE)

CATEGORY_PREFIX = {"AI & Machine Learning": "ai-projects", "Cybersecurity": "cybersecurity-projects",
                   "Software Engineering": "software-engineering"}

WRAP_START, WRAP_END = "<!-- hub-sidebar:content-start -->", "<!-- hub-sidebar:content-end -->"


def _load_manifest(root: Path) -> dict:
    return json.loads((Path(root) / "templates.json").read_text())


def _entry(manifest: dict, tid: str) -> dict | None:
    return next((t for t in manifest.get("templates", []) if t["id"] == tid), None)


def _read_template(root: Path, entry: dict) -> str:
    root = Path(root).resolve()
    path = (root / entry["file"]).resolve()
    if root not in path.parents:                       # a manifest entry must not read outside the templates root
        raise ValueError(f"template file escapes the templates root: {entry['file']}")
    return path.read_text()


def _result(html=None, ok=False, missing=None, errors=None, warnings=None, used=None) -> dict:
    return {"ok": ok, "html": html, "missing": missing or [], "errors": errors or [],
            "warnings": warnings or [], "used_options": used or []}


def render(template_id: str, data: dict | None = None, options: dict | None = None, root: Path = ROOT) -> dict:
    data, options = dict(data or {}), dict(options or {})
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
        raw = data.get(name)
        value = "" if raw is None else str(raw)
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
    warnings += [f"unknown field ignored: {k}" for k in data if k not in fields]

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
    return _result(out, ok=not missing and not errors, missing=missing, errors=errors, warnings=warnings, used=used)


def list_templates(root: Path = ROOT) -> list[dict]:
    return _load_manifest(root).get("templates", [])


# ── reference pages: every existing page, for reference ─────────────────────

def extract_page_content(raw: str) -> str:
    """A live page is its own content wrapped by the Hub Sidebar generator. The reference template is
    the page's OWN content: what sits between the generator's content markers, or the raw text."""
    if WRAP_START in raw and WRAP_END in raw:
        return raw.split(WRAP_START, 1)[1].split(WRAP_END, 1)[0].strip()
    return raw


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
        content = extract_page_content((inventory_dir / p["raw"]).read_text())
        (out / f"{p['slug']}.html").write_text(content)
        # a page that is only a navigation parent (e.g. /education/) has genuinely empty content: listed, flagged, not faked
        index.append({"slug": p["slug"], "url": p["url"], "title": p["title"], "type": p["type"],
                      "file": f"reference/{p['slug']}.html", "empty": not content.strip()})
    (out / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    return index


# ── plug-and-play: a whole new project from one data set ────────────────────

def plan_new_project(data: dict, root: Path = ROOT) -> dict:
    """Page content, card markup and the manifest entry for a new project -- deterministic, no writes.
    Applying the manifest entry (it lives in deploy/) stays a reviewed repo change."""
    need = ["title", "slug", "category", "subtitle", "description", "body_html", "hero_image_url", "thumbnail"]
    errors = [f"missing {k}" for k in need if not str(data.get(k, "")).strip()]
    if data.get("category") and data["category"] not in CATEGORY_PREFIX:
        errors.append(f"category must be one of {sorted(CATEGORY_PREFIX)}")
    if data.get("slug") and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", data["slug"]):
        errors.append("slug must be lowercase letters, digits and hyphens")
    if errors:
        return {"ok": False, "errors": errors, "page_html": None, "card_html": None, "manifest_entry": None}
    url = f"/{CATEGORY_PREFIX[data['category']]}/{data['slug']}/"
    page = render("project-page", {"TITLE": data["title"], "SUBTITLE": data["subtitle"], "HERO_IMAGE_URL": data["hero_image_url"],
                                   "BODY_HTML": data["body_html"], "STACK_CSV": data.get("stack_csv", "")},
                  {"actions": data.get("actions", [])}, root)
    card = render("project-card", {"URL": url, "TITLE": data["title"], "THUMBNAIL": data["thumbnail"], "DESCRIPTION": data["description"]}, None, root)
    errors = page["errors"] + card["errors"] + [f"missing {m}" for m in page["missing"] + card["missing"]]
    if errors:
        return {"ok": False, "errors": errors, "page_html": None, "card_html": None, "manifest_entry": None}
    return {"ok": True, "errors": [], "warnings": page["warnings"] + card["warnings"], "page_html": page["html"], "card_html": card["html"],
            "url": url, "manifest_entry": {"title": data["title"], "url": url, "category": data["category"],
                                           "secondary_categories": list(data.get("secondary_categories", [])),
                                           "thumbnail": data["thumbnail"], "description": data["description"]}}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("render"); r.add_argument("id"); r.add_argument("--data", default="{}"); r.add_argument("--options", default="{}")
    n = sub.add_parser("plan"); n.add_argument("--data", required=True)
    args = ap.parse_args()
    if args.cmd == "list":
        print(json.dumps(list_templates(), indent=2))
    elif args.cmd == "render":
        print(json.dumps(render(args.id, json.loads(args.data), json.loads(args.options))))
    else:
        print(json.dumps(plan_new_project(json.loads(args.data))))


if __name__ == "__main__":
    main()
