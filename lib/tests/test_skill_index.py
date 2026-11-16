"""Tests for lib/skill_index.py: skill frontmatter parsing and docs/skills.md generation."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import skill_index as si  # noqa: E402


def test_frontmatter_parses_yaml_key_value_pairs():
    """frontmatter() extracts key: value pairs from YAML block."""
    text = """---
name: example
description: A tool that does things.
tags: [a, b]
---
# Content"""
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.md"
        path.write_text(text)
        fm = si.frontmatter(path)
    assert fm.get("name") == "example"
    assert fm.get("description") == "A tool that does things."
    assert "tags" in fm


def test_frontmatter_handles_multiline_descriptions():
    """frontmatter() joins multiline description values."""
    text = """---
name: test
description: A tool that does many
  things and has a long description
  spanning multiple lines.
---
"""
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.md"
        path.write_text(text)
        fm = si.frontmatter(path)
    assert "does many" in fm.get("description", "")
    assert "multiple lines" in fm.get("description", "")


def test_frontmatter_handles_block_scalars():
    """frontmatter() handles YAML block scalar indicators (>, |)."""
    text = """---
name: test
description: >
  This is a block scalar.
  It spans multiple lines.
---
"""
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.md"
        path.write_text(text)
        fm = si.frontmatter(path)
    # Block scalars are joined from continuation lines
    assert "block scalar" in fm.get("description", "")
    assert "multiple lines" in fm.get("description", "")


def test_frontmatter_returns_empty_dict_for_missing_frontmatter():
    """frontmatter() returns {} if file has no --- markers."""
    text = "# No frontmatter here\nJust content."
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.md"
        path.write_text(text)
        fm = si.frontmatter(path)
    assert fm == {}


def test_frontmatter_strips_quotes_from_values():
    """frontmatter() removes surrounding quotes from values."""
    text = """---
name: "quoted"
description: 'single quoted'
---
"""
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.md"
        path.write_text(text)
        fm = si.frontmatter(path)
    assert fm.get("name") == "quoted"
    assert fm.get("description") == "single quoted"


def test_one_line_truncates_long_descriptions():
    """one_line() truncates descriptions longer than the limit."""
    # Create a first sentence that exceeds the 230-char limit
    long_sentence = "This is an extremely long single sentence with no period that goes on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on to ensure it exceeds two hundred thirty characters. More text after."
    result = si.one_line(long_sentence, limit=230)
    assert len(result) <= 230
    assert result.endswith("…"), f"Expected truncation marker, got: {result}"


def test_one_line_keeps_short_descriptions():
    """one_line() returns short descriptions unchanged."""
    short_desc = "A short description under 50 chars."
    result = si.one_line(short_desc, limit=230)
    assert result == short_desc


def test_one_line_extracts_first_sentence():
    """one_line() extracts only the first sentence."""
    multi_sentence = "First sentence ends here. This is the second. And a third."
    result = si.one_line(multi_sentence)
    assert result == "First sentence ends here."
    assert "second" not in result


def test_one_line_collapses_whitespace():
    """one_line() collapses multiple spaces into single spaces."""
    desc = "Text  with   multiple    spaces."
    result = si.one_line(desc)
    assert "  " not in result
    assert result == "Text with multiple spaces."


def test_one_line_escapes_pipes():
    """one_line() escapes pipe characters for markdown table context."""
    desc = "Uses | character in description."
    result = si.one_line(desc)
    assert "\\|" in result


def test_one_line_respects_custom_limit():
    """one_line() respects custom character limits."""
    desc = "This is exactly forty characters long."
    result = si.one_line(desc, limit=20)
    assert len(result) <= 20


def test_build_generates_markdown_header():
    """build() generates correct markdown header structure."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        skills_dir = tmpdir_path / "skills"
        skills_dir.mkdir()

        # Create a mock skill
        skill_dir = skills_dir / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("---\nname: test_skill\ndescription: A test skill.\n---\n# Content")

        result = si.build(tmpdir_path)

    assert "# Skills" in result
    assert "Generated from each skill's own" in result


def test_build_includes_all_skills():
    """build() includes all discovered skills."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        skills_dir = tmpdir_path / "skills"
        skills_dir.mkdir()

        # Create multiple skills
        for name in ["skill1", "skill2", "skill3"]:
            skill_dir = skills_dir / name
            skill_dir.mkdir()
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text(f"---\nname: {name}\ndescription: Description of {name}.\n---\n# Content")

        result = si.build(tmpdir_path)

    assert "skill1" in result
    assert "skill2" in result
    assert "skill3" in result


