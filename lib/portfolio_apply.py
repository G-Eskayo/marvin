#!/usr/bin/env python3
"""Apply the generated images that are IN USE to the portfolio's DEV site.

The Images tab chooses an image per project (portfolio_imagegen); until it is applied, the site still shows the old
shared stock photos. Applying is deliberately dev-only and repeatable:

  1. each in-use image is saved into the dev site's uploads as a 600px-wide thumbnail (and a full-width hero copy)
  2. the project manifest's thumbnails point at them (deploy/other-projects/manifest.json in the repo -- a change to
     review, never pushed from here -- and the dev site's own copy of the manifest, which the footer cards read)
  3. the hub and All Projects pages, which embed thumbnails when generated, are regenerated from the manifest

Nothing here touches production: step 3 talks to the local dev site through a temporary application password that
is created and revoked in the same run.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

HOME = Path.home()
PROJECT = HOME / "Documents" / "Projects" / "portfolio-website-updater"
DEV_HTML = HOME / "portfolio-dev" / "wordpress" / "html"
IMAGES_DIR = HOME / ".claude" / "portfolio" / "images"
UPLOAD_SUBDIR = "wp-content/uploads/generated"
WPCLI = "portfolio-website-updater-wpcli-1"
BASE = "http://localhost:8080"
THUMB_SIZE = (800, 500)      # card-shaped (the photo frame is roughly 3:2), so the cropped site frame loses very little

HUBS = [("AI & Machine Learning", "ai-projects"), ("Cybersecurity", "cybersecurity-projects"), ("Software Engineering", "software-engineering")]


def slug_of(url: str) -> str:
    return url.strip("/").split("/")[-1]


def best_cut(img: Image.Image, aspect: float) -> Image.Image:
    """The crop of the given width:height aspect that holds the most detail, so a wide banner is cut around its subject
    instead of blindly through the middle. Ties (an empty banner) fall back to the centre."""
    import numpy as np
    w, h = img.size
    cw = min(w, round(h * aspect))
    if cw >= w:
        return img
    lum = np.asarray(img.convert("L").resize((w // 8, h // 8)), dtype=np.float32)
    col = lum.sum(axis=0)                                  # brightness per column strip
    win = max(1, cw // 8)
    sums = np.convolve(col, np.ones(win), mode="valid")    # energy of every possible window
    centre = (len(sums) - 1) / 2
    best = int(max(range(len(sums)), key=lambda i: (round(float(sums[i]), 3), -abs(i - centre))))
    x = min(w - cw, best * 8)
    return img.crop((x, 0, x + cw, h))


def publish_images(manifest: list[dict], images_dir: Path, html_dir: Path) -> dict[str, str]:
    """Write each in-use image into the dev uploads. Returns {slug: thumbnail URL} for the ones that exist."""
    out_dir = Path(html_dir) / UPLOAD_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    urls: dict[str, str] = {}
    for entry in manifest:
        slug = slug_of(entry["url"])
        src = Path(images_dir) / f"{slug}.png"
        if not src.exists():
            continue
        img = Image.open(src).convert("RGB")
        thumb = best_cut(img, THUMB_SIZE[0] / THUMB_SIZE[1]).resize(THUMB_SIZE, Image.LANCZOS)
        thumb.save(out_dir / f"{slug}-600w.jpg", quality=90)
        img.save(out_dir / f"{slug}-hero.jpg", quality=90)
        urls[slug] = f"/{UPLOAD_SUBDIR}/{slug}-600w.jpg"
    return urls


def update_manifest_text(text: str, urls: dict[str, str]) -> tuple[str, int]:
    """Point each project's "thumbnail" at its generated image, editing only those values so the file's formatting
    (and so the git diff) stays exactly as it was."""
    changed, current, out = 0, None, []
    for line in text.splitlines(keepends=True):
        m = re.match(r'\s*"url":\s*"([^"]+)"', line)
        if m:
            current = slug_of(m.group(1))
        t = re.match(r'(\s*"thumbnail":\s*")([^"]*)(".*)$', line, flags=re.S)
        if t and current in urls and t.group(2) != urls[current]:
            line = f"{t.group(1)}{urls[current]}{t.group(3)}"
            changed += 1
        out.append(line)
    return "".join(out), changed


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180, **kw)


def regenerate_pages(project: Path = PROJECT, runner=_run) -> list[str]:
    """Regenerate the hub + All Projects pages (and re-wrap their sidebars) on the DEV site. Returns log lines."""
    wp = ["docker", "exec", WPCLI, "wp", "--path=/var/www/html"]
    pages = {}
    listing = runner([*wp, "post", "list", "--post_type=page", "--post_status=publish", "--fields=ID,post_name", "--format=json"])
    if listing.returncode != 0:
        raise RuntimeError("could not list the dev site's pages (is the dev site running?)")
    for p in json.loads(listing.stdout):
        pages[p["post_name"]] = str(p["ID"])
    user = runner([*wp, "user", "list", "--role=administrator", "--field=user_login"]).stdout.split()[0]
    pw = runner([*wp, "user", "application-password", "create", user, "marvin-apply-images", "--porcelain"]).stdout.strip()
    if not pw:
        raise RuntimeError("could not create a temporary dev application password")
    log: list[str] = []
    try:
        steps = [["generate-hub-page.py", BASE, user, pw, pages[slug], cat] for cat, slug in HUBS]
        steps.append(["generate-all-projects-page.py", BASE, user, pw, pages["all-projects"]])
        steps += [["generate-hub-sidebar-pages.py", BASE, user, pw, cat, pages[slug]] for cat, slug in HUBS]
        for step in steps:
            r = runner([sys.executable or "python3", str(project / "bin" / step[0]), *step[1:]])
            if r.returncode != 0:
                raise RuntimeError(f"{step[0]} failed: {(r.stderr or r.stdout)[-300:].replace(pw, '***')}")
            log.append((r.stdout.strip().splitlines() or [step[0]])[-1])
    finally:
        runner([*wp, "user", "application-password", "delete", user, "--all"])
    return log


def apply(project: Path = PROJECT, html_dir: Path = DEV_HTML, images_dir: Path = IMAGES_DIR, runner=_run, regenerate: bool = True) -> dict:
    manifest_file = Path(project) / "deploy" / "other-projects" / "manifest.json"
    text = manifest_file.read_text()
    urls = publish_images(json.loads(text), images_dir, html_dir)
    new_text, changed = update_manifest_text(text, urls)
    if changed:
        manifest_file.write_text(new_text)
    dev_copy = Path(html_dir) / "wp-content" / "other-projects" / "manifest.json"
    dev_copy.parent.mkdir(parents=True, exist_ok=True)
    dev_copy.write_text(new_text)
    log = regenerate_pages(project, runner) if regenerate else []
    return {"images": len(urls), "manifest_changed": changed, "pages": log}


def main() -> None:
    print(json.dumps(apply()))


if __name__ == "__main__":
    main()
