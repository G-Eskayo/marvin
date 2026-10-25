"""FLUX image management layer for dashboard (lib/portfolio_flux_images.py)."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_flux_images as pfi
import portfolio_imagegen


def _png(path, size=(800, 500)):
    """Create a test PNG at the given size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (50, 100, 150)).save(path)
    return path


def test_catalog_returns_styles_and_moods(tmp_path):
    """catalog() returns the styles/moods from portfolio_styles."""
    catalog_file = tmp_path / "image-styles.json"
    catalog_file.write_text(json.dumps({
        "styles": {"blueprint": "blueprint desc", "watercolor": "water desc"},
        "moods": {"calm": "calm desc", "energetic": "energy desc"},
    }))

    with patch("portfolio_flux_images.portfolio_styles.load_catalog", return_value={
        "styles": {"blueprint": "blueprint desc", "watercolor": "water desc"},
        "moods": {"calm": "calm desc", "energetic": "energy desc"},
    }):
        result = pfi.catalog()
        assert "styles" in result
        assert "moods" in result
        assert result["styles"]["blueprint"] == "blueprint desc"
        assert result["moods"]["calm"] == "calm desc"


def test_draft_subject_returns_description_for_slug(tmp_path):
    """draft_subject() returns the public description for a slug."""
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps([
        {"url": "/ai-projects/mancala/", "description": "Plays Mancala", "private": "secret"},
    ]))

    with patch("portfolio_flux_images.portfolio_styles.description_for_slug", return_value="Plays Mancala"):
        result = pfi.draft_subject("mancala", manifest_file)
        assert result == "Plays Mancala"


def test_draft_subject_raises_on_unknown_slug(tmp_path):
    """draft_subject() raises ValueError if slug not found."""
    with patch("portfolio_flux_images.portfolio_styles.description_for_slug", return_value=None):
        with pytest.raises(ValueError, match="unknown slug"):
            pfi.draft_subject("unknown-slug")


def test_build_and_queue_validates_style(tmp_path):
    """build_and_queue() rejects unknown style."""
    catalog = {
        "styles": {"blueprint": "desc"},
        "moods": {"calm": "desc"},
    }

    with patch("portfolio_flux_images.portfolio_styles.load_catalog", return_value=catalog):
        result = pfi.build_and_queue("test-slug", "unknown-style", "calm", "subject")
        assert not result["ok"]
        assert "unknown style" in result["error"]


def test_build_and_queue_validates_mood(tmp_path):
    """build_and_queue() rejects unknown mood."""
    catalog = {
        "styles": {"blueprint": "desc"},
        "moods": {"calm": "desc"},
    }

    with patch("portfolio_flux_images.portfolio_styles.load_catalog", return_value=catalog):
        result = pfi.build_and_queue("test-slug", "blueprint", "unknown-mood", "subject")
        assert not result["ok"]
        assert "unknown mood" in result["error"]


def test_build_and_queue_validates_subject_not_empty():
    """build_and_queue() rejects empty subject."""
    catalog = {
        "styles": {"blueprint": "desc"},
        "moods": {"calm": "desc"},
    }

    with patch("portfolio_flux_images.portfolio_styles.load_catalog", return_value=catalog):
        result = pfi.build_and_queue("test-slug", "blueprint", "calm", "")
        assert not result["ok"]
        assert "subject must be" in result["error"].lower()


def test_build_and_queue_validates_subject_max_length():
    """build_and_queue() rejects subject > 300 chars."""
    catalog = {
        "styles": {"blueprint": "desc"},
        "moods": {"calm": "desc"},
    }

    long_subject = "a" * 301

    with patch("portfolio_flux_images.portfolio_styles.load_catalog", return_value=catalog):
        result = pfi.build_and_queue("test-slug", "blueprint", "calm", long_subject)
        assert not result["ok"]
        assert "≤300 chars" in result["error"]


