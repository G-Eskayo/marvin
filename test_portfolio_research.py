"""Research logging for portfolio pages: parse evidence logs, render them as portfolio sections (tests for lib/portfolio_research.py)."""
import json
import sys
from pathlib import Path

# Import from the worktree (tests run here, gets synced to ~/.agents/lib)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_research as pr  # noqa: E402


# ── parse_evidence_log ──

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
    assert len(result["entries"]) == 2
    assert result["entries"][0]["id"] == "E1"
    assert result["entries"][0]["source"] == "A source."
    assert result["entries"][0]["public"] == "Yes"
    assert result["entries"][1]["id"] == "E2"
    assert result["entries"][1]["public"] == "Careful"
    assert result["warnings"] == []


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
    assert entry["source"] == "A source here."
    assert entry["took"] == "We took this here."
    assert entry["confidence"] == "Strong."
    assert entry["drives"] == "these decisions."


def test_parse_evidence_log_warns_on_missing_fields():
    text = """## E1. Incomplete
- **Source:** A source.
- **Confidence:** Strong.
"""
    result = pr.parse_evidence_log(text)
    assert len(result["entries"]) == 1
    assert len(result["warnings"]) > 0
    assert "E1" in result["warnings"][0]


def test_parse_evidence_log_handles_empty_input():
    result = pr.parse_evidence_log("")
    assert result["entries"] == []
    assert result["warnings"] == []


def test_parse_evidence_log_ignores_header_and_prose():
    text = """# Evidence log: title

Some prose here that doesn't matter.

## E1. Entry
- **Source:** A source.
- **What we took:** We took this.
- **Confidence:** Strong.
- **Drives:** decisions.
- **Public use:** Yes.
"""
    result = pr.parse_evidence_log(text)
    assert len(result["entries"]) == 1


# ── render_research_section ──

def test_render_research_section_includes_only_public_entries():
    entries = [
        {"id": "E1", "took": "We took A.", "public": "Yes"},
        {"id": "E2", "took": "We took B.", "public": "Internal"},
        {"id": "E3", "took": "We took C.", "public": "Careful"},
    ]
    result = pr.render_research_section(entries)
    html = result["html"]
    assert "E1" in html and "We took A." in html
    assert "E2" not in html and "Internal" not in html
    assert "E3" in html and "We took C." in html
    assert "Careful" in html  # caveat appears for Careful entries


def test_render_research_section_separates_visible_and_internal():
    entries = [
        {"id": "E1", "took": "Public.", "public": "Yes"},
        {"id": "E2", "took": "Careful.", "public": "Careful"},
        {"id": "E3", "took": "Hidden.", "public": "Internal"},
    ]
    result = pr.render_research_section(entries)
    assert len(result["shown"]) == 2  # E1, E2
    assert len(result["hidden_internal"]) == 1  # E3


def test_render_research_section_returns_html_and_metadata():
    entries = [
        {"id": "E1", "took": "We took this.", "public": "Yes"},
    ]
    result = pr.render_research_section(entries)
    assert "html" in result
    assert "shown" in result
    assert "hidden_internal" in result
    assert "warnings" in result
    assert isinstance(result["html"], str)
    assert len(result["html"]) > 0


def test_render_research_section_no_entries():
    result = pr.render_research_section([])
    assert result["html"] == ""
    assert result["shown"] == []
    assert result["hidden_internal"] == []


# ── insert_or_update_section ──

def test_insert_or_update_section_adds_research_section_to_empty_list():
    sections = []
    result = pr.insert_or_update_section(sections, "research", "Research", "<p>HTML</p>")
    assert len(result) == 1
    assert result[0]["role"] == "research"
    assert result[0]["heading"] == "Research"
    assert result[0]["body_html"] == "<p>HTML</p>"


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
    # Order preserved: still between why and status
    assert result[1]["role"] == "research"


def test_insert_or_update_section_defaults_to_moving_to_end():
    sections = [{"role": "why", "heading": "Why", "body_html": "<p>Why</p>"}]
    result = pr.insert_or_update_section(sections, "research", "Research", "<p>HTML</p>")
    assert len(result) == 2
    assert result[-1]["role"] == "research"


# ── generate ──

def test_generate_reads_evidence_log_and_renders_json(tmp_path):
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


def test_generate_handles_missing_evidence_log():
    # When there's no evidence log, the content is unchanged
    result = pr.generate(Path("/nonexistent"), Path("/nonexistent/content.json"))
    assert result is not None


def test_generate_writes_file_atomically(tmp_path):
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


# ── main / CLI ──

def test_main_accepts_repo_and_content_paths(tmp_path, monkeypatch):
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

    # Simulate command line
    monkeypatch.setattr(sys, "argv", ["portfolio_research.py", str(repo), str(content_path)])

    pr.main()

    # Content file should be updated
    result = json.loads(content_path.read_text())
    found = [s for s in result.get("sections", []) if s["role"] == "research"]
    assert len(found) == 1


def test_main_exits_with_usage_on_missing_args(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["portfolio_research.py"])
    try:
        pr.main()
        assert False, "should have raised SystemExit"
    except SystemExit as e:
        assert e.code == 2  # argparse exit code


# ── check_research_section ──

def test_check_research_section_warns_if_no_research_section():
    content = {"sections": []}
    findings = pr.check_research_section(content)
    assert any(f["rule"] == "research-section-missing" for f in findings)


def test_check_research_section_passes_if_research_section_exists():
    content = {
        "sections": [
            {"role": "research", "heading": "Research", "body_html": "<p>Research</p>"},
        ]
    }
    findings = pr.check_research_section(content)
    missing = [f for f in findings if f["rule"] == "research-section-missing"]
    assert len(missing) == 0


def test_check_research_section_returns_list_of_dicts():
    content = {"sections": []}
    findings = pr.check_research_section(content)
    assert isinstance(findings, list)
    for f in findings:
        assert isinstance(f, dict)
        assert "rule" in f
        assert "detail" in f
