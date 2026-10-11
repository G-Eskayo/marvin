#!/usr/bin/env python3
"""Simple test runner to verify portfolio_research.py implementation."""
import json
import sys
import tempfile
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_research as pr

def test_parse_evidence_log_reads_entries_from_markdown():
    text = """# Evidence log: title

## E1. First entry
- **Source:** A source.
- **What we took:** We took this.
- **Confidence:** Strong.
- **Drives:** the decision.
- **Public use:** Yes.

## E2. Second entry
- **Source:** Another source.
- **What we took:** We took that.
- **Confidence:** Moderate.
- **Drives:** another decision.
- **Public use:** Careful ("caveat").
"""
    result = pr.parse_evidence_log(text)
    assert len(result["entries"]) == 2, f"Expected 2 entries, got {len(result['entries'])}"
    assert result["entries"][0]["id"] == "E1"
    assert result["entries"][0]["source"] == "A source."
    assert result["entries"][0]["public"] == "Yes", f"Got public: {result['entries'][0]['public']}"
    assert result["entries"][1]["id"] == "E2"
    assert result["entries"][1]["public"] == "Careful", f"Got public: {result['entries'][1]['public']}"
    assert result["warnings"] == []
    print("✓ test_parse_evidence_log_reads_entries_from_markdown")


def test_parse_evidence_log_extracts_all_fields():
    text = """## E1. Title
- **Source:** A source here.
- **What we took:** We took this here.
- **Confidence:** Strong.
- **Drives:** these decisions.
- **Public use:** Yes.
"""
    result = pr.parse_evidence_log(text)
    entry = result["entries"][0]
    assert entry["source"] == "A source here.", f"Got source: {entry['source']}"
    assert entry["took"] == "We took this here.", f"Got took: {entry['took']}"
    assert entry["confidence"] == "Strong.", f"Got confidence: {entry['confidence']}"
    assert entry["drives"] == "these decisions.", f"Got drives: {entry['drives']}"
    assert entry["public"] == "Yes", f"Got public: {entry['public']}"
    print("✓ test_parse_evidence_log_extracts_all_fields")


def test_parse_evidence_log_handles_empty_input():
    result = pr.parse_evidence_log("")
    assert result["entries"] == []
    assert result["warnings"] == []
    print("✓ test_parse_evidence_log_handles_empty_input")


def test_render_research_section_includes_only_public_entries():
    entries = [
        {"id": "E1", "took": "We took A.", "public": "Yes", "title": "One", "caveat": None},
        {"id": "E2", "took": "We took B.", "public": "Internal", "title": "Two", "caveat": None},
        {"id": "E3", "took": "We took C.", "public": "Careful", "title": "Three", "caveat": "(caveat)"},
    ]
    result = pr.render_research_section(entries)
    html = result["html"]
    assert "E1" in html and "We took A." in html
    assert "E2" not in html and "Internal" not in html
    assert "E3" in html and "We took C." in html
    print("✓ test_render_research_section_includes_only_public_entries")


def test_render_research_section_separates_visible_and_internal():
    entries = [
        {"id": "E1", "took": "Public.", "public": "Yes", "title": "One", "caveat": None},
        {"id": "E2", "took": "Careful.", "public": "Careful", "title": "Two", "caveat": None},
        {"id": "E3", "took": "Hidden.", "public": "Internal", "title": "Three", "caveat": None},
    ]
    result = pr.render_research_section(entries)
    assert len(result["shown"]) == 2  # E1, E2
    assert len(result["hidden_internal"]) == 1  # E3
    print("✓ test_render_research_section_separates_visible_and_internal")


def test_render_research_section_no_entries():
    result = pr.render_research_section([])
    assert result["html"] == ""
    assert result["shown"] == []
    assert result["hidden_internal"] == []
    print("✓ test_render_research_section_no_entries")


def test_insert_or_update_section_adds_research_section_to_empty_list():
    sections = []
    result = pr.insert_or_update_section(sections, "research", "Research", "<p>HTML</p>")
    assert len(result) == 1
    assert result[0]["role"] == "research"
    assert result[0]["heading"] == "Research"
    assert result[0]["body_html"] == "<p>HTML</p>"
    print("✓ test_insert_or_update_section_adds_research_section_to_empty_list")


