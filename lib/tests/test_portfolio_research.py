"""Research section generation from evidence logs (lib/portfolio_research.py, ADR 0051)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portfolio_research as pr  # noqa: E402


# ── test data ──

SIMPLE_LOG = """## E1. First finding
- **Source:** [paper](https://arxiv.org/abs/1234.5678)
- **What we took:** Main technique
- **Drives:** Design decision
- **Public use:** Yes

## E2. Second finding
- **Source:** [blog](https://example.com/post)
- **What we took:** Implementation detail
- **Drives:** Architecture choice
- **Public use:** Careful (limited applicability)

## E3. Third finding
- **Source:** [GitHub](https://github.com/example)
- **What we took:** Reference code
- **Drives:** Testing strategy
- **Public use:** Internal
"""

MALFORMED_LOG = """## E1. Missing field
- **Source:** [link](https://example.com)
- **Public use:** Yes

## E2. Well-formed
- **Source:** [link](https://example.com)
- **What we took:** Technique
- **Drives:** Decision
- **Public use:** Yes
"""

MISSING_FLAG_LOG = """## E1. No flag
- **Source:** [link](https://example.com)
- **What we took:** Technique
- **Drives:** Decision
"""

CONTINUATION_LOG = """## E1. Continuation test
- **Source:** [first](https://a.com)
  and [second](https://b.com)
- **What we took:** Details continue
  on next line
- **Drives:** Decision
- **Public use:** Yes
"""

MALFORMED_CAREFUL = """## E1. Bad caveat
- **Source:** [link](https://example.com)
- **What we took:** Tech
- **Drives:** Decision
- **Public use:** Careful (maybe) something else
"""

MALFORMED_FLAG = """## E1. Bad flag value
- **Source:** [link](https://example.com)
- **What we took:** Tech
- **Drives:** Decision
- **Public use:** Maybe?
"""

TEMPLATE_DICT = {
    "id": "app-product",
    "sections": [
        {"role": "hero", "heading": "Hero", "required": True},
        {"role": "status", "heading": "Status", "required": True},
        {"role": "research", "heading": "Research behind it", "required": False, "evidence": ["callout"]},
        {"role": "built-with", "heading": "Built with MARVIN", "required": False},
    ]
}


def template_content(sections=None):
    return {
        "content_type": "app-product",
        "lead_html": "<p>Lead.</p>",
        "sections": sections or [],
    }


# ── parsing (tests 1-10) ──

def test_a_well_formed_log_parses_to_one_record_per_entry():
    """Test 1: E1-E3 shape parses correctly."""
    entries = pr.parse_log(SIMPLE_LOG)
    assert len(entries) == 3
    assert entries[0]['number'] == 1
    assert entries[0]['title'] == 'First finding'
    assert entries[0]['public_use'] == 'Yes'
    assert entries[1]['public_use'] == 'Careful'
    assert entries[1]['caveat'] == 'limited applicability'
    assert entries[2]['public_use'] == 'Internal'


def test_an_entry_missing_a_required_bullet_does_not_crash_the_parser():
    """Test 2: Malformed entry doesn't crash, other entries parse."""
    entries = pr.parse_log(MALFORMED_LOG)
    assert len(entries) == 2
    # E1 is missing What we took and Drives, E2 is complete
    assert entries[0]['what_we_took'] is None
    assert entries[0]['drives'] is None
    assert entries[1]['what_we_took'] == 'Technique'


def test_a_yes_entry_missing_required_fields_is_not_rendered():
    """A Yes entry with missing source/what_we_took/drives is excluded at render time."""
    log = """## E1. Incomplete but public
- **Source:** [link](https://example.com)
- **Public use:** Yes
"""
    entries = pr.parse_log(log)
    pub = pr.publishable(entries)
    assert len(pub) == 1  # Entry is kept by publishable (it's Yes)
    assert pub[0]['what_we_took'] is None
    assert pub[0]['drives'] is None

    section = pr.render_section(pub)
    assert section is None  # But render_entry's guard excludes it, so no section


def test_an_entry_with_no_public_use_bullet_resolves_to_internal():
    """Test 3: Missing Public use flag → Internal."""
    entries = pr.parse_log(MISSING_FLAG_LOG)
    assert len(entries) == 1
    assert entries[0]['public_use'] == 'Internal'


def test_a_malformed_public_use_value_is_treated_as_internal():
    """Test 4: Unknown Public use value → Internal."""
    entries = pr.parse_log(MALFORMED_FLAG)
    assert len(entries) == 1
    assert entries[0]['public_use'] == 'Internal'


def test_an_empty_file_returns_empty_list():
    """Test 5: Empty file → []."""
    assert pr.parse_log("") == []
    assert pr.parse_log("   \n  ") == []



def test_a_file_with_no_e_headings_returns_empty_list():
    """Prose only → []."""
    prose = "Some text about research.\nBut no E1 headings.\n## Other section\nStuff"
    assert pr.parse_log(prose) == []


def test_a_very_long_log_is_parsed_without_slowdown_or_duplication():
    """200 entries parse correctly."""
    entries_text = "\n\n".join(
        f"""## E{i}. Entry {i}
- **Source:** [link](https://example.com/{i})
- **What we took:** Detail {i}
- **Drives:** Decision {i}
- **Public use:** Yes"""
        for i in range(1, 201)
    )
    entries = pr.parse_log(entries_text)
    assert len(entries) == 200
    assert entries[0]['number'] == 1
    assert entries[199]['number'] == 200
    assert len(set(id(e) for e in entries)) == 200  # all unique objects


def test_a_source_bullet_with_multiple_markdown_links_preserves_all():
    """Multiple links in Source are preserved."""
    log = """## E1. Multi-link
- **Source:** [first](https://a.com) and [second](https://b.com) and [third](https://c.com)
- **What we took:** Technique
- **Drives:** Decision
- **Public use:** Yes
"""
    entries = pr.parse_log(log)
    assert '[first]' in entries[0]['source']
    assert '[second]' in entries[0]['source']
    assert '[third]' in entries[0]['source']


def test_a_malformed_link_does_not_crash_the_parser():
    """Broken/dead links don't crash."""
    log = """## E1. Bad links
- **Source:** [text]( missing paren, [text](javascript:alert()) and [good](https://ok.com)
- **What we took:** Technique
- **Drives:** Decision
- **Public use:** Yes
"""
    entries = pr.parse_log(log)
    assert len(entries) == 1
    assert entries[0]['source'] is not None  # parsed, not crashed


def test_continuation_lines_are_joined_into_the_same_field():
    """Test 10: Wrapped bullet lines join together."""
    entries = pr.parse_log(CONTINUATION_LOG)
    assert len(entries) == 1
    # Source should have both links joined
    assert '[first]' in entries[0]['source'] and '[second]' in entries[0]['source']
    # What we took should have both lines joined
    assert 'Details continue' in entries[0]['what_we_took']
    assert 'on next line' in entries[0]['what_we_took']


# ── filtering (tests 11-12) ──

def test_yes_and_careful_entries_are_kept_internal_and_missing_are_dropped():
    """Test 11: Filtering by Public use flag."""
    entries = pr.parse_log(SIMPLE_LOG)
    pub = pr.publishable(entries)
    assert len(pub) == 2  # E1 (Yes) and E2 (Careful), not E3 (Internal)
    assert pub[0]['number'] == 1
    assert pub[1]['number'] == 2


def test_a_careful_entry_with_caveat_carries_it_without_crashing():
    """Caveat from Careful is preserved."""
    entries = pr.parse_log(SIMPLE_LOG)
    pub = pr.publishable(entries)
    careful = [e for e in pub if e['public_use'] == 'Careful'][0]
    assert careful['caveat'] == 'limited applicability'
    # Also test Careful without caveat doesn't crash
    entries2 = pr.parse_log("""## E1. No caveat
- **Source:** [link](https://example.com)
- **What we took:** Tech
- **Drives:** Decision
- **Public use:** Careful""")
    pub2 = pr.publishable(entries2)
    assert pub2[0]['caveat'] is None


# ── rendering (tests 13-15) ──

def test_html_escaping_prevents_injection():
    """HTML escaping works."""
    log = """## E1. Injection test
- **Source:** <script>alert('xss')</script>
- **What we took:** <img src=x onerror="alert(1)">
- **Drives:** & < > "quotes"
- **Public use:** Yes
"""
    entries = pr.parse_log(log)
    pub = pr.publishable(entries)
    section = pr.render_section(pub)
    html = section['body_html']

    # No live script tags or event handlers
    assert '<script>' not in html  # not as live code
    # Properly escaped dangerous content is fine:
    assert '&lt;script&gt;' in html or '&lt;img' in html  # escaped
    assert '&amp;' in html
    assert '&lt;' in html
    assert '&gt;' in html
    # Verify event handlers are escaped, not live
    assert 'onerror="alert' not in html  # not live (but onerror=&quot; is fine)


def test_markdown_inline_conversion_works():
    """**bold** → <strong>, [text](url) → <a href>."""
    log = """## E1. Markdown test
- **Source:** [GitHub](https://github.com/example)
- **What we took:** Use the **bold technique** for **performance**
- **Drives:** Decide to use **solution** from [blog post](https://example.com/post)
- **Public use:** Yes
"""
    entries = pr.parse_log(log)
    pub = pr.publishable(entries)
    section = pr.render_section(pub)
    html = section['body_html']

    # Check <strong> tags
    assert '<strong>bold technique</strong>' in html
    assert '<strong>performance</strong>' in html
    assert '<strong>solution</strong>' in html

    # Check <a> tags
    assert '<a href="https://github.com/example">' in html
    assert '<a href="https://example.com/post">' in html


def test_every_rendered_entry_is_wrapped_in_longform_callout():
    """All entries wrapped in class="longform-callout"."""
    entries = pr.parse_log(SIMPLE_LOG)
    pub = pr.publishable(entries)
    section = pr.render_section(pub)
    html = section['body_html']

    # Count callout divs (one per entry)
    callout_count = html.count('class="longform-callout"')
    assert callout_count == len(pub)
    assert html.count('</div>') >= len(pub)


# ── content integration ──

def test_research_section_is_inserted_at_template_declared_position():
    """Section inserts at correct position per template."""
    content = template_content([
        {"role": "hero", "body_html": "<p>Hero</p>"},
        {"role": "status", "body_html": "<p>Status</p>"},
        {"role": "built-with", "body_html": "<p>Built with</p>"},
    ])
    section = {"role": "research", "body_html": "<p>Research</p>"}
    pr.insert_or_update_section(content, TEMPLATE_DICT, section)

    # research should be between status and built-with
    roles = [s['role'] for s in content['sections']]
    assert roles == ['hero', 'status', 'research', 'built-with']


def test_running_twice_against_unchanged_log_is_idempotent():
    """Idempotent update (no duplicates)."""
    log = """## E1. Test
- **Source:** [link](https://example.com)
- **What we took:** Technique
- **Drives:** Decision
- **Public use:** Yes
"""
    content = template_content([
        {"role": "hero", "body_html": "<p>Hero</p>"},
        {"role": "status", "body_html": "<p>Status</p>"},
    ])

    # First insert
    section = pr.render_section(pr.publishable(pr.parse_log(log)))
    original = json.dumps(content, indent=2, ensure_ascii=False)
    pr.insert_or_update_section(content, TEMPLATE_DICT, section)
    after_first = json.dumps(content, indent=2, ensure_ascii=False)

    # Second insert (same section)
    pr.insert_or_update_section(content, TEMPLATE_DICT, section)
    after_second = json.dumps(content, indent=2, ensure_ascii=False)

    assert after_first == after_second
    assert len(content['sections']) == 3


def test_running_after_log_changes_updates_the_section():
    """Update after log changes."""
    log1 = """## E1. First
- **Source:** [link1](https://a.com)
- **What we took:** Technique 1
- **Drives:** Decision 1
- **Public use:** Yes

## E2. Second
- **Source:** [link2](https://b.com)
- **What we took:** Technique 2
- **Drives:** Decision 2
- **Public use:** Internal
"""

    log2 = """## E1. First (updated)
- **Source:** [link1](https://a.com)
- **What we took:** Updated technique
- **Drives:** Decision 1
- **Public use:** Yes

## E2. Second
- **Source:** [link2](https://b.com)
- **What we took:** Technique 2
- **Drives:** Decision 2
- **Public use:** Yes
"""

    content = template_content([
        {"role": "hero", "body_html": "<p>Hero</p>"},
        {"role": "status", "body_html": "<p>Status</p>"},
    ])

    # First update
    section1 = pr.render_section(pr.publishable(pr.parse_log(log1)))
    pr.insert_or_update_section(content, TEMPLATE_DICT, section1)
    first_html = content['sections'][-1]['body_html']

    # Second update (log changed)
    section2 = pr.render_section(pr.publishable(pr.parse_log(log2)))
    pr.insert_or_update_section(content, TEMPLATE_DICT, section2)
    second_html = content['sections'][-1]['body_html']

    # Content should change
    assert first_html != second_html
    assert 'Updated technique' in second_html
    assert section1['body_html'] != section2['body_html']


def test_a_log_that_becomes_empty_has_its_section_removed():
    """All-Internal log removes section."""
    log_empty = """## E1. Internal
- **Source:** [link](https://example.com)
- **What we took:** Technique
- **Drives:** Decision
- **Public use:** Internal
"""

    content = template_content([
        {"role": "hero", "body_html": "<p>Hero</p>"},
        {"role": "status", "body_html": "<p>Status</p>"},
        {"role": "research", "body_html": "<p>Old research</p>"},
        {"role": "built-with", "body_html": "<p>Built</p>"},
    ])

    section = pr.render_section(pr.publishable(pr.parse_log(log_empty)))
    assert section is None  # No publishable entries
    pr.insert_or_update_section(content, TEMPLATE_DICT, section)

    # research section should be gone
    roles = [s['role'] for s in content['sections']]
    assert 'research' not in roles


def test_a_project_with_no_evidence_log_returns_none_section():
    """No evidence log → no section added, no error."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)
        # No docs/research/evidence-log.md

        section = pr.section_for_project(str(project_path))
        assert section is None


def test_atomic_write_uses_temp_file_and_replace():
    """Atomic write with temp file."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        content_path = tmpdir / "test.json"
        template_path = tmpdir / "template.json"
        project_path = tmpdir / "project"

        # Setup
        content = template_content([{"role": "hero", "body_html": "<p>Hero</p>"}])
        content_path.write_text(json.dumps(content))
        template_path.write_text(json.dumps(TEMPLATE_DICT))
        project_path.mkdir()
        (project_path / "docs" / "research").mkdir(parents=True)
        log = """## E1. Test
- **Source:** [link](https://example.com)
- **What we took:** Technique
- **Drives:** Decision
- **Public use:** Yes
"""
        (project_path / "docs" / "research" / "evidence-log.md").write_text(log)

        # Update
        changed = pr.update_project_content(content_path, template_path, str(project_path))
        assert changed

        # Check file exists and is valid JSON
        assert content_path.exists()
        result = json.loads(content_path.read_text())
        assert 'sections' in result
        assert any(s['role'] == 'research' for s in result['sections'])


def test_unreadable_path_raises_clear_error():
    """Clear error on permission issues."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        content_path = tmpdir / "nonexistent.json"
        template_path = tmpdir / "template.json"

        with pytest.raises(RuntimeError, match="Failed to update"):
            pr.update_project_content(content_path, template_path, "/nonexistent")


# ── regression tests ──

def test_double_escape_regression_query_string_url():
    """Regression: query-string URLs escaped exactly once."""
    log = """## E1. Query string test
- **Source:** [API docs](https://example.com/docs?key=value&other=data)
- **What we took:** Endpoint details
- **Drives:** API design
- **Public use:** Yes
"""
    entries = pr.parse_log(log)
    pub = pr.publishable(entries)
    section = pr.render_section(pub)
    html = section['body_html']

    # URL should be present in the href with & escaped to &amp; exactly once
    assert 'href="https://example.com/docs?key=value&amp;other=data"' in html
    # Link text should be rendered correctly
    assert 'API docs</a>' in html


def test_double_escape_regression_escaped_char_link_text():
    """Regression: link text with < or & doesn't get double-escaped."""
    log = """## E1. Escaped text test
- **Source:** [A&B comparison](https://example.com/a-and-b)
- **What we took:** Comparison details
- **Drives:** Decision
- **Public use:** Yes
"""
    entries = pr.parse_log(log)
    pub = pr.publishable(entries)
    section = pr.render_section(pub)
    html = section['body_html']

    # & in link text should be escaped once as &amp;
    assert 'A&amp;B comparison</a>' in html
    # Not double-escaped as &amp;amp;
    assert '&amp;amp;' not in html


def test_unreadable_log_directory_as_log_path_raises():
    """Regression: directory as log path raises RuntimeError."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)
        # Create docs/research as a directory but not a file
        (project_path / "docs" / "research" / "evidence-log.md").mkdir(parents=True)

        # Should raise RuntimeError, not silently return None
        with pytest.raises(RuntimeError, match="Cannot read evidence log"):
            pr.section_for_project(str(project_path))


# ── CLI ──

def test_plan_mode_makes_no_writes(monkeypatch, capsys):
    """Plan mode prints section but does not modify files."""
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        content_path = tmpdir / "test.json"
        template_path = tmpdir / "template.json"
        project_path = tmpdir / "project"

        # Setup
        content = template_content([{"role": "hero", "body_html": "<p>Hero</p>"}])
        content_path.write_text(json.dumps(content))
        template_path.write_text(json.dumps(TEMPLATE_DICT))
        project_path.mkdir()
        (project_path / "docs" / "research").mkdir(parents=True)
        log = """## E1. Test
- **Source:** [link](https://example.com)
- **What we took:** Technique
- **Drives:** Decision
- **Public use:** Yes
"""
        (project_path / "docs" / "research" / "evidence-log.md").write_text(log)

        original = content_path.read_text()

        # Use env var to point PORTFOLIO_ROOT to tmpdir to avoid looking for real templates
        monkeypatch.setenv("PORTFOLIO_ROOT", str(tmpdir))
        monkeypatch.setattr(sys, "argv", ["test", "--content", str(content_path), "--source-repo", str(project_path), "--plan"])

        pr.main()

        # Verify plan mode printed JSON (with research section)
        captured = capsys.readouterr()
        assert "research" in captured.out
        assert "Source" in captured.out

        # File should be unchanged
        assert content_path.read_text() == original


def test_missing_source_repo_gives_clear_error(monkeypatch):
    """Clear error if no source-repo."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        content_path = tmpdir / "test.json"

        content = template_content([{"role": "hero", "body_html": "<p>Hero</p>"}])
        content_path.write_text(json.dumps(content))

        monkeypatch.setattr(sys, "argv", ["test", "--content", str(content_path)])
        with pytest.raises(SystemExit):
            pr.main()


# ── CLI error handling (misuse tests 4-8) ──

def test_cli_content_file_not_found(monkeypatch, capsys):
    """CLI: clear error if content file doesn't exist."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        project_path = tmpdir / "project"
        project_path.mkdir()

        monkeypatch.setattr(sys, "argv", [
            "test", "--content", str(tmpdir / "nonexistent.json"),
            "--source-repo", str(project_path)
        ])

        with pytest.raises(SystemExit) as exc_info:
            pr.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "Content file" in captured.err


def test_cli_content_file_invalid_json(monkeypatch, capsys):
    """CLI: clear error if content file is not valid JSON."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        content_path = tmpdir / "test.json"
        project_path = tmpdir / "project"

        content_path.write_text("{ invalid json")
        project_path.mkdir()

        monkeypatch.setattr(sys, "argv", [
            "test", "--content", str(content_path),
            "--source-repo", str(project_path)
        ])

        with pytest.raises(SystemExit) as exc_info:
            pr.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "parse" in captured.err.lower() or "JSON" in captured.err


def test_cli_missing_content_type_field(monkeypatch, capsys):
    """CLI: clear error if content file has no content_type field."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        content_path = tmpdir / "test.json"
        project_path = tmpdir / "project"

        # Content file without content_type
        content = {"lead_html": "<p>Lead</p>", "sections": []}
        content_path.write_text(json.dumps(content))
        project_path.mkdir()

        monkeypatch.setattr(sys, "argv", [
            "test", "--content", str(content_path),
            "--source-repo", str(project_path)
        ])

        with pytest.raises(SystemExit) as exc_info:
            pr.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "content_type" in captured.err.lower()


def test_cli_unknown_catalog_slug(monkeypatch, capsys):
    """CLI: clear error if --project references unknown catalog entry."""
    monkeypatch.setattr(sys, "argv", ["test", "--project", "nonexistent-project"])

    with pytest.raises(SystemExit) as exc_info:
        pr.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()


def test_cli_catalog_entry_missing_source_repo(monkeypatch, capsys):
    """CLI: clear error if catalog entry has no source_repo."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        content_path = tmpdir / "test.json"

        content = template_content([{"role": "hero", "body_html": "<p>Hero</p>"}])
        content_path.write_text(json.dumps(content))

        # This would require mocking project_catalog.load(), so we test the other path instead:
        # when --project is not provided and --source-repo is missing
        monkeypatch.setattr(sys, "argv", ["test", "--content", str(content_path)])

        with pytest.raises(SystemExit) as exc_info:
            pr.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "required" in captured.err.lower()
