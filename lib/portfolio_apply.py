#!/usr/bin/env python3
"""Apply the generated images that are IN USE to the portfolio's DEV site.

The Images tab chooses an image per project (portfolio_imagegen); until it is applied, the site still shows the old
shared stock photos. Applying is deliberately dev-only and repeatable:

  1. each in-use image is saved into the dev site's uploads as a 600px-wide thumbnail (and a full-width hero copy)
  2. the project manifest's thumbnails point at them (deploy/other-projects/manifest.json in the repo -- a change to
     review, never pushed from here -- and the dev site's own copy of the manifest, which the footer cards read)
  3. the hub and All Projects pages, which embed thumbnails when generated, are regenerated from the manifest
  4. each project's page hero image is repointed at the same hero image as its card (so they stay in sync)

Nothing here touches production: step 3 talks to the local dev site through a temporary application password that
is created and revoked in the same run.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_rules  # noqa: E402
import project_catalog  # noqa: E402

HOME = Path.home()
PROJECT = project_catalog.portfolio_repo_path()
DEV_HTML = HOME / "portfolio-dev" / "wordpress" / "html"
IMAGES_DIR = HOME / ".claude" / "portfolio" / "images"
UPLOAD_SUBDIR = "wp-content/uploads/generated"
WPCLI = "portfolio-website-updater-wpcli-1"
# wp-cli runs as this admin: with no user, WordPress filters written HTML (kses) and drops tags such as <source>.
WP_USER = "Gil"
# Absolute fallback: launchd jobs and plain ssh sessions get a PATH without /usr/local/bin, where Docker Desktop links it.
DOCKER = shutil.which("docker") or "/usr/local/bin/docker"


def wp_base(interactive: bool = False) -> list[str]:
    """The wp-cli prefix every portfolio tool uses for the dev site."""
    return [DOCKER, "exec", *(["-i"] if interactive else []), WPCLI, "wp", "--path=/var/www/html", f"--user={WP_USER}"]
BASE = "http://localhost:8080"
THUMB_SIZE = tuple(portfolio_rules.load_rules()["images"]["thumb_size"])   # card-shaped (the photo frame is roughly 3:2)

HUBS = list(portfolio_rules.load_rules()["categories"].items())        # (category, hub page slug)

FUSION_CODE = re.compile(r"\[fusion_code\](.*?)\[/fusion_code\]", re.S)
HERO_IMG = re.compile(r'(<div class="col-xs-12">\s*<img\b[^>]*\bsrc=")([^"]*)(")')


def slug_of(url: str) -> str:
    return url.strip("/").split("/")[-1]


def page_hero_src(raw: str) -> str | None:
    """Decode a page's base64 [fusion_code] if present, then extract the hero img's src.
    Returns None if the markup is not recognized (legacy WP-Coder page, no hero img)."""
    content = raw
    m = FUSION_CODE.search(raw)
    if m:
        try:
            content = base64.b64decode(m.group(1)).decode("utf-8")
        except Exception:
            return None
    match = HERO_IMG.search(content)
    return match.group(2) if match else None


def set_page_hero_src(raw: str, new_src: str) -> tuple[str, bool]:
    """Decode a page's base64 [fusion_code] if present, replace the hero img's src, and re-encode.
    Returns (new_raw, changed) — changed=False when src already matches or no hero img found (idempotent)."""
    current = page_hero_src(raw)
    if current == new_src:
        return raw, False
    if current is None:
        return raw, False
    m = FUSION_CODE.search(raw)
    if m:
        try:
            content = base64.b64decode(m.group(1)).decode("utf-8")
            new_content = HERO_IMG.sub(rf"\g<1>{new_src}\g<3>", content)
            new_raw = raw[:m.start(1)] + base64.b64encode(new_content.encode()).decode() + raw[m.end(1):]
            return new_raw, True
        except Exception:
            return raw, False
    new_raw = HERO_IMG.sub(rf"\g<1>{new_src}\g<3>", raw)
    return new_raw, True


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


def publish_images(manifest: list[dict], images_dir: Path, html_dir: Path, deploy_dir: Path | None = None) -> dict[str, str]:
    """Write each in-use image into the dev uploads, and (when `deploy_dir` is given) into the repo's deploy/ folder too.
    The production deploy only ships deploy/ (to wp-content/), so an image that exists only under the dev site's uploads
    would be a broken thumbnail on the live site. Returns {slug: thumbnail URL} for the ones that exist."""
    out_dirs = [Path(html_dir) / UPLOAD_SUBDIR] + ([Path(deploy_dir) / "uploads" / "generated"] if deploy_dir else [])
    for d in out_dirs:
        d.mkdir(parents=True, exist_ok=True)
    urls: dict[str, str] = {}
    for entry in manifest:
        slug = slug_of(entry["url"])
        src = Path(images_dir) / f"{slug}.png"
        if not src.exists():
            continue
        img = Image.open(src).convert("RGB")
        thumb = best_cut(img, THUMB_SIZE[0] / THUMB_SIZE[1]).resize(THUMB_SIZE, Image.LANCZOS)
        for out_dir in out_dirs:
            thumb.save(out_dir / f"{slug}-600w.jpg", quality=88, optimize=True)
            img.save(out_dir / f"{slug}-hero.jpg", quality=82, optimize=True)
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
    wp = wp_base()
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
    manifest = json.loads(text)
    urls = publish_images(manifest, images_dir, html_dir, Path(project) / "deploy")
    new_text, changed = update_manifest_text(text, urls)
    if changed:
        manifest_file.write_text(new_text)
    dev_copy = Path(html_dir) / "wp-content" / "other-projects" / "manifest.json"
    dev_copy.parent.mkdir(parents=True, exist_ok=True)
    dev_copy.write_text(new_text)

    heroes_fixed, hero_warnings = 0, []
    if urls:
        from portfolio_migrate import find_page, MigrationError  # local import to avoid circular dependency
        try:
            wp = wp_base()
            pages_r = runner([*wp, "post", "list", "--post_type=page", "--post_status=publish", "--fields=ID,post_name,post_parent", "--format=json"])
            if pages_r.returncode == 0:
                pages = json.loads(pages_r.stdout)
                for entry in manifest:
                    slug = slug_of(entry["url"])
                    if slug not in urls:
                        continue
                    try:
                        page = find_page(entry["url"], runner, pages=pages)
                        raw = runner([*wp, "post", "get", str(page["ID"]), "--field=post_content"]).stdout
                        new_raw, hero_changed = set_page_hero_src(raw, f"/{UPLOAD_SUBDIR}/{slug}-hero.jpg")
                        if hero_changed:
                            runner([*wp, "post", "update", str(page["ID"]), "-"], input=new_raw)
                            heroes_fixed += 1
                    except MigrationError as e:
                        hero_warnings.append(f"{slug}: {str(e)}")
        except Exception as e:
            hero_warnings.append(f"hero sync failed: {str(e)}")

    log = regenerate_pages(project, runner) if regenerate else []
    return {"images": len(urls), "manifest_changed": changed, "heroes_fixed": heroes_fixed, "hero_warnings": hero_warnings, "pages": log}


def main() -> None:
    print(json.dumps(apply()))


if __name__ == "__main__":
    main()
