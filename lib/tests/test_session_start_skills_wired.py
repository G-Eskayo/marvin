"""Tests for skill discovery, wiring, and the banner's skill count (marvin#997).

Tests 1-14: check_identity, skill_names, _dir_entries, _prune_dangling_commands, _wired_skill_names.

Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_session_start_skills_wired.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import session_start_report as ssr  # noqa: E402


class TestDirEntries:
    """Test 1: _dir_entries returns sorted list of direct subdirectories."""

    def test_returns_empty_on_nonexistent_path(self, tmp_path):
        d = tmp_path / "does" / "not" / "exist"
        assert ssr._dir_entries(d) == []

    def test_returns_empty_on_file_not_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("")
        assert ssr._dir_entries(f) == []

    def test_returns_sorted_subdirectories_only(self, tmp_path):
        (tmp_path / "z_dir").mkdir()
        (tmp_path / "a_dir").mkdir()
        (tmp_path / "file.txt").write_text("")
        (tmp_path / "file.md").write_text("")
        result = ssr._dir_entries(tmp_path)
        assert len(result) == 2
        assert result[0].name == "a_dir"
        assert result[1].name == "z_dir"


class TestSkillNames:
    """Test 2: skill_names finds subdirectories containing exactly SKILL.md."""

    def test_empty_when_no_skills_dir(self, tmp_path):
        d = tmp_path / "does" / "not" / "exist"
        assert ssr.skill_names(d) == []

    def test_finds_skills_with_skill_md(self, tmp_path):
        (tmp_path / "skill1").mkdir()
        (tmp_path / "skill1" / "SKILL.md").write_text("# Skill 1")
        (tmp_path / "skill2").mkdir()
        (tmp_path / "skill2" / "SKILL.md").write_text("# Skill 2")
        result = ssr.skill_names(tmp_path)
        assert result == ["skill1", "skill2"]

    def test_ignores_dirs_without_skill_md(self, tmp_path):
        (tmp_path / "skill1").mkdir()
        (tmp_path / "skill1" / "SKILL.md").write_text("# Skill 1")
        (tmp_path / "no_skill").mkdir()
        (tmp_path / "no_skill" / "README.md").write_text("# No SKILL.md")
        result = ssr.skill_names(tmp_path)
        assert result == ["skill1"]

    def test_ignores_files_at_root_level(self, tmp_path):
        (tmp_path / "SKILL.md").write_text("# Root level")
        (tmp_path / "skill1").mkdir()
        (tmp_path / "skill1" / "SKILL.md").write_text("# Skill 1")
        result = ssr.skill_names(tmp_path)
        assert result == ["skill1"]

    def test_returns_sorted_names(self, tmp_path):
        for name in ["z_skill", "a_skill", "m_skill"]:
            (tmp_path / name).mkdir()
            (tmp_path / name / "SKILL.md").write_text(f"# {name}")
        result = ssr.skill_names(tmp_path)
        assert result == ["a_skill", "m_skill", "z_skill"]


class TestPruneDanglingCommands:
    """Test 3: _prune_dangling_commands removes broken symlinks."""

    def test_does_nothing_if_commands_dir_missing(self, tmp_path):
        # Should not raise
        ssr._prune_dangling_commands(tmp_path / "does" / "not" / "exist")

    def test_removes_broken_symlink(self, tmp_path, monkeypatch):
        commands = tmp_path / "commands"
        commands.mkdir()
        broken = commands / "broken.md"
        broken.symlink_to(tmp_path / "missing_target")
        monkeypatch.setattr(ssr, "log_hook_error", lambda *a, **kw: None)
        ssr._prune_dangling_commands(commands)
        assert not broken.exists()

    def test_keeps_working_symlink(self, tmp_path, monkeypatch):
        commands = tmp_path / "commands"
        commands.mkdir()
        target = tmp_path / "target.md"
        target.write_text("# Target")
        link = commands / "working.md"
        link.symlink_to(target)
        monkeypatch.setattr(ssr, "log_hook_error", lambda *a, **kw: None)
        ssr._prune_dangling_commands(commands)
        assert link.exists()

    def test_keeps_regular_files(self, tmp_path, monkeypatch):
        commands = tmp_path / "commands"
        commands.mkdir()
        regular = commands / "regular.md"
        regular.write_text("# Regular")
        monkeypatch.setattr(ssr, "log_hook_error", lambda *a, **kw: None)
        ssr._prune_dangling_commands(commands)
        assert regular.exists()

    def test_logs_failures_on_unlink(self, tmp_path, monkeypatch):
        commands = tmp_path / "commands"
        commands.mkdir()
        broken = commands / "broken.md"
        broken.symlink_to(tmp_path / "missing_target")
        errors = []
        monkeypatch.setattr(ssr, "log_hook_error",
                           lambda hook, fn, exc: errors.append((hook, fn, type(exc).__name__)))
        # Mock unlink to always raise an error
        original_unlink = Path.unlink
        def failing_unlink(self):
            if self.name == "broken.md":
                raise OSError("Permission denied")
            return original_unlink(self)
        monkeypatch.setattr(Path, "unlink", failing_unlink)
        ssr._prune_dangling_commands(commands)
        assert any("broken.md" in fn for hook, fn, exc_type in errors)


class TestWiredSkillNames:
    """Test 4: _wired_skill_names finds skills wired by command files."""

    def test_empty_when_no_commands(self, tmp_path):
        commands = tmp_path / "commands"
        commands.mkdir()
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "skill1").mkdir()
        (skills / "skill1" / "SKILL.md").write_text("# Skill 1")
        result = ssr._wired_skill_names(skills, commands)
        assert result == set()

    def test_wired_by_matching_stem(self, tmp_path):
        """Command file stem matches a skill name."""
        commands = tmp_path / "commands"
        commands.mkdir()
        (commands / "skill1.md").write_text("# Command")
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "skill1").mkdir()
        (skills / "skill1" / "SKILL.md").write_text("# Skill 1")
        (skills / "skill2").mkdir()
        (skills / "skill2" / "SKILL.md").write_text("# Skill 2")
        result = ssr._wired_skill_names(skills, commands)
        assert result == {"skill1"}

    def test_wired_by_content_reference(self, tmp_path):
        """Command file references skills/<name>/SKILL.md in content."""
        commands = tmp_path / "commands"
        commands.mkdir()
        (commands / "other.md").write_text("This command references skills/skill2/SKILL.md for something")
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "skill1").mkdir()
        (skills / "skill1" / "SKILL.md").write_text("# Skill 1")
        (skills / "skill2").mkdir()
        (skills / "skill2" / "SKILL.md").write_text("# Skill 2")
        result = ssr._wired_skill_names(skills, commands)
        assert result == {"skill2"}

    def test_prioritizes_stem_match_over_content(self, tmp_path):
        """When both stem and content match, find both but don't double-count."""
        commands = tmp_path / "commands"
        commands.mkdir()
        (commands / "skill1.md").write_text("Also references skills/skill2/SKILL.md")
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "skill1").mkdir()
        (skills / "skill1" / "SKILL.md").write_text("# Skill 1")
        (skills / "skill2").mkdir()
        (skills / "skill2" / "SKILL.md").write_text("# Skill 2")
        result = ssr._wired_skill_names(skills, commands)
        assert result == {"skill1", "skill2"}

    def test_counts_valid_symlinks(self, tmp_path):
        """Valid symlinks are counted like regular files (matching stem wires the skill)."""
        commands = tmp_path / "commands"
        commands.mkdir()
        target = tmp_path / "target.md"
        target.write_text("# Target")
        link = commands / "skill1.md"
        link.symlink_to(target)
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "skill1").mkdir()
        (skills / "skill1" / "SKILL.md").write_text("# Skill 1")
        result = ssr._wired_skill_names(skills, commands)
        assert result == {"skill1"}

    def test_skips_dangling_symlinks(self, tmp_path):
        """Dangling symlinks (broken links) are skipped."""
        commands = tmp_path / "commands"
        commands.mkdir()
        broken = commands / "broken.md"
        broken.symlink_to(tmp_path / "missing_target")
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "broken").mkdir()
        (skills / "broken" / "SKILL.md").write_text("# Broken Skill")
        result = ssr._wired_skill_names(skills, commands)
        assert result == set()

    def test_handles_unreadable_files(self, tmp_path):
        """Unreadable command files don't crash, just skip the content check."""
        commands = tmp_path / "commands"
        commands.mkdir()
        (commands / "other.md").write_text("# Some command")
        (commands / "unreadable.md").write_text("# Content")
        (commands / "unreadable.md").chmod(0o000)
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "skill1").mkdir()
        (skills / "skill1" / "SKILL.md").write_text("# Skill 1")
        try:
            result = ssr._wired_skill_names(skills, commands)
            assert result == set()
        finally:
            (commands / "unreadable.md").chmod(0o644)


