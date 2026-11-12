"""Test that skill documentation links use absolute paths."""
import re
from pathlib import Path


def test_research_skill_uses_absolute_doc_links():
    """Verify that research/SKILL.md uses absolute paths for epistemic-framework.md."""
    skill_path = Path(__file__).resolve().parents[1] / "skills" / "research" / "SKILL.md"

    content = skill_path.read_text()

    # Find all markdown links to epistemic-framework.md
    # We're looking for [text](path) patterns
    links = re.findall(r'\[epistemic-framework\.md\]\(([^)]+)\)', content)

    # Should have 2 links
    assert len(links) == 2, f"Expected 2 epistemic-framework.md links, found {len(links)}"

    # Both should use absolute paths with ~/.agents/
    for link in links:
        assert link == "~/.agents/skills/research/epistemic-framework.md", \
            f"Expected absolute path ~/.agents/skills/research/epistemic-framework.md, got {link}"
