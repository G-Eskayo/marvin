#!/usr/bin/env python3
"""Add a project to the portfolio DEV site from a small spec -- the missing link between a finished project and the
page generators.

Spec in, finished dev-site change out. Everything is deterministic and rule-driven; the only judgment an LLM (or
Gil) supplies is the spec's wording and, optionally, a theme for the generated image. Steps, in order:

  1. validate the spec against the site rules and render the page (no writes; --plan stops here)
  2. generate a unique image for the project and put it on the dev site
  3. create the project page on the dev site, under its category hub
  4. append the project to deploy/other-projects/manifest.json (formatting preserved; a change to REVIEW, never pushed)
  5. regenerate the category hub, All Projects and the sidebars, which now include the new page and its card
  6. evaluate the dev site and report what the new page and the pages it touched look like to the checker

Dev only: it refuses anything but the local dev site. Production promotion is a person's act.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_apply as pa  # noqa: E402
import portfolio_templates as pt  # noqa: E402

HERO_URL = "/{sub}/{slug}-hero.jpg"
THUMB_URL = "/{sub}/{slug}-600w.jpg"


class AddProjectError(Exception):
    pass


def normalise(spec: dict) -> dict:
    """Fill what the site rules decide, so the spec only has to carry what a person writes."""
    s = dict(spec or {})
    s["slug"] = str(s.get("slug") or "").strip()
    actions = list(s.get("actions") or [])
    if s.get("github_url"):
        actions.append({"template": "button-github", "data": {"REPO_URL": s["github_url"]}})
    if s.get("download_url"):
        actions.append({"template": "button-download", "data": {"FILE_URL": s["download_url"], **({"LABEL": s["download_label"]} if s.get("download_label") else {})}})
    # rule: GitHub first, then Download, nothing else
    order = {"button-github": 0, "button-download": 1}
    s["actions"] = sorted((a for a in actions if a.get("template") in order), key=lambda a: order[a["template"]])
    s.setdefault("secondary_categories", [])
    s.setdefault("stack_csv", "")
    s["hero_image_url"] = HERO_URL.format(sub=pa.UPLOAD_SUBDIR, slug=s["slug"])
    s["thumbnail"] = THUMB_URL.format(sub=pa.UPLOAD_SUBDIR, slug=s["slug"])
    return s


def plan(spec: dict, manifest_text: str, templates_root: Path | None = None) -> dict:
    s = normalise(spec)
    kw = {"root": templates_root} if templates_root else {}
    result = pt.plan_new_project(s, **kw)
    if result["ok"]:
        if any(p["url"] == result["url"] for p in json.loads(manifest_text)):
            result = {**result, "ok": False, "errors": [f"{result['url']} is already in the manifest"]}
    return {**result, "spec": s}


def append_manifest_entry(text: str, entry: dict) -> str:
    """Add one entry at the end of the manifest array, matching the file's existing formatting so the repo diff is
    exactly the new entry."""
    body = json.dumps(entry, indent=2, ensure_ascii=False)
    body = "\n".join("  " + line for line in body.splitlines())
    stripped = text.rstrip()
    if not stripped.endswith("]"):
        raise AddProjectError("manifest.json does not end with ]")
    head = stripped[:-1].rstrip()
    sep = "," if head.endswith("}") else ""
    return f"{head}{sep}\n{body}\n]\n"


def _run(cmd, input=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180, input=input)


def create_page(s: dict, content: str, runner=_run) -> int:
    """Create the project page on the dev site under its category hub. Returns the new page's ID."""
    wp = ["docker", "exec", "-i", pa.WPCLI, "wp", "--path=/var/www/html"]
    hub_slug = pt.CATEGORY_PREFIX[s["category"]]
    listing = runner([*wp, "post", "list", "--post_type=page", "--post_status=publish", "--fields=ID,post_name,post_parent", "--format=json"])
    if listing.returncode != 0:
        raise AddProjectError("could not reach the dev site's WordPress (is the dev site running?)")
    pages = json.loads(listing.stdout)
    hub = next((p for p in pages if p["post_name"] == hub_slug and str(p["post_parent"]) == "0"), None)
    if hub is None:
        raise AddProjectError(f"the category hub page /{hub_slug}/ was not found on the dev site")
    if any(p["post_name"] == s["slug"] and str(p["post_parent"]) == str(hub["ID"]) for p in pages):
        raise AddProjectError(f"a page /{hub_slug}/{s['slug']}/ already exists on the dev site")
    r = runner([*wp, "post", "create", "-", "--post_type=page", "--post_status=publish", f"--post_title={s['title']}",
                f"--post_name={s['slug']}", f"--post_parent={hub['ID']}", "--porcelain"], input=content)
    if r.returncode != 0 or not r.stdout.strip().isdigit():
        raise AddProjectError(f"creating the page failed: {(r.stderr or r.stdout)[-200:]}")
    return int(r.stdout.strip())


def add_project(spec: dict, *, dry_run: bool = False, project: Path = pa.PROJECT, html_dir: Path = pa.DEV_HTML,
                images_dir: Path | None = None, registry_path: Path | None = None, runner=_run, regenerate=pa.regenerate_pages, evaluate=None,
                imagegen=None, templates_root: Path | None = None) -> dict:
    manifest_file = Path(project) / "deploy" / "other-projects" / "manifest.json"
    manifest_text = manifest_file.read_text()
    p = plan(spec, manifest_text, templates_root)
    if not p["ok"]:
        return {"ok": False, "stage": "plan", "errors": p["errors"]}
    s = p["spec"]
    steps = ["image", "page", "manifest", "regenerate", "evaluate"]
    if dry_run:
        return {"ok": True, "dry_run": True, "url": p["url"], "steps": steps, "manifest_entry": p["manifest_entry"],
                "warnings": p.get("warnings", []), "page_chars": len(p["page_html"])}

    if imagegen is None:
        import portfolio_imagegen as imagegen
    kw = {k: v for k, v in (("images_dir", images_dir), ("registry_path", registry_path)) if v}
    motif = imagegen._motif_arg(s.get("theme"))
    image = imagegen.pick_unique_variant(s["slug"], motif, None, **kw)
    pa.publish_images([{"url": p["url"]}], images_dir or imagegen.IMAGES_DIR, html_dir)

    page_id = create_page(s, p["page_html"], runner)
    new_text = append_manifest_entry(manifest_text, p["manifest_entry"])
    manifest_file.write_text(new_text)
    dev_copy = Path(html_dir) / "wp-content" / "other-projects" / "manifest.json"
    dev_copy.parent.mkdir(parents=True, exist_ok=True)
    dev_copy.write_text(new_text)

    log = regenerate(project, runner) if regenerate else []
    findings = []
    if evaluate is not None:
        result = evaluate()
        findings = [f for f in result.get("findings", []) if s["slug"] in f.get("page", "")]
    return {"ok": True, "url": p["url"], "page_id": page_id, "image": image, "manifest_entry": p["manifest_entry"],
            "pages_regenerated": log, "findings_for_new_page": findings, "review": "deploy/other-projects/manifest.json (not pushed)"}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--spec", required=True, help="path to the project spec JSON")
    ap.add_argument("--plan", action="store_true", help="validate and show what would happen; write nothing")
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text())

    def evaluate():
        import portfolio_eval
        return portfolio_eval.run()

    out = add_project(spec, dry_run=args.plan, evaluate=evaluate)
    print(json.dumps(out))
    sys.exit(0 if out.get("ok") else 2)


if __name__ == "__main__":
    main()
