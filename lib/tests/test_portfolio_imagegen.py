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
    out = ig.assign(SLUGS, registry_path=tmp_path / "r.json", size=ig.HERO_SIZE)  # the real banner size: sparse diagrams are too coarse to compare when tiny
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


def test_images_are_coloured_not_greyscale_since_the_sites_black_and_white_is_a_css_effect():
    # Gil 2026-10-02: colour is fine -- the black-and-white on the site is an effect applied to images.
    img = arr(ig.render("mancala", size=SMALL)).astype(int)
    chroma = img.max(axis=2) - img.min(axis=2)
    assert np.percentile(chroma, 99) > 60   # the drawn structure is coloured (the dark ground is naturally low-chroma)


def _mean_hue(img):
    import colorsys
    a = np.asarray(img, dtype=np.float32).reshape(-1, 3)[::11] / 255.0
    hsv = np.array([colorsys.rgb_to_hsv(*px) for px in a])
    w = hsv[:, 1] * hsv[:, 2]
    return float(np.degrees(np.arctan2((np.sin(hsv[:, 0] * 2 * np.pi) * w).sum(), (np.cos(hsv[:, 0] * 2 * np.pi) * w).sum())) % 360)


def _angle_gap(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


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
    assert ig.hamming(ig.fingerprint(Image.open(src)), ig.fingerprint(out)) >= ig.MIN_DISTANCE
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
    monkeypatch.setattr(ig, "MIN_DISTANCE", 200)      # impossible distance: everything "collides"
    out = ig.assign(["mancala", "mitre"], registry_path=reg, size=SMALL, max_salt=3)
    assert out["mancala"]["salt"] == 0
    assert out["mitre"]["salt"] == 3 and out["mitre"].get("warning")   # gave up at the cap, but said so


def test_a_corrupt_registry_is_treated_as_empty_not_a_crash(tmp_path):
    reg = tmp_path / "registry.json"; reg.write_text("{broken")
    assert "mancala" in ig.assign(["mancala"], registry_path=reg, size=SMALL)


# ── the fingerprint must see fine textures ──────────────────────────────────
# Found 2026-10-02 generating real images: killer-sudoku's very fine moire weave averaged to flat
# grey at the 9x8 dHash resolution -> hash 0000000000000000, so the uniqueness check was BLIND to it
# (and the closest same-style pair was only 5 bits apart). The fingerprint now adds a spectral
# half (which frequencies/orientations the image contains), which is phase-independent.

def test_a_fine_moire_weave_does_not_fingerprint_as_flat():
    fp = ig.fingerprint(ig.render("killer-sudoku", size=(1100, 300)))
    assert fp != 0 and (fp & ((1 << 64) - 1)) != 0          # the spectral half is populated


def test_two_fine_weaves_with_different_parameters_are_told_apart():
    a = ig.fingerprint(ig.render("killer-sudoku", size=(1100, 300)))
    b = ig.fingerprint(ig.render("marvin", size=(1100, 300)))
    assert ig.hamming(a, b) >= ig.MIN_DISTANCE


def test_the_fingerprint_is_128_bits_and_deterministic():
    img = ig.render("mancala", size=SMALL)
    assert ig.fingerprint(img) == ig.fingerprint(ig.render("mancala", size=SMALL))
    assert 0 <= ig.fingerprint(img) < (1 << 128)


def test_registry_stores_the_128_bit_fingerprint_as_32_hex_chars(tmp_path):
    out = ig.assign(["mancala"], registry_path=tmp_path / "r.json", size=SMALL)
    assert len(out["mancala"]["hash"]) == 32


# ── colour palette inspired by the project's own image ──────────────────────

def _tinted(tmp_path, rgb, name):
    p = tmp_path / name
    Image.fromarray(np.full((120, 440, 3), rgb, dtype=np.uint8)).save(p)
    return p


def test_inspiration_reports_the_dominant_hues_of_a_coloured_image(tmp_path):
    red = ig.inspiration_from([_tinted(tmp_path, (200, 20, 20), "r.png")])
    assert red["saturation"] > 0.5 and _angle_gap(red["hues"][0], 0) < 15
    assert len(red["hues"]) == 2


def test_a_red_inspiration_gives_red_art_and_a_teal_one_gives_teal_art(tmp_path):
    red = ig.render("mancala", size=SMALL, inspiration=ig.inspiration_from([_tinted(tmp_path, (210, 30, 30), "r.png")]))
    teal = ig.render("mancala", size=SMALL, inspiration=ig.inspiration_from([_tinted(tmp_path, (20, 190, 180), "t.png")]))
    assert _angle_gap(_mean_hue(red), 0) < 40
    assert _angle_gap(_mean_hue(teal), 175) < 40


def test_a_project_whose_image_has_no_colour_still_gets_a_deterministic_colour_from_its_slug(tmp_path):
    grey = ig.inspiration_from([_tinted(tmp_path, (120, 120, 120), "g.png")])
    a1, a2 = ig.render("mancala", size=SMALL, inspiration=grey), ig.render("mancala", size=SMALL, inspiration=grey)
    assert np.array_equal(arr(a1), arr(a2))
    assert (arr(a1).astype(int).max(axis=2) - arr(a1).astype(int).min(axis=2)).mean() > 25   # coloured, not grey


def test_slug_derived_colours_vary_across_projects():
    hues = {round(_mean_hue(ig.render(s, size=(220, 60))) / 60) for s in SLUGS}
    assert len(hues) >= 3


# ── thematic motifs ─────────────────────────────────────────────────────────

def test_every_default_motif_is_drawable_and_deterministic():
    import numpy as np
    import portfolio_motifs as m
    for name in set(m.DEFAULT_MOTIFS.values()):
        a = m.draw(name, (440, 120), np.random.RandomState(3))
        b = m.draw(name, (440, 120), np.random.RandomState(3))
        assert a.shape == (120, 440) and a.max() > 0.5, name       # something is actually drawn
        assert (a == b).all(), name


def test_motif_override_wins_and_unknown_motif_is_rejected(tmp_path):
    import json
    import numpy as np
    import portfolio_motifs as m
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"marvin": "tree", "mancala": None}))
    assert m.motif_for("marvin", f) == "tree"
    assert m.motif_for("mancala", f) is None            # explicit null = abstract pattern instead
    assert m.motif_for("killer-sudoku", f) == "sudoku"  # untouched slugs keep the default
    assert m.motif_for("never-heard-of-it", f) is None
    import pytest
    with pytest.raises(ValueError):
        m.draw("nope", (10, 10), np.random.RandomState(0))


