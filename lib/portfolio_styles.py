#!/usr/bin/env python3
"""Style catalog and prompt builder for portfolio image generation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_catalog  # noqa: E402

STYLES_PATH = Path(__file__).resolve().parents[1] / "portfolio" / "image-styles.json"
NO_TEXT_CLAUSE = "no text, no words, no letters, no numbers, no logos, no watermarks"


def load_catalog(path: Path = STYLES_PATH) -> dict:
    """Load styles and moods catalog. Returns {} on missing or corrupt file."""
    try:
        data = json.loads(Path(path).read_text())
        if isinstance(data, dict) and "styles" in data and "moods" in data:
            return data
        return {}
    except (OSError, ValueError):
        return {}


def style_names(path: Path = STYLES_PATH) -> list[str]:
    """List all available style names."""
    catalog = load_catalog(path)
    return list(catalog.get("styles", {}).keys())


def mood_names(path: Path = STYLES_PATH) -> list[str]:
    """List all available mood names."""
    catalog = load_catalog(path)
    return list(catalog.get("moods", {}).keys())


def style_fragment(name: str, path: Path = STYLES_PATH) -> str:
    """Get the style description fragment. Raises ValueError on unknown name."""
    catalog = load_catalog(path)
    if name not in catalog.get("styles", {}):
        raise ValueError(f"unknown style: {name!r}")
    return catalog["styles"][name]


def mood_fragment(name: str, path: Path = STYLES_PATH) -> str:
    """Get the mood description fragment. Raises ValueError on unknown name."""
    catalog = load_catalog(path)
    if name not in catalog.get("moods", {}):
        raise ValueError(f"unknown mood: {name!r}")
    return catalog["moods"][name]


def subject_from_description(description: str) -> str:
    """Generic trim/cleanup of a plain string. Raises on empty/blank input."""
    cleaned = description.strip().rstrip(".")
    if not cleaned:
        raise ValueError("subject cannot be empty or blank")
    return cleaned


def description_for_slug(slug: str, manifest_path: Path | None = None) -> str | None:
    """Lookup the public description for a project slug from the manifest.

    Returns only the 'description' field, never private docs. Returns None if slug not found.
    """
    if manifest_path is None:
        manifest_path = project_catalog.portfolio_repo_path() / "deploy" / "other-projects" / "manifest.json"

    manifest = project_catalog.discover_manifest(manifest_path)
    for entry in manifest:
        url = entry.get("url", "")
        entry_slug = project_catalog.slug(url.rstrip("/").rsplit("/", 1)[-1])
        if entry_slug == slug:
            return entry.get("description")
    return None


def build_prompt(subject: str, style: str, mood: str, path: Path = STYLES_PATH) -> str:
    """Build a complete image generation prompt from subject, style, and mood."""
    style_desc = style_fragment(style, path)
    mood_desc = mood_fragment(mood, path)
    return f"{subject}, {style_desc}, {mood_desc}, {NO_TEXT_CLAUSE}"


def prompt_for_project(slug: str, style: str, mood: str, manifest_path: Path | None = None, path: Path = STYLES_PATH) -> str:
    """Build a prompt for a project slug using its manifest description.

    Raises ValueError if the slug has no public description in the manifest.
    """
    description = description_for_slug(slug, manifest_path)
    if description is None:
        raise ValueError(f"unknown slug: {slug!r} (not found in manifest or has no description)")
    subject = subject_from_description(description)
    return build_prompt(subject, style, mood, path)
