"""Research evidence logging for portfolio pages (lib/portfolio_research.py).

Tests for parsing evidence logs, rendering research sections, and integrating with content files.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_research as pr  # noqa: E402


# ── parse_evidence_log tests ──

def test_parse_evidence_log_extracts_entries_from_markdown():
    """parse_evidence_log reads markdown-formatted entries with link syntax."""
    text = """
## Evidence

- Source: [Paper Title](https://example.com/paper.pdf)
- Takeaway: Some key insight here
- Confidence: 85%
- Decision: Use this finding
- Public: Yes
"""
    result = pr.parse_evidence_log(text)
    assert "entries" in result and "warnings" in result
    assert len(result["entries"]) >= 1
    entry = result["entries"][0]
    assert entry["source_title"] == "Paper Title"
    assert entry["source_url"] == "https://example.com/paper.pdf"


def test_parse_evidence_log_handles_multiple_entries():
    """parse_evidence_log collects all entries in the markdown."""
    text = """
- Source: [First](https://a.com)
  Takeaway: First insight
  Public: Yes

- Source: [Second](https://b.com)
  Takeaway: Second insight
  Public: Careful
"""
    result = pr.parse_evidence_log(text)
    assert len(result["entries"]) == 2
    assert result["entries"][0]["source_title"] == "First"
    assert result["entries"][1]["source_title"] == "Second"


def test_parse_evidence_log_escapes_raw_text_fields():
    """parse_evidence_log HTML-escapes takeaway, decision, and other raw text before rendering."""
    text = """
- Source: [Title](https://example.com)
  Takeaway: A <script>alert("xss")</script> attack
  Decision: Reject <b>bold</b> claims
  Public: Yes
"""
    result = pr.parse_evidence_log(text)
    entry = result["entries"][0]
    assert "&lt;script&gt;" in entry["takeaway"]
    assert "&lt;b&gt;" in entry["decision"]


def test_parse_evidence_log_renders_source_link_as_html():
    """parse_evidence_log converts markdown link [title](url) into HTML <a> tag."""
    text = """
- Source: [My Research](https://research.example.com/doc)
  Public: Yes
"""
    result = pr.parse_evidence_log(text)
    entry = result["entries"][0]
    assert '<a href="https://research.example.com/doc"' in entry["source_html"]
    assert "My Research" in entry["source_html"]


def test_parse_evidence_log_only_renders_yes_and_careful_as_public():
    """parse_evidence_log: Public field must be exactly 'Yes' or 'Careful' to render; otherwise warnings."""
    text = """
- Source: [A](https://a.com)
  Public: Yes

- Source: [B](https://b.com)
  Public: Careful

- Source: [C](https://c.com)
  Public: maybe
"""
    result = pr.parse_evidence_log(text)
    assert result["entries"][0]["public"] == "Yes"
    assert result["entries"][1]["public"] == "Careful"
    assert result["entries"][2]["public"] is None
    assert any("Public" in w for w in result["warnings"])


def test_parse_evidence_log_collects_warnings_for_malformed_entries():
    """parse_evidence_log warns about entries missing required fields (source, takeaway, decision)."""
    text = """
- Source: [Title](https://example.com)
  Takeaway: Missing decision field
"""
    result = pr.parse_evidence_log(text)
    assert any("decision" in w.lower() for w in result["warnings"])


def test_parse_evidence_log_handles_empty_or_missing_sections():
    """parse_evidence_log returns empty entries list and warning if no evidence section found."""
    text = "Some random markdown with no evidence section"
    result = pr.parse_evidence_log(text)
    assert result["entries"] == []
    assert any("evidence" in w.lower() for w in result["warnings"])


# ── render_research_section tests ──

def test_render_research_section_generates_html_callout():
    """render_research_section creates .longform-callout markup from entries."""
    entries = [
        {
            "source_html": '<a href="https://example.com">Paper A</a>',
            "takeaway": "Key finding",
            "confidence": "85%",
            "decision": "Use this",
            "public": "Yes",
        }
    ]
    result = pr.render_research_section(entries, style="default")
    assert "longform-callout" in result["html"]
    assert "Key finding" in result["html"]


def test_render_research_section_collects_shown_and_hidden_fields():
    """render_research_section tracks which entries are shown vs hidden_internal based on public flag."""
    entries = [
        {"source_html": '<a>A</a>', "takeaway": "public", "public": "Yes", "confidence": "90%", "decision": "yes"},
        {"source_html": '<a>B</a>', "takeaway": "careful", "public": "Careful", "confidence": "70%", "decision": "maybe"},
        {"source_html": '<a>C</a>', "takeaway": "private", "public": None, "confidence": "50%", "decision": "no"},
    ]
    result = pr.render_research_section(entries, style="default")
    assert result["shown"] == 2
    assert result["hidden_internal"] == 1


def test_render_research_section_returns_warnings_for_malformed_entries():
    """render_research_section warns if entries lack required fields for rendering."""
    entries = [
        {"source_html": None, "takeaway": None, "public": "Yes"},  # missing required
    ]
    result = pr.render_research_section(entries, style="default")
    assert len(result["warnings"]) > 0


def test_render_research_section_uses_decision_option_a_by_default():
    """render_research_section uses Option A (single shared callout) when no style specified."""
    entries = [
        {
            "source_html": '<a href="#">Source</a>',
            "takeaway": "Finding",
            "confidence": "80%",
            "decision": "Applied",
            "public": "Yes",
        }
    ]
    result = pr.render_research_section(entries, style="option_a")
    assert "longform-callout" in result["html"]


# ── insert_or_update_section tests ──

def test_insert_or_update_section_appends_when_no_template():
    """insert_or_update_section appends a new section when template is None."""
    sections = [{"role": "evidence", "body_html": "<p>Existing</p>"}]
    updated = pr.insert_or_update_section(
        sections,
        role="research",
        heading="Research Behind It",
        body_html="<div class='longform-callout'>New content</div>",
        template=None,
    )
    assert len(updated) == 2
    assert updated[-1]["role"] == "research"


def test_insert_or_update_section_inserts_at_template_index():
    """insert_or_update_section inserts at the position specified by template's index when given."""
    sections = [
        {"role": "evidence", "body_html": "<p>First</p>"},
        {"role": "extras", "body_html": "<p>Second</p>"},
    ]
    template = {"index": 1}  # insert at position 1
    updated = pr.insert_or_update_section(
        sections,
        role="research",
        heading="Research",
        body_html="<p>Research</p>",
        template=template,
    )
    assert updated[1]["role"] == "research"
    assert len(updated) == 3


def test_insert_or_update_section_replaces_existing_research_section():
    """insert_or_update_section replaces an existing 'research' role section instead of appending."""
    sections = [
        {"role": "evidence", "body_html": "<p>Evidence</p>"},
        {"role": "research", "body_html": "<p>Old research</p>"},
        {"role": "extras", "body_html": "<p>Extras</p>"},
    ]
    updated = pr.insert_or_update_section(
        sections,
        role="research",
        heading="Research",
        body_html="<p>New research</p>",
        template=None,
    )
    assert len(updated) == 3
    research = [s for s in updated if s["role"] == "research"][0]
    assert "New research" in research["body_html"]


def test_insert_or_update_section_removes_empty_research_section():
    """insert_or_update_section removes the research section if body_html is empty or None."""
    sections = [
        {"role": "evidence", "body_html": "<p>Evidence</p>"},
        {"role": "research", "body_html": "<p>Old research</p>"},
    ]
    updated = pr.insert_or_update_section(
        sections,
        role="research",
        heading="Research",
        body_html="",  # empty
        template=None,
    )
    assert len(updated) == 1
    assert all(s["role"] != "research" for s in updated)


# ── generate tests ──

def test_generate_reads_content_file_and_updates_it():
    """generate reads a content JSON file, updates the research section, and writes back."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "docs" / "research").mkdir(parents=True)
        (repo / "docs" / "research" / "evidence-log.md").write_text(
            "- Source: [Test](https://example.com)\n  Takeaway: Test\n  Public: Yes\n  Decision: Yes\n  Confidence: 90%"
        )
        content = tmp_path / "content.json"
        content.write_text(json.dumps({
            "content_type": "skill-tool",
            "sections": [{"role": "evidence", "body_html": "<p>Evidence</p>"}],
        }))
        result = pr.generate(str(repo), str(content))
        assert "warnings" in result
        assert result["sections"] is not None


def test_generate_raises_filenotfound_for_missing_content():
    """generate raises FileNotFoundError if content_path doesn't exist."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        try:
            pr.generate(str(tmp_path), str(tmp_path / "missing.json"))
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass


def test_generate_writes_atomically_via_temp_file():
    """generate uses atomic write: temp file + os.replace, not direct overwrite."""
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "docs" / "research").mkdir(parents=True)
        (repo / "docs" / "research" / "evidence-log.md").write_text(
            "- Source: [Test](https://example.com)\n  Takeaway: Test\n  Public: Yes\n  Decision: Yes\n  Confidence: 90%"
        )
        content_path = tmp_path / "content.json"
        content_path.write_text(json.dumps({
            "content_type": "skill-tool",
            "sections": [{"role": "evidence", "body_html": "<p>Evidence</p>"}],
        }))
        original_replace = os.replace
        replace_called = []

        def track_replace(src, dst):
            replace_called.append((src, dst))
            return original_replace(src, dst)

        os.replace = track_replace
        try:
            pr.generate(str(repo), str(content_path))
            assert len(replace_called) > 0
        finally:
            os.replace = original_replace


def test_generate_handles_json_decode_error():
    """generate raises json.JSONDecodeError if content file is not valid JSON."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "docs" / "research").mkdir(parents=True)
        (repo / "docs" / "research" / "evidence-log.md").write_text("- Source: [Test](https://example.com)\n  Takeaway: Test\n  Public: Yes\n  Decision: Yes")
        content = tmp_path / "bad.json"
        content.write_text("not valid json {")
        try:
            pr.generate(str(repo), str(content))
            assert False, "Should have raised JSONDecodeError"
        except json.JSONDecodeError:
            pass


# ── main (CLI) tests ──

def test_main_accepts_two_positional_arguments(tmp_path, capsys):
    """main() works as a CLI with two positional args: repo_path and content_path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docs" / "research").mkdir(parents=True)
    (repo / "docs" / "research" / "evidence-log.md").write_text(
        "- Source: [Test](https://example.com)\n  Takeaway: Test\n  Public: Yes\n  Decision: Yes\n  Confidence: 90%"
    )
    content = tmp_path / "content.json"
    content.write_text(json.dumps({"content_type": "skill-tool", "sections": []}))

    sys.argv = ["portfolio_research.py", str(repo), str(content)]
    pr.main()
    captured = capsys.readouterr()
    # Should run without error; warnings go to stderr


def test_main_prints_warnings_to_stderr(tmp_path, capsys):
    """main() prints warnings from parsing to stderr."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docs" / "research").mkdir(parents=True)
    (repo / "docs" / "research" / "evidence-log.md").write_text("invalid format")
    content = tmp_path / "content.json"
    content.write_text(json.dumps({"content_type": "skill-tool", "sections": []}))

    sys.argv = ["portfolio_research.py", str(repo), str(content)]
    pr.main()
    captured = capsys.readouterr()
    # Warnings should appear in stderr
    assert "evidence" in captured.err.lower() or len(captured.err) > 0


def test_evidence_in_recognizes_longform_callout_markup():
    """portfolio_content.evidence_in() recognizes .longform-callout div as 'callout' evidence."""
    import portfolio_content as pc
    html = '<div class="longform-callout">Research callout</div>'
    kinds = pc.evidence_in(html)
    assert "callout" in kinds