def test_insert_or_update_section_replaces_existing_research_section():
    sections = [
        {"role": "why", "heading": "Why", "body_html": "<p>Why</p>"},
        {"role": "research", "heading": "Old research", "body_html": "<p>Old</p>"},
        {"role": "status", "heading": "Status", "body_html": "<p>Status</p>"},
    ]
    result = pr.insert_or_update_section(sections, "research", "Research behind it", "<p>New</p>")
    assert len(result) == 3
    found = [s for s in result if s["role"] == "research"][0]
    assert found["heading"] == "Research behind it"
    assert found["body_html"] == "<p>New</p>"
    assert result[1]["role"] == "research"
    print("✓ test_insert_or_update_section_replaces_existing_research_section")


def test_insert_or_update_section_defaults_to_moving_to_end():
    sections = [{"role": "why", "heading": "Why", "body_html": "<p>Why</p>"}]
    result = pr.insert_or_update_section(sections, "research", "Research", "<p>HTML</p>")
    assert len(result) == 2
    assert result[-1]["role"] == "research"
    print("✓ test_insert_or_update_section_defaults_to_moving_to_end")


def test_generate_reads_evidence_log_and_renders_json():
    with tempfile.TemporaryDirectory() as tmp_path:
        tmp_path = Path(tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "docs" / "research").mkdir(parents=True)
        (repo / "docs" / "research" / "evidence-log.md").write_text("""# Evidence log

## E1. Test
- **Source:** A source.
- **What we took:** We took this.
- **Confidence:** Strong.
- **Drives:** decision.
- **Public use:** Yes.
""")

        content_path = tmp_path / "content.json"
        content_path.write_text(json.dumps({
            "sections": [
                {"role": "why", "heading": "Why", "body_html": "<p>Why</p>"},
            ]
        }))

        result = pr.generate(repo, content_path)
        assert "sections" in result
        found = [s for s in result["sections"] if s["role"] == "research"]
        assert len(found) == 1
        assert "E1" in found[0]["body_html"]
        print("✓ test_generate_reads_evidence_log_and_renders_json")


def test_generate_writes_file_atomically():
    with tempfile.TemporaryDirectory() as tmp_path:
        tmp_path = Path(tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "docs" / "research").mkdir(parents=True)
        (repo / "docs" / "research" / "evidence-log.md").write_text("""# Evidence log

## E1. Test
- **Source:** A source.
- **What we took:** We took this.
- **Confidence:** Strong.
- **Drives:** decision.
- **Public use:** Yes.
""")

        content_path = tmp_path / "content.json"
        content_path.write_text(json.dumps({"sections": []}))

        result = pr.generate(repo, content_path)

        # File should be rewritten
        on_disk = json.loads(content_path.read_text())
        assert on_disk == result
        print("✓ test_generate_writes_file_atomically")


def test_check_research_section_warns_if_no_research_section():
    content = {"sections": []}
    findings = pr.check_research_section(content)
    assert any(f["rule"] == "research-section-missing" for f in findings)
    print("✓ test_check_research_section_warns_if_no_research_section")


def test_check_research_section_passes_if_research_section_exists():
    content = {
        "sections": [
            {"role": "research", "heading": "Research", "body_html": "<p>Research</p>"},
        ]
    }
    findings = pr.check_research_section(content)
    missing = [f for f in findings if f["rule"] == "research-section-missing"]
    assert len(missing) == 0
    print("✓ test_check_research_section_passes_if_research_section_exists")


if __name__ == "__main__":
    try:
        test_parse_evidence_log_reads_entries_from_markdown()
        test_parse_evidence_log_extracts_all_fields()
        test_parse_evidence_log_handles_empty_input()
        test_render_research_section_includes_only_public_entries()
        test_render_research_section_separates_visible_and_internal()
        test_render_research_section_no_entries()
        test_insert_or_update_section_adds_research_section_to_empty_list()
        test_insert_or_update_section_replaces_existing_research_section()
        test_insert_or_update_section_defaults_to_moving_to_end()
        test_generate_reads_evidence_log_and_renders_json()
        test_generate_writes_file_atomically()
        test_check_research_section_warns_if_no_research_section()
        test_check_research_section_passes_if_research_section_exists()
        print("\n✅ All tests passed!")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
