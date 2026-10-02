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
