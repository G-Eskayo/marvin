#!/usr/bin/env python3
"""Dashboard-facing API for FLUX image generation and variant management.

Wraps portfolio_flux.py (low-level generation) and portfolio_styles.py (prompts)
for the dashboard's image picker. Handles queuing, listing, choosing, and deleting
variants with style/mood/subject tracking.

CLI: portfolio_flux_images.py catalog
     portfolio_flux_images.py subject SLUG
     portfolio_flux_images.py queue SLUG --style STYLE --mood MOOD --subject SUBJECT
     portfolio_flux_images.py list SLUG
     portfolio_flux_images.py choose SLUG --seed SEED
     portfolio_flux_images.py delete SLUG --seed SEED
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_flux
import portfolio_imagegen
import portfolio_styles

HOME = Path.home()
IMAGES_DIR = HOME / ".claude" / "portfolio" / "images"
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "portfolio" / "image-registry.json"


def catalog() -> dict:
    """Return the styles and moods catalog for image generation.

    Returns {"styles": {...}, "moods": {...}} where each is a dict of name -> description.
    """
    cat = portfolio_styles.load_catalog()
    return {
        "styles": cat.get("styles", {}),
        "moods": cat.get("moods", {}),
    }


def draft_subject(slug: str, manifest_path: Path | None = None) -> str:
    """Lookup and return the public description for a project slug.

    Raises ValueError if the slug has no public description in the manifest.
    """
    description = portfolio_styles.description_for_slug(slug, manifest_path)
    if description is None:
        raise ValueError(f"unknown slug: {slug!r} (not found in manifest or has no description)")
    return portfolio_styles.subject_from_description(description)


def build_and_queue(slug: str, style: str, mood: str, subject: str,
                    target: str = "mac-mini",
                    images_dir: Path = IMAGES_DIR,
                    registry_path: Path = REGISTRY_PATH) -> dict:
    """Validate style/mood, build prompt, queue generation, return result with metadata.

    Returns {"ok": True, "seed": N, "card": "...", "hero": "..."} or {"ok": False, "error": "..."}.
    """
    cat = portfolio_styles.load_catalog()

    if style not in cat.get("styles", {}):
        return {"ok": False, "error": f"unknown style: {style!r}"}
    if mood not in cat.get("moods", {}):
        return {"ok": False, "error": f"unknown mood: {mood!r}"}

    if not subject or not subject.strip() or len(subject.strip()) > 300:
        return {"ok": False, "error": "subject must be non-empty and ≤300 chars"}

    subject = subject.strip()

    prompt = portfolio_styles.build_prompt(subject, style, mood)

    result = portfolio_flux.queued_generate(slug, prompt, target=target, images_dir=images_dir, registry_path=registry_path)

    if not result.ok:
        return {"ok": False, "error": result.error}

    card_path = result.card_path
    hero_path = result.hero_path
    seed = result.seed

    sidecar_path = images_dir / slug / f"flux-{slug}-{seed}.json"
    if sidecar_path.exists():
        sidecar = json.loads(sidecar_path.read_text())
        sidecar["style"] = style
        sidecar["mood"] = mood
        sidecar["subject"] = subject
        sidecar_path.write_text(json.dumps(sidecar, indent=2))

    return {
        "ok": True,
        "seed": seed,
        "card": str(card_path),
        "hero": str(hero_path),
    }


def list_variants(slug: str, images_dir: Path = IMAGES_DIR, registry_path: Path = REGISTRY_PATH) -> dict:
    """Scan and list all FLUX variants for a slug.

    Returns {"variants": [{"seed": N, "card": "...", "hero": "...", "style": "...", "mood": "...", "subject": "...", "chosen": True/False}, ...]}.
    """
    slug_dir = images_dir / slug
    if not slug_dir.exists():
        return {"variants": []}

    variants = []
    registry = portfolio_imagegen._load(registry_path)
    chosen_flux = registry.get(slug, {}).get("flux_chosen")

    for card_file in sorted(slug_dir.glob("flux-card-*.jpg")):
        seed_str = card_file.stem.replace("flux-card-", "")
        try:
            seed = int(seed_str)
        except ValueError:
            continue

        hero_file = slug_dir / f"flux-hero-{seed}.jpg"
        sidecar_file = slug_dir / f"flux-{slug}-{seed}.json"

        if not hero_file.exists():
            continue

        variant = {
            "seed": seed,
            "card": str(card_file),
            "hero": str(hero_file),
            "chosen": seed == chosen_flux,
        }

        if sidecar_file.exists():
            try:
                sidecar = json.loads(sidecar_file.read_text())
                variant["style"] = sidecar.get("style", "")
                variant["mood"] = sidecar.get("mood", "")
                variant["subject"] = sidecar.get("subject", "")
            except (OSError, ValueError):
                pass

        variants.append(variant)

    return {"variants": variants}


def choose(slug: str, seed: int, images_dir: Path = IMAGES_DIR, registry_path: Path = REGISTRY_PATH) -> dict:
    """Mark a FLUX variant as chosen and save its hero crop to images/<slug>.png.

    Returns {"ok": True, "hero": "..."} or {"ok": False, "error": "..."}.
    """
    if not isinstance(seed, int):
        raise TypeError(f"seed must be an integer, got {type(seed).__name__}")
    if seed < 0 or seed > 2**31 - 1:
        raise ValueError(f"seed must be in range [0, {2**31 - 1}], got {seed}")

    slug_dir = images_dir / slug
    hero_file = slug_dir / f"flux-hero-{seed}.jpg"

    if not hero_file.exists():
        return {"ok": False, "error": f"variant not found: flux-hero-{seed}.jpg"}

    sidecar_file = slug_dir / f"flux-{slug}-{seed}.json"
    if not sidecar_file.exists():
        return {"ok": False, "error": f"sidecar not found: flux-{slug}-{seed}.json"}

    try:
        sidecar = json.loads(sidecar_file.read_text())
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"failed to read sidecar: {e}"}

    prompt = sidecar.get("prompt", "")
    style = sidecar.get("style", "")
    mood = sidecar.get("mood", "")
    subject = sidecar.get("subject", "")

    from PIL import Image
    hero_img = Image.open(hero_file)
    hero_hash = portfolio_imagegen.fingerprint(hero_img)

    registry = portfolio_imagegen._load(registry_path)

    registry[slug] = {
        "kind": "flux",
        "seed": seed,
        "prompt": prompt,
        "style": style,
        "mood": mood,
        "subject": subject,
        "hash": f"{hero_hash:x}",
        "chosen": True,
        "flux_chosen": seed,
    }

    Path(registry_path).write_text(json.dumps(registry, indent=2, sort_keys=True))

    hero_output = images_dir.parent / f"{slug}.png"
    hero_img.save(hero_output, quality=95)

    return {
        "ok": True,
        "hero": str(hero_output),
    }


def delete(slug: str, seed: int, images_dir: Path = IMAGES_DIR, registry_path: Path = REGISTRY_PATH) -> dict:
    """Delete a FLUX variant (card, hero, sidecar).

    Refuses if it's the currently chosen variant.
    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    if not isinstance(seed, int):
        raise TypeError(f"seed must be an integer, got {type(seed).__name__}")
    if seed < 0 or seed > 2**31 - 1:
        raise ValueError(f"seed must be in range [0, {2**31 - 1}], got {seed}")

    registry = portfolio_imagegen._load(registry_path)
    chosen_flux = registry.get(slug, {}).get("flux_chosen")

    if seed == chosen_flux:
        return {"ok": False, "error": f"cannot delete chosen variant (seed {seed})"}

    slug_dir = images_dir / slug
    card_file = slug_dir / f"flux-card-{seed}.jpg"
    hero_file = slug_dir / f"flux-hero-{seed}.jpg"
    sidecar_file = slug_dir / f"flux-{slug}-{seed}.json"

    for f in [card_file, hero_file, sidecar_file]:
        if f.exists():
            f.unlink()

    return {"ok": True}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    subparsers = ap.add_subparsers(dest="command", required=True)

    subparsers.add_parser("catalog", help="list available styles and moods")

    subject_parser = subparsers.add_parser("subject", help="draft subject for a project slug")
    subject_parser.add_argument("slug", help="project slug")

    queue_parser = subparsers.add_parser("queue", help="queue a FLUX variant")
    queue_parser.add_argument("slug", help="project slug")
    queue_parser.add_argument("--style", required=True, help="style name")
    queue_parser.add_argument("--mood", required=True, help="mood name")
    queue_parser.add_argument("--subject", required=True, help="subject description")

    list_parser = subparsers.add_parser("list", help="list variants for a slug")
    list_parser.add_argument("slug", help="project slug")

    choose_parser = subparsers.add_parser("choose", help="choose a variant")
    choose_parser.add_argument("slug", help="project slug")
    choose_parser.add_argument("--seed", type=int, required=True, help="variant seed")

    delete_parser = subparsers.add_parser("delete", help="delete a variant")
    delete_parser.add_argument("slug", help="project slug")
    delete_parser.add_argument("--seed", type=int, required=True, help="variant seed")

    args = ap.parse_args()

    if args.command == "catalog":
        result = catalog()
        print(json.dumps(result, indent=2))
    elif args.command == "subject":
        try:
            result = draft_subject(args.slug)
            print(json.dumps({"ok": True, "subject": result}, indent=2))
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}, indent=2), file=sys.stderr)
            sys.exit(1)
    elif args.command == "queue":
        result = build_and_queue(args.slug, args.style, args.mood, args.subject)
        if result["ok"]:
            print(json.dumps(result, indent=2))
            sys.exit(0)
        else:
            print(json.dumps(result, indent=2), file=sys.stderr)
            sys.exit(1)
    elif args.command == "list":
        result = list_variants(args.slug)
        print(json.dumps(result, indent=2))
    elif args.command == "choose":
        result = choose(args.slug, args.seed)
        if result["ok"]:
            print(json.dumps(result, indent=2))
            sys.exit(0)
        else:
            print(json.dumps(result, indent=2), file=sys.stderr)
            sys.exit(1)
    elif args.command == "delete":
        result = delete(args.slug, args.seed)
        if result["ok"]:
            print(json.dumps(result, indent=2))
            sys.exit(0)
        else:
            print(json.dumps(result, indent=2), file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
