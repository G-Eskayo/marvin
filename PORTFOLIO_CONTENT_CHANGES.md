# Changes to portfolio_content.py

## 1. Add import at the top

After the existing imports (around line 22):

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_catalog  # noqa: E402
import portfolio_research  # noqa: E402  # NEW LINE
```

## 2. Add check_research_section function

After the `check_has_figure()` function (around line 118):

```python
def check_research_section(content: dict) -> list[dict]:
    """Check whether a content object has a research section.
    
    If the project has an evidence log (docs/research/evidence-log.md), a research
    section should be present in the content. This is an info-level check, not a
    hard requirement, since not all projects will have supporting research.
    """
    sections = content.get("sections", [])
    has_research = any(s.get("role") == "research" for s in sections)
    
    if not has_research:
        return [{
            "rule": "research-section-missing",
            "severity": "info",
            "detail": "no 'research' section; run portfolio_research.py to auto-generate from an evidence log"
        }]
    
    return []
```

## 3. Update evaluate() function

Around line 156, change:

```python
findings = check_copy(html) + check_media_markup(html) + check_has_figure(c)
```

To:

```python
findings = check_copy(html) + check_media_markup(html) + check_has_figure(c) + check_research_section(c)
```

## Changes to test_portfolio_content.py

### Add test after test_manifest_pages_without_a_content_file_are_listed_as_not_on_a_template:

```python
def test_research_section_is_checked():
    # Test 15: research section checking
    content_with_research = {
        "content_type": "skill-tool",
        "lead_html": "<p>Lead.</p>",
        "sections": [
            {"role": "why", "heading": "Why", "body_html": "<p>Why</p>"},
            {"role": "research", "heading": "Research", "body_html": "<p>Research here</p>"},
        ]
    }
    content_without_research = {
        "content_type": "skill-tool",
        "lead_html": "<p>Lead.</p>",
        "sections": [
            {"role": "why", "heading": "Why", "body_html": "<p>Why</p>"},
        ]
    }
    
    # With research section: no research-section-missing finding
    findings_with = pc.check_research_section(content_with_research)
    missing_findings = [f for f in findings_with if f["rule"] == "research-section-missing"]
    assert len(missing_findings) == 0
    
    # Without research section: info-level finding
    findings_without = pc.check_research_section(content_without_research)
    assert len(findings_without) == 1
    assert findings_without[0]["rule"] == "research-section-missing"
    assert findings_without[0]["severity"] == "info"


def test_research_section_is_included_in_evaluate():
    # Test 16: verify research checking is wired into evaluate()
    (tmp_path / "templates" / "content").mkdir(parents=True)
    (tmp_path / "content" / "longform").mkdir(parents=True)
    (tmp_path / "deploy" / "other-projects").mkdir(parents=True)
    (tmp_path / "templates" / "content" / "skill-tool.json").write_text(json.dumps(TEMPLATE))
    (tmp_path / "content" / "longform" / "tool.json").write_text(json.dumps(page([
        {"role": "evidence", "body_html": FIG.format(f="out.png", a="output")},
        {"role": "setup", "body_html": FIG.format(f="setup.svg", a="setup")}
    ])))
    (tmp_path / "deploy" / "other-projects" / "manifest.json").write_text(json.dumps([]))
    
    report = pc.evaluate(tmp_path)
    tool = report["pages"]["tool"]
    
    # Should have research-section-missing in findings (info level, not error)
    research_findings = [f for f in tool["findings"] if f["rule"] == "research-section-missing"]
    assert len(research_findings) == 1
    assert research_findings[0]["severity"] == "info"
```

Note: The second test (test_16) requires a tmp_path fixture, so it should follow the pattern of
`test_evaluate_reads_templates_and_content_files_from_a_project`.
