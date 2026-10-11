"""Test research section checking for portfolio pages (integration test for test 15)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path.home() / ".agents" / "lib"))

# Import from both locations to test integration
import portfolio_research as pr  # noqa: E402

CONTENT_WITH_RESEARCH = {
    "sections": [
        {"role": "why", "heading": "Why", "body_html": "<p>Why</p>"},
        {"role": "research", "heading": "Research", "body_html": "<p>Research here</p>"},
    ]
}

CONTENT_WITHOUT_RESEARCH = {
    "sections": [
        {"role": "why", "heading": "Why", "body_html": "<p>Why</p>"},
    ]
}


def test_check_research_section_warns_if_no_research_section():
    """Test 15: content without research section gets flagged."""
    findings = pr.check_research_section(CONTENT_WITHOUT_RESEARCH)
    assert len(findings) > 0, "Expected findings for content without research section"
    assert any(f["rule"] == "research-section-missing" for f in findings)
    # Should be info level, not error
    assert findings[0]["severity"] == "info"
    print("✓ test_check_research_section_warns_if_no_research_section")


def test_check_research_section_passes_if_research_section_exists():
    """Test 15b: content with research section passes check."""
    findings = pr.check_research_section(CONTENT_WITH_RESEARCH)
    missing = [f for f in findings if f["rule"] == "research-section-missing"]
    assert len(missing) == 0, f"Expected no missing findings, got {missing}"
    print("✓ test_check_research_section_passes_if_research_section_exists")


def test_check_research_section_returns_list_of_dicts():
    """Test 15c: check_research_section returns proper format."""
    findings = pr.check_research_section(CONTENT_WITHOUT_RESEARCH)
    assert isinstance(findings, list)
    for f in findings:
        assert isinstance(f, dict)
        assert "rule" in f
        assert "detail" in f
        assert "severity" in f
    print("✓ test_check_research_section_returns_list_of_dicts")


if __name__ == "__main__":
    try:
        test_check_research_section_warns_if_no_research_section()
        test_check_research_section_passes_if_research_section_exists()
        test_check_research_section_returns_list_of_dicts()
        print("\n✅ All research section tests passed!")
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
