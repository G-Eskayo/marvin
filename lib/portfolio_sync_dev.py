#!/usr/bin/env python3
"""The element pipeline: from the repo's source files to a verified dev site, in one run.

What the portfolio's deploy/ folder holds (the card template, its stylesheet and script, the manifest, the mu-plugins) is
what the dev site must serve; nothing used to copy it there, so an edit looked right in one place and stale in another. This
runs the whole chain and records every step:

  1. sync        copy deploy/ files to the dev site's own copy (only files that differ; dev only, never production)
  2. pages       regenerate the hub, All Projects and the sidebars from the manifest and the templates
  3. capture     re-capture every element and every page layout from the live dev site
  4. parity      each element as the dashboard previews it must match the element as the site shows it
  5. evaluate    every page against the elements, the layouts' rules and the site rules

The result goes to ~/.claude/portfolio/pipeline-status.json, which the dashboard's Templates tab shows.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_apply as pa  # noqa: E402

STATUS = Path.home() / ".claude" / "portfolio" / "pipeline-status.json"

# repo path (under deploy/) -> path under the dev site's wp-content/
SYNC_DIRS = {"other-projects": "other-projects", "mu-plugins": "mu-plugins", "longform": "longform", "uploads": "uploads"}
EXCLUDE = ("pipeline-test",)        # deploy-pipeline test markers that exist to prove a deploy, not to be served on dev


def sync_files(project: Path, dev_html: Path) -> list[str]:
    """Copy each file under deploy/<dir>/ to the dev site when it differs. Returns the files that changed."""
    changed = []
    for src_dir, dest_dir in SYNC_DIRS.items():
        src_root = Path(project) / "deploy" / src_dir
        if not src_root.is_dir():
            continue
        for f in sorted(p for p in src_root.rglob("*") if p.is_file() and not any(x in p.name for x in EXCLUDE)):
            dest = Path(dev_html) / "wp-content" / dest_dir / f.relative_to(src_root)
            if dest.exists() and dest.read_bytes() == f.read_bytes():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f.read_bytes())
            changed.append(f"{src_dir}/{f.relative_to(src_root)}")
    return changed


def _step(name: str, fn) -> dict:
    t = time.time()
    try:
        ok, detail = fn()
    except Exception as exc:                              # a step that cannot run is a failed step, not a crashed pipeline
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    return {"name": name, "ok": bool(ok), "detail": detail, "seconds": round(time.time() - t, 1)}


def run(project: Path = pa.PROJECT, dev_html: Path = pa.DEV_HTML, status_path: Path = STATUS, steps: dict | None = None) -> dict:
    """Run the pipeline. `steps` lets a test swap any step; each is a callable returning (ok, detail)."""
    import portfolio_elements as pe
    import portfolio_eval as ev
    import portfolio_layouts as pl
    import portfolio_parity as pp

    def sync():
        changed = sync_files(project, dev_html)
        return True, f"{len(changed)} file(s) updated on the dev site" + (": " + ", ".join(changed) if changed else "")

    def pages():
        return True, f"{len(pa.regenerate_pages(project))} generator step(s) ran"

    def capture():
        done = pe.capture_many(list(pe.ELEMENTS), project=project)
        layouts = pl.capture(project=project)
        return True, f"{len(done)} elements, {len(layouts)} layouts captured"

    def parity():
        results = {i: pp.verify(i) for i in pe.ELEMENTS if (Path(project) / "templates" / "elements" / f"{i}.json").exists()}
        bad = {i: r["differences"] for i, r in results.items() if not r["ok"]}
        return not bad, "every element's dashboard preview matches the live site" if not bad else "; ".join(f"{i}: {d[0]}" for i, d in bad.items())

    def evaluate():
        result = ev.run()
        n = len(result["findings"])
        return n == 0, "no findings" if n == 0 else f"{n} finding(s), first: {result['findings'][0]['rule']} on {result['findings'][0]['page']}"

    plan = {"sync": sync, "pages": pages, "capture": capture, "parity": parity, "evaluate": evaluate, **(steps or {})}
    results = []
    for name, fn in plan.items():
        r = _step(name, fn)
        results.append(r)
        if not r["ok"] and name in ("sync", "pages"):       # later steps would only measure a half-updated site
            break
    out = {"ran_at": datetime.now(timezone.utc).isoformat(), "ok": all(r["ok"] for r in results) and len(results) == len(plan), "steps": results}
    Path(status_path).parent.mkdir(parents=True, exist_ok=True)
    Path(status_path).write_text(json.dumps(out, indent=2))
    return out


def main() -> None:
    out = run()
    print(json.dumps(out))
    sys.exit(0 if out["ok"] else 1)


if __name__ == "__main__":
    main()