def test_build_and_queue_queues_and_updates_sidecar(tmp_path):
    """build_and_queue() builds prompt, queues, and updates sidecar with style/mood/subject."""
    images_dir = tmp_path / "images"
    registry_path = tmp_path / "registry.json"

    catalog = {
        "styles": {"blueprint": "blueprint desc"},
        "moods": {"calm": "calm desc"},
    }

    queued_result = MagicMock()
    queued_result.ok = True
    queued_result.seed = 42
    queued_result.card_path = images_dir / "test-slug" / "flux-card-42.jpg"
    queued_result.hero_path = images_dir / "test-slug" / "flux-hero-42.jpg"

    _png(queued_result.card_path)
    _png(queued_result.hero_path)

    sidecar_file = images_dir / "test-slug" / "flux-test-slug-42.json"
    sidecar_file.parent.mkdir(parents=True, exist_ok=True)
    sidecar_file.write_text(json.dumps({
        "model_build_id": "mflux-4bit",
        "prompt": "test subject, blueprint desc, calm desc, no text...",
        "seed": 42,
        "steps": 20,
        "guidance": 7.5,
        "master_size": [2240, 980],
    }))

    with patch("portfolio_flux_images.portfolio_styles.load_catalog", return_value=catalog):
        with patch("portfolio_flux_images.portfolio_flux.queued_generate", return_value=queued_result):
            result = pfi.build_and_queue("test-slug", "blueprint", "calm", "test subject",
                                        images_dir=images_dir, registry_path=registry_path)

    assert result["ok"]
    assert result["seed"] == 42

    updated_sidecar = json.loads(sidecar_file.read_text())
    assert updated_sidecar["style"] == "blueprint"
    assert updated_sidecar["mood"] == "calm"
    assert updated_sidecar["subject"] == "test subject"


def test_list_variants_scans_and_returns_metadata(tmp_path):
    """list_variants() returns all flux variants with metadata from sidecars."""
    images_dir = tmp_path / "images"
    registry_path = tmp_path / "registry.json"

    slug = "test-slug"
    slug_dir = images_dir / slug
    slug_dir.mkdir(parents=True, exist_ok=True)

    card1 = slug_dir / "flux-card-42.jpg"
    hero1 = slug_dir / "flux-hero-42.jpg"
    sidecar1 = slug_dir / "flux-test-slug-42.json"

    _png(card1)
    _png(hero1)
    sidecar1.write_text(json.dumps({
        "prompt": "test prompt",
        "seed": 42,
        "style": "blueprint",
        "mood": "calm",
        "subject": "test subject",
    }))

    registry_path.write_text(json.dumps({
        "other-slug": {"flux_chosen": 999},
    }))

    result = pfi.list_variants(slug, images_dir=images_dir, registry_path=registry_path)

    assert len(result["variants"]) == 1
    variant = result["variants"][0]
    assert variant["seed"] == 42
    assert variant["style"] == "blueprint"
    assert variant["mood"] == "calm"
    assert variant["subject"] == "test subject"
    assert not variant["chosen"]


def test_list_variants_marks_chosen(tmp_path):
    """list_variants() marks the chosen variant with chosen=True."""
    images_dir = tmp_path / "images"
    registry_path = tmp_path / "registry.json"

    slug = "test-slug"
    slug_dir = images_dir / slug
    slug_dir.mkdir(parents=True, exist_ok=True)

    card1 = slug_dir / "flux-card-42.jpg"
    hero1 = slug_dir / "flux-hero-42.jpg"
    sidecar1 = slug_dir / "flux-test-slug-42.json"

    _png(card1)
    _png(hero1)
    sidecar1.write_text(json.dumps({"seed": 42}))

    registry_path.write_text(json.dumps({
        slug: {"flux_chosen": 42},
    }))

    result = pfi.list_variants(slug, images_dir=images_dir, registry_path=registry_path)

    assert len(result["variants"]) == 1
    assert result["variants"][0]["chosen"]