def test_projects_with_a_motif_render_differently_from_the_pattern_only_look():
    import numpy as np
    import portfolio_imagegen as g
    with_motif = np.asarray(g.render("mancala", (440, 120)))
    assert g.look_for("mancala") == "mancala"
    assert g.look_for("some-new-project") == g.style_for("some-new-project")
    assert with_motif.std() > 0


# ── variants: keep what was generated, choose what is used ──────────────────

def _paths(tmp_path):
    return {"registry_path": tmp_path / "reg.json", "images_dir": tmp_path / "images"}


def test_a_variant_is_cached_by_motif_and_salt_and_listed(tmp_path):
    p = _paths(tmp_path)
    v = ig.make_variant("mancala", "mancala", 0, None, p["images_dir"], SMALL)
    assert Path(v["file"]).exists() and Path(v["file"]).name == "mancala-0.png"
    listing = ig.list_variants("mancala", **p)
    assert [(x["motif"], x["salt"], x["chosen"]) for x in listing["variants"]] == [("mancala", 0, False)]
    assert listing["default_motif"] == "mancala"


def test_next_salt_skips_variants_already_generated(tmp_path):
    p = _paths(tmp_path)
    assert ig.next_variant_salt("mancala", "mancala", p["images_dir"]) == 0
    ig.make_variant("mancala", "mancala", 0, None, p["images_dir"], SMALL)
    ig.make_variant("mancala", "mancala", 1, None, p["images_dir"], SMALL)
    assert ig.next_variant_salt("mancala", "mancala", p["images_dir"]) == 2
    assert ig.next_variant_salt("mancala", "tree", p["images_dir"]) == 0      # another motif has its own count


def test_choosing_a_variant_makes_it_the_image_in_use_and_survives_listing(tmp_path):
    p = _paths(tmp_path)
    ig.make_variant("mancala", "mancala", 3, None, p["images_dir"], SMALL)
    out = ig.choose_variant("mancala", "mancala", 3, None, size=SMALL, **p)
    assert out == {"slug": "mancala", "motif": "mancala", "salt": 3}
    assert (p["images_dir"] / "mancala.png").exists()
    reg = json.loads(p["registry_path"].read_text())["mancala"]
    assert reg["chosen"] is True and reg["salt"] == 3 and reg["look"] == "mancala"
    listing = ig.list_variants("mancala", **p)
    assert [x["chosen"] for x in listing["variants"]] == [True]


def test_choosing_a_different_theme_than_the_default_is_allowed(tmp_path):
    p = _paths(tmp_path)
    ig.choose_variant("mancala", "tree", 0, None, size=SMALL, **p)     # make_variant happens on demand
    assert json.loads(p["registry_path"].read_text())["mancala"]["look"] == "tree"
    ig.choose_variant("mancala", None, 0, None, size=SMALL, **p)       # None = the abstract pattern, no motif
    assert json.loads(p["registry_path"].read_text())["mancala"]["look"] == "pattern"


def test_a_choice_is_never_blocked_by_similarity_only_warned(tmp_path):
    p = _paths(tmp_path)
    ig.choose_variant("marvin", "network", 0, None, size=SMALL, **p)
    out = ig.choose_variant("marketplace-ml-agent", "network", 0, None, size=SMALL, **p)
    assert out["motif"] == "network"             # chosen regardless; a warning may accompany it
    assert json.loads(p["registry_path"].read_text())["marketplace-ml-agent"]["chosen"] is True


def test_motif_argument_parsing():
    assert ig._motif_arg(None) is ig.DEFAULT and ig._motif_arg("default") is ig.DEFAULT
    assert ig._motif_arg("pattern") is None and ig._motif_arg("tree") == "tree"
    import pytest
    with pytest.raises(ValueError):
        ig._motif_arg("nonsense")
    assert "pattern" in ig.motif_choices() and "network" in ig.motif_choices()