class TestCheckIdentity:
    """Test 5: check_identity builds the banner with total and wired skill counts."""

    def test_identity_format(self, tmp_path, monkeypatch):
        """Banner contains all expected fields with new format."""
        claude = tmp_path / ".claude"
        claude.mkdir()
        commands = claude / "commands"
        commands.mkdir()
        skills = tmp_path / "skills"
        skills.mkdir()
        # Create two skills
        (skills / "skill1").mkdir()
        (skills / "skill1" / "SKILL.md").write_text("# Skill 1")
        (skills / "skill2").mkdir()
        (skills / "skill2" / "SKILL.md").write_text("# Skill 2")
        # Wire one
        (commands / "skill1.md").write_text("# Command")
        monkeypatch.setattr(ssr, "SKILLS_DIR", skills)
        monkeypatch.setattr(ssr, "CLAUDE_DIR", claude)
        monkeypatch.setattr(ssr, "HOME", tmp_path)
        monkeypatch.setattr(ssr, "log_hook_error", lambda *a, **kw: None)
        result = ssr.check_identity()
        assert "MARVIN active" in result
        assert "· agents@" in result
        assert "· claude@" in result
        assert "2 skills (1 wired)" in result

    def test_identity_with_no_skills(self, tmp_path, monkeypatch):
        """Banner handles zero skills gracefully."""
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "commands").mkdir()
        skills = tmp_path / "skills"
        skills.mkdir()
        monkeypatch.setattr(ssr, "SKILLS_DIR", skills)
        monkeypatch.setattr(ssr, "CLAUDE_DIR", claude)
        monkeypatch.setattr(ssr, "HOME", tmp_path)
        monkeypatch.setattr(ssr, "log_hook_error", lambda *a, **kw: None)
        result = ssr.check_identity()
        assert "0 skills (0 wired)" in result

    def test_identity_calls_prune(self, tmp_path, monkeypatch):
        """check_identity calls _prune_dangling_commands on the commands dir."""
        claude = tmp_path / ".claude"
        claude.mkdir()
        commands = claude / "commands"
        commands.mkdir()
        skills = tmp_path / "skills"
        skills.mkdir()
        # Create a broken symlink
        broken = commands / "broken.md"
        broken.symlink_to(tmp_path / "missing")
        monkeypatch.setattr(ssr, "SKILLS_DIR", skills)
        monkeypatch.setattr(ssr, "CLAUDE_DIR", claude)
        monkeypatch.setattr(ssr, "HOME", tmp_path)
        monkeypatch.setattr(ssr, "log_hook_error", lambda *a, **kw: None)
        ssr.check_identity()
        # The broken symlink should be gone
        assert not broken.exists()
