"""Regression test: verify the public showcase (docs/impact.md) stays durable and evidence-linked."""
import re
from pathlib import Path


def test_impact_doc_exists():
    """docs/impact.md must exist at the repo root."""
    impact_path = Path(__file__).resolve().parents[2] / "docs" / "impact.md"
    assert impact_path.exists(), f"docs/impact.md not found at {impact_path}"


def test_impact_doc_is_linked_from_readme():
    """Impact showcase must be linked from README.md's Docs map section."""
    readme_path = Path(__file__).resolve().parents[2] / "README.md"
    readme_text = readme_path.read_text()

    # Look for the Docs map section and the impact.md link within it
    docs_map_match = re.search(r"## Docs map.*?(?=## [A-Z]|\Z)", readme_text, re.DOTALL)
    assert docs_map_match, "No 'Docs map' section found in README.md"

    docs_map_section = docs_map_match.group(0)
    assert "[`docs/impact.md`]" in docs_map_section or "[docs/impact.md]" in docs_map_section, \
        "docs/impact.md is not linked in the Docs map section"


def test_impact_has_at_least_two_case_studies():
    """Impact showcase must contain at least 2 case studies (### headings) under Real-world impact."""
    impact_path = Path(__file__).resolve().parents[2] / "docs" / "impact.md"
    impact_text = impact_path.read_text()

    # Find the "Real-world impact" section and count ### headings
    match = re.search(r"# Real-world impact\s*(.*?)(?=^# [A-Z]|\Z)", impact_text, re.MULTILINE | re.DOTALL)
    assert match, "No 'Real-world impact' heading found in docs/impact.md"

    impact_section = match.group(1)
    case_studies = re.findall(r"^### ", impact_section, re.MULTILINE)
    assert len(case_studies) >= 2, f"Expected at least 2 case studies (###), found {len(case_studies)}"


def test_each_case_study_has_evidence_links():
    """Each case study must contain at least one markdown link (evidence)."""
    impact_path = Path(__file__).resolve().parents[2] / "docs" / "impact.md"
    impact_text = impact_path.read_text()

    # Find the "Real-world impact" section
    match = re.search(r"# Real-world impact\s*(.*?)(?=^# [A-Z]|\Z)", impact_text, re.MULTILINE | re.DOTALL)
    assert match, "No 'Real-world impact' heading found in docs/impact.md"

    impact_section = match.group(1)

    # Split by case study headings (###)
    case_studies = re.split(r"^### ", impact_section, flags=re.MULTILINE)[1:]  # Skip the header junk

    assert len(case_studies) >= 2, f"Expected at least 2 case studies, found {len(case_studies)}"

    for i, case_study in enumerate(case_studies, 1):
        # Each case study should contain at least one markdown link: [text](url) or [text](path)
        links = re.findall(r"\[([^\]]+)\]\(([^\)]+)\)", case_study)
        assert len(links) >= 1, \
            f"Case study {i} contains no markdown links (no evidence links found)"
