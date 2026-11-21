"""Tests for rebuild-manifest.py model-scope handling. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_rebuild_manifest.py -v
"""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import rebuild_manifest from scripts directory
rebuild_scripts = Path(__file__).resolve().parents[2] / "skills" / "self-improve" / "scripts"
spec = importlib.util.spec_from_file_location("rebuild_manifest", rebuild_scripts / "rebuild-manifest.py")
rebuild_manifest = importlib.util.module_from_spec(spec)

# Inject model_scope into sys.modules before executing
sys.modules["rebuild_manifest"] = rebuild_manifest
import model_scope as model_scope_mod  # noqa: E402
sys.modules["model_scope"] = model_scope_mod

spec.loader.exec_module(rebuild_manifest)


class TestParseModelScope:
    """Tests for model-scope field parsing in rebuild-manifest."""

    def test_skill_with_no_model_scope_field_omits_from_entry(self, tmp_path):
        """Skill without model-scope should not have that field in manifest entry."""
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: test-skill
tags: [type:skill, intent:test]
---
# Test Skill
""")

        fm = rebuild_manifest.parse_frontmatter(skill_file)
        raw_scope = fm.get("model-scope", "all").strip()
        should_include = raw_scope and raw_scope.lower() != "all"

        assert not should_include

    def test_skill_with_model_scope_all_omits_from_entry(self, tmp_path):
        """Skill with model-scope: all should not have that field in manifest entry."""
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: test-skill
model-scope: all
tags: [type:skill, intent:test]
---
# Test Skill
""")

        fm = rebuild_manifest.parse_frontmatter(skill_file)
        raw_scope = fm.get("model-scope", "all").strip()
        should_include = raw_scope and raw_scope.lower() != "all"

        assert not should_include

    def test_skill_with_model_scope_tier_includes_in_entry(self, tmp_path):
        """Skill with explicit model-scope should include that field in entry."""
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: test-skill
model-scope: sonnet+
tags: [type:skill, intent:test]
---
# Test Skill
""")

        fm = rebuild_manifest.parse_frontmatter(skill_file)
        raw_scope = fm.get("model-scope", "all").strip()
        should_include = raw_scope and raw_scope.lower() != "all"

        assert should_include
        assert raw_scope == "sonnet+"

    def test_skill_with_comma_separated_model_scope(self, tmp_path):
        """Skill with comma-separated model tiers should include that field."""
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: test-skill
model-scope: haiku,sonnet
tags: [type:skill, intent:test]
---
# Test Skill
""")

        fm = rebuild_manifest.parse_frontmatter(skill_file)
        raw_scope = fm.get("model-scope", "all").strip()
        should_include = raw_scope and raw_scope.lower() != "all"

        assert should_include
        assert raw_scope == "haiku,sonnet"


def test_an_empty_stdin_is_a_scheduled_run_not_a_bad_hook_payload(monkeypatch):
    # mac-mini-2012's systemd mirror job runs this with stdin = /dev/null (not a tty): that logged
    # "parsing stdin payload" to the error log every 10 minutes (ADR 0069).
    import io
    logged = []
    monkeypatch.setattr(rebuild_manifest.sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(rebuild_manifest, "log_hook_error", lambda *a, **k: logged.append(a))
    assert rebuild_manifest._hook_should_skip() is False     # full rebuild, as from the CLI
    assert logged == []


def test_a_garbled_hook_payload_is_still_logged(monkeypatch):
    import io
    logged = []
    monkeypatch.setattr(rebuild_manifest.sys, "stdin", io.StringIO("{not json"))
    monkeypatch.setattr(rebuild_manifest, "log_hook_error", lambda *a, **k: logged.append(a))
    assert rebuild_manifest._hook_should_skip() is False
    assert logged


class TestCallsField:
    """Tests for 'calls' field handling in rebuild-manifest."""

    def test_parse_frontmatter_on_real_to_tasklist_has_no_calls_key(self):
        """AC1: parse_frontmatter on the real to-tasklist/SKILL.md has no 'calls' key."""
        # Resolve path relative to repo root
        repo_root = Path(__file__).resolve().parents[2]
        to_tasklist_file = repo_root / "skills" / "to-tasklist" / "SKILL.md"

        assert to_tasklist_file.exists(), f"Expected {to_tasklist_file} to exist"

        fm = rebuild_manifest.parse_frontmatter(to_tasklist_file)
        assert "calls" not in fm, f"Expected no 'calls' key in frontmatter, but got: {fm.get('calls')}"

    def test_scan_skills_to_tasklist_entry_has_no_calls_key(self, monkeypatch):
        """AC2: scan_skills() returns to-tasklist entry with no 'calls' key."""
        # Get repo root
        repo_root = Path(__file__).resolve().parents[2]
        skills_dir = repo_root / "skills"

        assert skills_dir.exists(), f"Expected {skills_dir} to exist"

        # Monkeypatch SKILLS_DIR to point to repo's own skills/ dir
        monkeypatch.setattr(rebuild_manifest, "SKILLS_DIR", skills_dir)

        # Run scan_skills()
        entries = rebuild_manifest.scan_skills()

        # Find the to-tasklist entry
        to_tasklist_entry = next(
            (e for e in entries if e.get("name") == "to-tasklist"),
            None
        )
        assert to_tasklist_entry is not None, "Expected to-tasklist entry in scan_skills() output"
        assert "calls" not in to_tasklist_entry, f"Expected no 'calls' key in to-tasklist entry, but got: {to_tasklist_entry.get('calls')}"

    def test_parse_frontmatter_on_real_improve_codebase_architecture_has_no_calls_key(self):
        """AC3: parse_frontmatter on the real improve-codebase-architecture/SKILL.md has no 'calls' key."""
        repo_root = Path(__file__).resolve().parents[2]
        skill_file = repo_root / "skills" / "improve-codebase-architecture" / "SKILL.md"

        assert skill_file.exists(), f"Expected {skill_file} to exist"

        fm = rebuild_manifest.parse_frontmatter(skill_file)
        assert "calls" not in fm, f"Expected no 'calls' key in frontmatter, but got: {fm.get('calls')}"

    def test_scan_skills_improve_codebase_architecture_entry_has_no_calls_key(self, monkeypatch):
        """AC4: scan_skills() returns improve-codebase-architecture entry with no 'calls' key."""
        repo_root = Path(__file__).resolve().parents[2]
        skills_dir = repo_root / "skills"

        assert skills_dir.exists(), f"Expected {skills_dir} to exist"

        monkeypatch.setattr(rebuild_manifest, "SKILLS_DIR", skills_dir)

        entries = rebuild_manifest.scan_skills()

        improve_arch_entry = next(
            (e for e in entries if e.get("name") == "improve-codebase-architecture"),
            None
        )
        assert improve_arch_entry is not None, "Expected improve-codebase-architecture entry in scan_skills() output"
        assert "calls" not in improve_arch_entry, f"Expected no 'calls' key in improve-codebase-architecture entry, but got: {improve_arch_entry.get('calls')}"