def test_build_groups_skills_correctly():
    """build() places skills into defined GROUPS."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        skills_dir = tmpdir_path / "skills"
        skills_dir.mkdir()

        # Create skills that match existing groups
        for name in ["diagnose", "readme", "research"]:
            skill_dir = skills_dir / name
            skill_dir.mkdir()
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text(f"---\nname: {name}\ndescription: Description of {name}.\n---\n# Content")

        result = si.build(tmpdir_path)

    # Verify group headers exist
    assert "## Quality and debugging" in result
    assert "## Writing and creating" in result
    assert "## Research and reading" in result


def test_build_includes_security_sweep_in_quality_group():
    """build() includes security-sweep in Quality and debugging group."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        skills_dir = tmpdir_path / "skills"
        skills_dir.mkdir()

        # Create security-sweep skill
        skill_dir = skills_dir / "security-sweep"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("---\nname: security-sweep\ndescription: Security sweep tool.\n---\n# Content")

        result = si.build(tmpdir_path)

    # Find the Quality and debugging section
    lines = result.split("\n")
    quality_idx = next(i for i, l in enumerate(lines) if "## Quality and debugging" in l)
    # security-sweep should appear after the quality header
    security_sweep_found = False
    for line in lines[quality_idx:quality_idx + 20]:
        if "security-sweep" in line:
            security_sweep_found = True
            break
    assert security_sweep_found, "security-sweep not found in Quality and debugging section"


def test_build_creates_table_rows():
    """build() creates markdown table rows with pipe-separated columns."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        skills_dir = tmpdir_path / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "test"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("---\nname: test\ndescription: A test skill for testing.\n---\n# Content")

        result = si.build(tmpdir_path)

    # Check for markdown table structure with link
    assert "[`test`]" in result
    assert "A test skill for testing" in result


def test_build_handles_empty_skills_directory():
    """build() handles case with no skills gracefully."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        skills_dir = tmpdir_path / "skills"
        skills_dir.mkdir()

        result = si.build(tmpdir_path)

    # Should still have header even with no skills
    assert "# Skills" in result
    assert "0 skills" in result


def test_build_skill_count_is_accurate():
    """build() reports correct skill count."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        skills_dir = tmpdir_path / "skills"
        skills_dir.mkdir()

        # Create exactly 5 skills
        for i in range(5):
            skill_dir = skills_dir / f"skill{i}"
            skill_dir.mkdir()
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text(f"---\nname: skill{i}\ndescription: Skill number {i}.\n---\n")

        result = si.build(tmpdir_path)

    assert "5 skills" in result


def test_build_places_ungrouped_skills_in_other():
    """build() creates 'Other' section for skills not in predefined groups."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        skills_dir = tmpdir_path / "skills"
        skills_dir.mkdir()

        # Create a skill not in any GROUPS
        skill_dir = skills_dir / "random_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("---\nname: random_skill\ndescription: A random skill.\n---\n")

        result = si.build(tmpdir_path)

    # Should create Other section
    assert "## Other" in result
    assert "random_skill" in result


def test_build_uses_links_to_skill_files():
    """build() creates markdown links to SKILL.md files."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        skills_dir = tmpdir_path / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "example"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("---\nname: example\ndescription: Example skill.\n---\n")

        result = si.build(tmpdir_path)

    # Should contain link to SKILL.md
    assert "[`example`]" in result
    assert "../skills/example/SKILL.md" in result


def test_frontmatter_with_yaml_array_values():
    """frontmatter() handles YAML array values in brackets."""
    text = """---
name: test
tags: [intent:write, domain:docs]
---
"""
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.md"
        path.write_text(text)
        fm = si.frontmatter(path)
    assert "tags" in fm


def test_one_line_stops_at_first_sentence_boundary():
    """one_line() correctly identifies sentence boundaries (., !, ?)."""
    desc1 = "Question here? More text after."
    result1 = si.one_line(desc1)
    assert result1 == "Question here?"

    desc2 = "Exclamation here! More text after."
    result2 = si.one_line(desc2)
    assert result2 == "Exclamation here!"


def test_build_markdown_table_is_valid():
    """build() generates valid markdown table with proper separators."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        skills_dir = tmpdir_path / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "test"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("---\nname: test\ndescription: Test skill.\n---\n")

        result = si.build(tmpdir_path)

    # Check for header row separator
    lines = result.split("\n")
    found_separator = False
    for i, line in enumerate(lines):
        if "|---|---|" in line:
            found_separator = True
            break
    assert found_separator, "Markdown table separator not found"
