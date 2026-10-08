"""Portfolio style catalog and prompt builder."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_styles as ps  # noqa: E402

CATALOG = {
    "styles": {
        "blueprint-line-art": "blueprint line art, white technical linework on deep blue, drafting-table precision",
        "watercolor": "loose watercolor painting, soft bleeding pigment, visible paper texture",
        "ink-brush": "ink brush painting, bold expressive strokes, sumi-e style",
        "low-poly": "low-poly 3D render, faceted geometric shapes, flat shading",
        "isometric": "isometric illustration, clean 30-degree projection, flat colour blocks",
        "risograph": "risograph print, limited spot-colour layers, visible grain and misregistration",
        "paper-cut-out": "paper cut-out collage, layered paper shapes, soft drop shadows",
        "minimal-vector": "minimal flat vector illustration, simple geometric shapes, generous negative space",
    },
    "moods": {
        "calm": "calm and serene, soft muted tones, gentle lighting",
        "energetic": "energetic and dynamic, bold contrast, a sense of motion",
        "nocturnal": "nocturnal, deep shadows, a single warm light source",
        "warm": "warm palette, amber and terracotta tones",
        "cool": "cool palette, blues and teals",
        "monochrome": "monochrome, a single hue with tonal variation only",
        "sunrise": "sunrise palette, soft pink and gold gradient",
        "neon": "neon palette, saturated electric colours against a dark background",
    },
}


def test_load_catalog_returns_styles_and_moods(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    catalog_file.write_text(json.dumps(CATALOG))
    result = ps.load_catalog(catalog_file)
    assert result == CATALOG
    assert set(result["styles"].keys()) == {
        "blueprint-line-art", "watercolor", "ink-brush", "low-poly", "isometric",
        "risograph", "paper-cut-out", "minimal-vector"
    }
    assert set(result["moods"].keys()) == {
        "calm", "energetic", "nocturnal", "warm", "cool", "monochrome", "sunrise", "neon"
    }


def test_load_catalog_returns_empty_dict_on_missing_file():
    result = ps.load_catalog(Path("/nonexistent/path/image-styles.json"))
    assert result == {}


def test_load_catalog_returns_empty_dict_on_corrupt_json(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    catalog_file.write_text("{ invalid json }")
    result = ps.load_catalog(catalog_file)
    assert result == {}


def test_style_names(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    catalog_file.write_text(json.dumps(CATALOG))
    names = ps.style_names(catalog_file)
    assert set(names) == set(CATALOG["styles"].keys())
    assert "blueprint-line-art" in names


def test_mood_names(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    catalog_file.write_text(json.dumps(CATALOG))
    names = ps.mood_names(catalog_file)
    assert set(names) == set(CATALOG["moods"].keys())
    assert "calm" in names


def test_style_fragment_returns_description(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    catalog_file.write_text(json.dumps(CATALOG))
    result = ps.style_fragment("blueprint-line-art", catalog_file)
    assert result == CATALOG["styles"]["blueprint-line-art"]


def test_style_fragment_raises_on_unknown_name(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    catalog_file.write_text(json.dumps(CATALOG))
    with pytest.raises(ValueError, match="unknown style.*unknown-style"):
        ps.style_fragment("unknown-style", catalog_file)


def test_mood_fragment_returns_description(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    catalog_file.write_text(json.dumps(CATALOG))
    result = ps.mood_fragment("calm", catalog_file)
    assert result == CATALOG["moods"]["calm"]


def test_mood_fragment_raises_on_unknown_name(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    catalog_file.write_text(json.dumps(CATALOG))
    with pytest.raises(ValueError, match="unknown mood.*unknown-mood"):
        ps.mood_fragment("unknown-mood", catalog_file)


def test_build_prompt_contains_all_parts(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    catalog_file.write_text(json.dumps(CATALOG))
    subject = "a futuristic city"
    prompt = ps.build_prompt(subject, "blueprint-line-art", "calm", catalog_file)
    assert subject in prompt
    assert CATALOG["styles"]["blueprint-line-art"] in prompt
    assert CATALOG["moods"]["calm"] in prompt
    assert ps.NO_TEXT_CLAUSE in prompt


def test_build_prompt_is_deterministic(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    catalog_file.write_text(json.dumps(CATALOG))
    subject = "a robot"
    style, mood = "isometric", "energetic"
    p1 = ps.build_prompt(subject, style, mood, catalog_file)
    p2 = ps.build_prompt(subject, style, mood, catalog_file)
    assert p1 == p2


def test_subject_from_description_strips_whitespace():
    result = ps.subject_from_description("  hello world  ")
    assert result == "hello world"


def test_subject_from_description_removes_trailing_period():
    result = ps.subject_from_description("hello world.")
    assert result == "hello world"


def test_subject_from_description_strips_and_removes_period():
    result = ps.subject_from_description("  hello world.  ")
    assert result == "hello world"


def test_subject_from_description_raises_on_empty_input():
    with pytest.raises(ValueError):
        ps.subject_from_description("")


def test_subject_from_description_raises_on_blank_input():
    with pytest.raises(ValueError):
        ps.subject_from_description("   ")


def test_description_for_slug_returns_none_for_unknown_slug(tmp_path):
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps([
        {"url": "/ai-projects/mancala/", "description": "Plays Mancala"},
    ]))
    result = ps.description_for_slug("unknown-slug", manifest_file)
    assert result is None


def test_description_for_slug_returns_only_description_field(tmp_path):
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps([
        {
            "url": "/ai-projects/mancala/",
            "description": "Plays Mancala",
            "notes": "This is private",
            "docs": "Also private",
            "title": "Mancala Game",
        },
    ]))
    result = ps.description_for_slug("mancala", manifest_file)
    assert result == "Plays Mancala"


def test_description_for_slug_matches_url_to_slug(tmp_path):
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps([
        {"url": "/ai-projects/foo-bar/", "description": "Foo Bar project"},
        {"url": "/ai-projects/baz-qux/", "description": "Baz Qux project"},
    ]))
    assert ps.description_for_slug("foo-bar", manifest_file) == "Foo Bar project"
    assert ps.description_for_slug("baz-qux", manifest_file) == "Baz Qux project"


def test_prompt_for_project_raises_on_unknown_slug(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    manifest_file = tmp_path / "manifest.json"
    catalog_file.write_text(json.dumps(CATALOG))
    manifest_file.write_text(json.dumps([]))
    with pytest.raises(ValueError, match="unknown slug"):
        ps.prompt_for_project("unknown-slug", "blueprint-line-art", "calm", manifest_file, catalog_file)


def test_prompt_for_project_builds_prompt_from_manifest_description(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    manifest_file = tmp_path / "manifest.json"
    catalog_file.write_text(json.dumps(CATALOG))
    manifest_file.write_text(json.dumps([
        {"url": "/ai-projects/mancala/", "description": "Plays Mancala"},
    ]))
    prompt = ps.prompt_for_project("mancala", "blueprint-line-art", "calm", manifest_file, catalog_file)
    assert "Plays Mancala" in prompt
    assert CATALOG["styles"]["blueprint-line-art"] in prompt
    assert CATALOG["moods"]["calm"] in prompt
    assert ps.NO_TEXT_CLAUSE in prompt


def test_prompt_for_project_works_with_synthetic_slug_not_in_motifs(tmp_path):
    catalog_file = tmp_path / "image-styles.json"
    manifest_file = tmp_path / "manifest.json"
    catalog_file.write_text(json.dumps(CATALOG))
    manifest_file.write_text(json.dumps([
        {"url": "/ai-projects/synthetic-project-xyz/", "description": "A synthetic test project"},
    ]))
    prompt = ps.prompt_for_project("synthetic-project-xyz", "watercolor", "nocturnal", manifest_file, catalog_file)
    assert "A synthetic test project" in prompt
    assert CATALOG["styles"]["watercolor"] in prompt
    assert CATALOG["moods"]["nocturnal"] in prompt
    assert ps.NO_TEXT_CLAUSE in prompt
