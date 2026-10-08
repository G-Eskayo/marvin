#!/usr/bin/env python3
"""FLUX.1 image generation engine for portfolio projects.

Generates unique, deterministic hero images using FLUX.1-schnell (4-bit quantized) on the mac-mini.
One master image per project, cropped to both card (800x500) and hero (2200x600) formats.
Images are queued (one at a time, ~1 min each), fingerprinted for uniqueness, and re-rolled
if too similar to an existing project's image. Metadata (prompt, seed, settings) is recorded
for reproducibility.

CLI: portfolio_flux.py SLUG --prompt "..." [--seed N]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import job_events
import model_registry
import portfolio_imagegen
import portfolio_rules
import task_dispatch

HOME = Path.home()
IMAGES_DIR = HOME / ".claude" / "portfolio" / "images"
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "portfolio" / "image-registry.json"
LOCK_DIR = HOME / ".claude" / "dispatch" / "locks"
FLUX_LOCK_FILE = LOCK_DIR / "flux-generate.lock"

MASTER_SIZE = (1920, 960)
MIN_DISTANCE = portfolio_rules.load_rules()["images"]["min_distance"]


@dataclass
class DiskCheckResult:
    ok: bool
    error: str = ""


def check_disk_headroom(min_disk_gb: int, download_gb: int) -> DiskCheckResult:
    """Check if free space > download_gb + min_disk_gb buffer. Returns error if insufficient."""
    stat = os.statvfs(HOME)
    free_kb = (stat.f_bavail * stat.f_frsize) // 1024
    free_gb = free_kb / (1024 ** 2)

    required_gb = download_gb + min_disk_gb
    if free_gb < required_gb:
        return DiskCheckResult(
            ok=False,
            error=f"insufficient headroom: {free_gb:.1f} GB free, need {required_gb:.1f} GB (download: {download_gb} GB + buffer: {min_disk_gb} GB)",
        )
    return DiskCheckResult(ok=True)


def get_min_disk_guard() -> int:
    """Load min_disk_gb from config/dispatch.json."""
    config_path = Path(__file__).resolve().parents[1] / "config" / "dispatch.json"
    try:
        data = json.loads(config_path.read_text())
        return data.get("guards", {}).get("min_disk_gb", 15)
    except (OSError, ValueError):
        return 15


def load_dispatch_config() -> dict:
    """Load config/dispatch.json."""
    config_path = Path(__file__).resolve().parents[1] / "config" / "dispatch.json"
    try:
        return json.loads(config_path.read_text())
    except (OSError, ValueError):
        return {}


def crop_card_and_hero(master: object) -> tuple:
    """Extract card and hero crops from a master image (reusing render_map_images.py pattern).

    Master is a PIL Image. Returns (card_img, hero_img) both cropped to the right sizes.
    The crops are centered on the master image to preserve key content.
    """
    from PIL import Image

    rules = portfolio_rules.load_rules()
    card_size = tuple(rules["images"]["thumb_size"])
    hero_size = tuple(rules["images"]["hero_size"])

    w, h = master.width, master.height

    card_w, card_h = card_size
    hero_w, hero_h = hero_size

    left = (w - hero_w) // 2
    top = (h - hero_h) // 2

    hero_box = (left, top, left + hero_w, top + hero_h)
    hero_img = master.crop(hero_box).resize(hero_size, Image.LANCZOS)

    card_left = (w - card_w) // 2
    card_top = (h - card_h) // 2

    card_box = (card_left, card_top, card_left + card_w, card_top + card_h)
    card_img = master.crop(card_box).resize(card_size, Image.LANCZOS)

    return card_img, hero_img


def verify_mflux_help(target: str = "mac-mini") -> task_dispatch.DispatchResult:
    """Before install, run mflux-generate --help on the target to verify flag names."""
    cmd = "~/.agents/venv/bin/mflux-generate --help 2>&1 || echo 'mflux not installed yet'"
    return task_dispatch.dispatch(cmd, target=target, task_label="verify-mflux-flags")


@dataclass
class GenerateResult:
    ok: bool
    image: Optional[object] = None
    seed_used: Optional[int] = None
    settings: Optional[dict] = None
    error: str = ""


def generate(prompt: str, seed: Optional[int] = None, size: tuple = MASTER_SIZE,
             target: str = "mac-mini") -> tuple:
    """Generate an image via mflux on the target mac-mini.

    Returns (image, seed_used, settings) or raises if generation fails.
    The image is a PIL Image of the given size (multiple of 16 for MLX).
    """
    from PIL import Image

    if seed is None:
        import random
        seed = random.randint(0, 2**31 - 1)

    reg = model_registry.ModelRegistry()
    reg.touch_last_used("FLUX.1-schnell-4bit")

    output_path = f"/tmp/flux-{seed}.png"
    cmd = f"""~/.agents/venv/bin/mflux-generate \\
        --prompt "{prompt}" \\
        --seed {seed} \\
        --width {size[0]} \\
        --height {size[1]} \\
        --output "{output_path}" \\
        --steps 20 \\
        --guidance 7.5"""

    result = task_dispatch.dispatch(cmd, target=target, task_label=f"flux-generate-seed{seed}",
                                    timeout=120)

    if not result.ok:
        raise RuntimeError(f"mflux generation failed: {result.error}")

    local_path = Path(output_path)
    if not local_path.exists():
        import subprocess
        scp_cmd = f"scp -o StrictHostKeyChecking=no -o ConnectTimeout=5 {target}:{output_path} {local_path}"
        subprocess.run(scp_cmd.split(), check=True)

    image = Image.open(local_path).convert("RGB")

    settings = {
        "size": list(size),
        "steps": 20,
        "guidance": 7.5,
        "model_build_id": "mflux-4bit-schnell",
    }

    return image, seed, settings


def is_unique(candidate_hash: int, existing_hashes: list[int], min_distance: int) -> bool:
    """Check if candidate is unique (Hamming distance >= min_distance from all existing)."""
    for h in existing_hashes:
        dist = portfolio_imagegen.hamming(candidate_hash, h)
        if dist < min_distance:
            return False
    return True


def record_sidecar(slug: str, prompt: str, seed: int, settings: dict, images_dir: Path = IMAGES_DIR) -> Path:
    """Write JSON sidecar next to the PNG with generation metadata."""
    variant_path = images_dir / slug / f"flux-{slug}-{seed}.json"
    variant_path.parent.mkdir(parents=True, exist_ok=True)

    sidecar = {
        "model_build_id": settings.get("model_build_id", "mflux-4bit"),
        "prompt": prompt,
        "seed": seed,
        "steps": settings.get("steps", 20),
        "guidance": settings.get("guidance", 7.5),
        "master_size": settings.get("size", [1920, 960]),
    }

    variant_path.write_text(json.dumps(sidecar, indent=2))
    return variant_path


@dataclass
class QueuedJobResult:
    ok: bool
    slug: str
    seed: int
    card_path: Optional[Path] = None
    hero_path: Optional[Path] = None
    error: str = ""


def queued_generate(slug: str, prompt: str, seed: Optional[int] = None, target: str = "mac-mini",
                    images_dir: Path = IMAGES_DIR, registry_path: Path = REGISTRY_PATH) -> QueuedJobResult:
    """Generate an image with single-flight lock (one at a time, queued).

    Returns (ok, slug, seed, card_path, hero_path) or (ok=False, error).
    """
    LOCK_DIR.mkdir(parents=True, exist_ok=True)

    with job_events.job_run("flux-generate", label=f"flux-generate-{slug}") as run:
        run.step("queue-lock", f"acquiring lock for {slug}")

        with open(FLUX_LOCK_FILE, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)

            try:
                run.step("disk-check", "verifying free space")
                min_disk_gb = get_min_disk_guard()
                check = check_disk_headroom(min_disk_gb, 8)
                if not check.ok:
                    run.fail(check.error)
                    return QueuedJobResult(ok=False, slug=slug, seed=seed or 0, error=check.error)

                run.step("generate", f"calling mflux for {slug}")
                image, seed_used, settings = generate(prompt, seed, MASTER_SIZE, target)

                run.step("crop", "extracting card and hero from master")
                card_img, hero_img = crop_card_and_hero(image)

                run.step("fingerprint", "checking uniqueness")
                hero_hash = portfolio_imagegen.fingerprint(hero_img)
                registry = portfolio_imagegen._load(registry_path)
                existing_hashes = [int(v["hash"], 16) for v in registry.values()]

                if not is_unique(hero_hash, existing_hashes, MIN_DISTANCE):
                    for retry_seed in range(seed_used + 1, seed_used + 8):
                        image, seed_used, settings = generate(prompt, retry_seed, MASTER_SIZE, target)
                        card_img, hero_img = crop_card_and_hero(image)
                        hero_hash = portfolio_imagegen.fingerprint(hero_img)
                        if is_unique(hero_hash, existing_hashes, MIN_DISTANCE):
                            break

                run.step("save", "writing images and metadata")
                images_dir.mkdir(parents=True, exist_ok=True)
                slug_dir = images_dir / slug
                slug_dir.mkdir(parents=True, exist_ok=True)

                card_path = slug_dir / f"flux-card-{seed_used}.jpg"
                hero_path = slug_dir / f"flux-hero-{seed_used}.jpg"

                card_img.save(card_path, quality=88)
                hero_img.save(hero_path, quality=88)

                sidecar = record_sidecar(slug, prompt, seed_used, settings, images_dir)

                run.summary(f"generated {slug} with seed {seed_used}")

                return QueuedJobResult(
                    ok=True,
                    slug=slug,
                    seed=seed_used,
                    card_path=card_path,
                    hero_path=hero_path,
                )

            except Exception as e:
                error = f"generation failed: {e}"
                run.fail(error)
                return QueuedJobResult(ok=False, slug=slug, seed=seed or 0, error=error)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="project slug")
    ap.add_argument("--prompt", required=True, help="generation prompt (public text from project description)")
    ap.add_argument("--seed", type=int, default=None, help="random seed (optional, auto-generated if omitted)")
    ap.add_argument("--target", default="mac-mini", help="dispatch target machine (default: mac-mini)")
    ap.add_argument("--images-dir", type=Path, default=IMAGES_DIR, help="where to save images")
    ap.add_argument("--registry-path", type=Path, default=REGISTRY_PATH, help="image registry file")

    args = ap.parse_args()

    result = queued_generate(
        args.slug,
        args.prompt,
        args.seed,
        args.target,
        args.images_dir,
        args.registry_path,
    )

    if result.ok:
        print(json.dumps({
            "slug": result.slug,
            "seed": result.seed,
            "card": str(result.card_path),
            "hero": str(result.hero_path),
        }, indent=2))
        sys.exit(0)
    else:
        print(json.dumps({
            "error": result.error,
            "slug": result.slug,
        }, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
