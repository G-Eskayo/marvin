"""Test that index skill documentation is current."""
from pathlib import Path


def test_index_skill_explains_manifest_scope():
    """Verify that index/SKILL.md explains what the manifest indexes."""
    skill_path = Path(__file__).resolve().parents[1] / "skills" / "index" / "SKILL.md"

    content = skill_path.read_text()

    # Step 2 should mention that manifest indexes every skill plus knowledge files with tags
    assert "every skill" in content, \
        "Step 2 should explain that manifest indexes every skill"
    assert "knowledge files carrying `tags:` frontmatter" in content, \
        "Step 2 should mention knowledge files with tags frontmatter"


def test_index_skill_instructs_memory_scanning():
    """Verify that index/SKILL.md tells users to scan MEMORY.md for manual retrieval."""
    skill_path = Path(__file__).resolve().parents[1] / "skills" / "index" / "SKILL.md"

    content = skill_path.read_text()

    # Step 2 should mention scanning MEMORY.md for memory files without tags
    assert "MEMORY.md" in content, \
        "Step 2 should mention scanning MEMORY.md for memory files without tags"
    assert "one-line hooks" in content, \
        "Step 2 should mention MEMORY.md's one-line hooks"


def test_index_skill_no_examples_section():
    """Verify that Examples section has been removed from index/SKILL.md."""
    skill_path = Path(__file__).resolve().parents[1] / "skills" / "index" / "SKILL.md"

    content = skill_path.read_text()

    # Examples section should not exist
    assert "## Examples" not in content, \
        "Examples section should be removed from the documentation"


def test_index_skill_keeping_manifest_current_mentions_knowledge_files():
    """Verify that 'Keeping the Manifest Current' mentions knowledge files with tags."""
    skill_path = Path(__file__).resolve().parents[1] / "skills" / "index" / "SKILL.md"

    content = skill_path.read_text()

    # The section should mention knowledge files you want found by tag
    assert "knowledge file you want found by tag" in content, \
        "Should mention 'knowledge file you want found by tag' in Keeping the Manifest Current section"
