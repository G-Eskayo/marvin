"""Deterministic generative hero images for portfolio projects.

Decided 2026-10-02: unique art keyed to each project's slug (same slug -> same image),
black-and-white to match the site, zero API cost. A project's existing images are NEVER
the key photo -- they only INSPIRE the generator (measured brightness/contrast/tint steer
its parameters). Found because 6 of 17 projects shared one stock thumbnail.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portfolio_imagegen as ig  # noqa: E402

SLUGS = ["marketplace-ml-agent", "algorithms", "mancala", "random-number", "regression-and-classification",
         "anomaly-detection", "resume-selector", "mitre", "pipeline", "bug-bounty", "skineedipping",
         "helicopter-crutches", "clarity-captions", "killer-sudoku", "marvin", "resume-tailor", "paper-dive"]
SMALL = (440, 120)   # same pipeline as production size, 25x fewer pixels, so the suite stays fast


def arr(img):
    return np.asarray(img)


def test_same_slug_gives_exactly_the_same_image():
    assert np.array_equal(arr(ig.render("mancala", size=SMALL)), arr(ig.render("mancala", size=SMALL)))


def test_different_slugs_give_different_images():
    assert not np.array_equal(arr(ig.render("mancala", size=SMALL)), arr(ig.render("mitre", size=SMALL)))


def test_every_real_project_slug_is_perceptually_distinct_from_every_other_once_assigned(tmp_path):
    # Raw renders of same-style slugs can land close on a coarse 64-bit hash (killer-sudoku vs
    # marvin: distance 5, though their pixels differ strongly). Distinctness is what assign()
    # GUARANTEES by re-rolling with a salt -- so that is what is asserted, not luck.
    out = ig.assign(SLUGS, registry_path=tmp_path / "r.json", size=SMALL)
    hashes = {s: int(v["hash"], 16) for s, v in out.items()}
    worst = min(ig.hamming(hashes[a], hashes[b]) for i, a in enumerate(SLUGS) for b in SLUGS[i + 1:])
    assert worst >= ig.MIN_DISTANCE
    assert not any("warning" in v for v in out.values())


def test_output_has_the_requested_size_and_is_rgb():
    img = ig.render("mancala", size=(440, 120))
    assert img.size == (440, 120) and img.mode == "RGB"


def test_production_size_defaults_to_the_sites_wide_panorama():
    assert ig.HERO_SIZE == (2200, 600)


def test_thumbnail_is_600_wide_and_keeps_the_aspect_ratio():
    t = ig.thumbnail(ig.render("mancala", size=(2200 // 5, 600 // 5)), width=600)
    assert t.size[0] == 600 and abs(t.size[1] - round(600 * 120 / 440)) <= 1


def test_the_generator_uses_several_distinct_styles_across_projects():
    assert len({ig.style_for(s) for s in SLUGS}) >= 3


def test_images_stay_in_the_sites_black_and_white_aesthetic():
    img = arr(ig.render("mancala", size=SMALL)).astype(int)
    chroma = (img.max(axis=2) - img.min(axis=2)).mean()
    assert chroma < 30            # at most a faint tint, never colourful


# ── inspiration, never the key photo ────────────────────────────────────────

def _photo(tmp_path, level, name="p.png", noise=0):
    rng = np.random.RandomState(1)
    a = np.full((120, 440, 3), level, dtype=np.uint8)
    if noise:
        a = np.clip(a.astype(int) + rng.randint(-noise, noise + 1, a.shape), 0, 255).astype(np.uint8)
    p = tmp_path / name
    Image.fromarray(a).save(p)
    return p


def test_inspiration_measures_brightness_contrast_and_tint(tmp_path):
    dark = ig.inspiration_from([_photo(tmp_path, 30, "d.png")])
    bright = ig.inspiration_from([_photo(tmp_path, 220, "b.png")])
    assert dark["luminance"] < 0.2 < 0.8 < bright["luminance"]
    assert set(dark) >= {"luminance", "contrast", "hue", "saturation"}


def test_inspiration_from_no_usable_images_is_neutral_not_an_error(tmp_path):
    assert ig.inspiration_from([]) == ig.NEUTRAL_INSPIRATION
    assert ig.inspiration_from([tmp_path / "missing.png"]) == ig.NEUTRAL_INSPIRATION


def test_inspiration_steers_the_output_so_a_dark_project_renders_darker_than_a_bright_one(tmp_path):
    dark = ig.inspiration_from([_photo(tmp_path, 25, "d.png")])
    bright = ig.inspiration_from([_photo(tmp_path, 235, "b.png")])
    d = arr(ig.render("mancala", size=SMALL, inspiration=dark)).mean()
    b = arr(ig.render("mancala", size=SMALL, inspiration=bright)).mean()
    assert d < b - 15


def test_same_slug_and_same_inspiration_is_still_deterministic(tmp_path):
    insp = ig.inspiration_from([_photo(tmp_path, 90, "m.png", noise=40)])
    assert np.array_equal(arr(ig.render("mancala", size=SMALL, inspiration=insp)),
                          arr(ig.render("mancala", size=SMALL, inspiration=insp)))


def test_the_output_is_never_a_copy_of_the_source_photo(tmp_path):
    src = _photo(tmp_path, 120, "src.png", noise=60)
    out = ig.render("mancala", size=SMALL, inspiration=ig.inspiration_from([src]))
    assert ig.hamming(ig.dhash(Image.open(src)), ig.dhash(out)) >= ig.MIN_DISTANCE
    assert not np.array_equal(arr(Image.open(src).resize(SMALL)), arr(out))


# ── registry: stable assignment, collision handling ─────────────────────────

def test_assign_records_each_slug_with_its_hash_and_is_stable_across_calls(tmp_path):
    reg = tmp_path / "registry.json"
    a = ig.assign(["mancala", "mitre"], registry_path=reg, size=SMALL)
    b = ig.assign(["mancala", "mitre"], registry_path=reg, size=SMALL)
    assert a == b
    saved = json.loads(reg.read_text())
    assert set(saved) == {"mancala", "mitre"} and all("hash" in v and "salt" in v for v in saved.values())


def test_adding_a_new_project_never_changes_an_existing_projects_image(tmp_path):
    reg = tmp_path / "registry.json"
    before = ig.assign(["mancala"], registry_path=reg, size=SMALL)["mancala"]
    after = ig.assign(["mancala", "mitre", "paper-dive"], registry_path=reg, size=SMALL)["mancala"]
    assert before == after


def test_a_collision_with_an_already_assigned_image_is_resolved_with_a_salt(tmp_path, monkeypatch):
    reg = tmp_path / "registry.json"
    monkeypatch.setattr(ig, "MIN_DISTANCE", 65)       # impossible distance: everything "collides"
    out = ig.assign(["mancala", "mitre"], registry_path=reg, size=SMALL, max_salt=3)
    assert out["mancala"]["salt"] == 0
    assert out["mitre"]["salt"] == 3 and out["mitre"].get("warning")   # gave up at the cap, but said so


def test_a_corrupt_registry_is_treated_as_empty_not_a_crash(tmp_path):
    reg = tmp_path / "registry.json"; reg.write_text("{broken")
    assert "mancala" in ig.assign(["mancala"], registry_path=reg, size=SMALL)
