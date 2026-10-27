"""Tests for command wiring (tests 14-19): auto-wire non-library skills as / commands.

wire_commands scans ~/.agents/skills for SKILL.md files, extracts their name,
filters out type:library skills, and creates ~/.claude/commands/<name>.md files
for invocation from Claude Code."""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wire_commands as wc


def test_14_parse_skill_name_from_frontmatter(tmp_path):
    """parse_skill_name should extract name from SKILL.md frontmatter."""
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()

    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: my-skill\n"
        "description: Test skill\n"
        "---\n\n"
        "# My Skill\n"
    )

    name = wc.parse_skill_name(skill_dir)
    assert name == "my-skill"


def test_15_parse_skill_name_ignores_missing_skill_md(tmp_path):
    """Should return None if SKILL.md doesn't exist."""
    skill_dir = tmp_path / "no-skill"
    skill_dir.mkdir()

    name = wc.parse_skill_name(skill_dir)
    assert name is None


def test_16_detect_library_skill_type(tmp_path):
    """is_library_skill should detect type:library tag."""
    skill_dir = tmp_path / "lib-skill"
    skill_dir.mkdir()

    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: lib-skill\n"
        "tags: [type:library, domain:utils]\n"
        "---\n"
    )

    assert wc.is_library_skill(skill_dir) is True


def test_17_detect_non_library_skill_type(tmp_path):
    """is_library_skill should return False for non-library skills."""
    skill_dir = tmp_path / "tool-skill"
    skill_dir.mkdir()

    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: tool-skill\n"
        "tags: [type:skill, domain:debug]\n"
        "---\n"
    )

    assert wc.is_library_skill(skill_dir) is False


def test_18_wire_commands_creates_command_files(tmp_path):
    """wire_commands should create .md files for each non-library skill."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    commands_dir = tmp_path / "commands"

    # Create two skills: one regular, one library
    for name, is_lib in [("diagnose", False), ("utils", True)]:
        skill_dir = skills_dir / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            f"---\n"
            f"name: {name}\n"
            f"tags: [{('type:library' if is_lib else 'type:skill')}]\n"
            f"---\n"
        )

    count = wc.wire_commands(skills_dir, commands_dir)

    # Should create command only for non-library skill
    assert count == 1
    assert (commands_dir / "diagnose.md").exists()
    assert not (commands_dir / "utils.md").exists()


def test_19_command_file_format_is_slash_command(tmp_path):
    """Command files should contain just /<name> for slash-command invocation."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    commands_dir = tmp_path / "commands"

    skill_dir = skills_dir / "myskill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: myskill\n"
        "tags: [type:skill]\n"
        "---\n"
    )

    wc.wire_commands(skills_dir, commands_dir)

    # Command file should contain the slash command
    content = (commands_dir / "myskill.md").read_text()
    assert "/myskill" in content