def test_list_variants_returns_empty_if_no_variants(tmp_path):
    """list_variants() returns empty list if no variants exist."""
    images_dir = tmp_path / "images"
    registry_path = tmp_path / "registry.json"

    result = pfi.list_variants("nonexistent-slug", images_dir=images_dir, registry_path=registry_path)

    assert result["variants"] == []


def test_choose_marks_variant_and_saves_hero(tmp_path):
    """choose() marks a variant as chosen and saves hero to images/<slug>.png."""
    images_dir = tmp_path / "images"
    registry_path = tmp_path / "registry.json"

    slug = "test-slug"
    slug_dir = images_dir / slug
    slug_dir.mkdir(parents=True, exist_ok=True)

    hero_file = slug_dir / "flux-hero-42.jpg"
    sidecar_file = slug_dir / "flux-test-slug-42.json"

    _png(hero_file, (2200, 600))
    sidecar_file.write_text(json.dumps({
        "prompt": "test prompt",
        "style": "blueprint",
        "mood": "calm",
        "subject": "test subject",
    }))

    registry_path.write_text(json.dumps({}))

    result = pfi.choose(slug, 42, images_dir=images_dir, registry_path=registry_path)

    assert result["ok"]
    assert (images_dir.parent / f"{slug}.png").exists()

    registry = json.loads(registry_path.read_text())
    assert registry[slug]["kind"] == "flux"
    assert registry[slug]["seed"] == 42
    assert registry[slug]["chosen"]


def test_choose_rejects_invalid_seed():
    """choose() rejects invalid seed (negative, non-int, out of range)."""
    with pytest.raises((ValueError, TypeError, AssertionError)):
        pfi.choose("test-slug", -1)

    with pytest.raises((ValueError, TypeError, AssertionError)):
        pfi.choose("test-slug", "not-a-number")


def test_choose_fails_if_variant_missing(tmp_path):
    """choose() fails if variant files don't exist."""
    images_dir = tmp_path / "images"
    registry_path = tmp_path / "registry.json"

    result = pfi.choose("test-slug", 99, images_dir=images_dir, registry_path=registry_path)

    assert not result["ok"]
    assert "not found" in result["error"].lower()


def test_delete_removes_variant(tmp_path):
    """delete() removes card, hero, and sidecar files."""
    images_dir = tmp_path / "images"
    registry_path = tmp_path / "registry.json"

    slug = "test-slug"
    slug_dir = images_dir / slug
    slug_dir.mkdir(parents=True, exist_ok=True)

    card = slug_dir / "flux-card-42.jpg"
    hero = slug_dir / "flux-hero-42.jpg"
    sidecar = slug_dir / "flux-test-slug-42.json"

    _png(card)
    _png(hero)
    sidecar.write_text(json.dumps({}))

    registry_path.write_text(json.dumps({slug: {"flux_chosen": 99}}))

    result = pfi.delete(slug, 42, images_dir=images_dir, registry_path=registry_path)

    assert result["ok"]
    assert not card.exists()
    assert not hero.exists()
    assert not sidecar.exists()


def test_delete_refuses_chosen_variant(tmp_path):
    """delete() refuses to delete the chosen variant."""
    images_dir = tmp_path / "images"
    registry_path = tmp_path / "registry.json"

    slug = "test-slug"
    slug_dir = images_dir / slug
    slug_dir.mkdir(parents=True, exist_ok=True)

    card = slug_dir / "flux-card-42.jpg"
    hero = slug_dir / "flux-hero-42.jpg"
    sidecar = slug_dir / "flux-test-slug-42.json"

    _png(card)
    _png(hero)
    sidecar.write_text(json.dumps({}))

    registry_path.write_text(json.dumps({slug: {"flux_chosen": 42}}))

    result = pfi.delete(slug, 42, images_dir=images_dir, registry_path=registry_path)

    assert not result["ok"]
    assert "cannot delete chosen" in result["error"].lower()
    assert card.exists()
