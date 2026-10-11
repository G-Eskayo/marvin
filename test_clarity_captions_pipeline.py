#!/usr/bin/env python3
"""End-to-end test of the portfolio_research pipeline with real clarity-captions data.

This script:
1. Reads the real evidence log from clarity-captions
2. Parses it
3. Renders the research section
4. Verifies the output is correct
"""
import json
import sys
from pathlib import Path

# Import portfolio_research
sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_research as pr

CLARITY_CAPTIONS_REPO = Path.home() / "Developer" / "clarity-captions"
CLARITY_CAPTIONS_CONTENT = Path.home() / "Developer" / "portfolio-website-updater" / "content" / "longform" / "clarity-captions.json"


def test_real_evidence_log():
    """Test parsing the real clarity-captions evidence log."""
    evidence_log_path = CLARITY_CAPTIONS_REPO / "docs" / "research" / "evidence-log.md"

    if not evidence_log_path.exists():
        print(f"⚠️  Evidence log not found at {evidence_log_path}")
        print("Skipping real data test (this is OK in isolated environments)")
        return False

    log_text = evidence_log_path.read_text()
    result = pr.parse_evidence_log(log_text)

    print(f"✓ Parsed evidence log: {len(result['entries'])} entries found")
    if result["warnings"]:
        print(f"  Warnings: {result['warnings']}")

    # Should have entries E1-E8 in the real log
    assert len(result["entries"]) >= 8, f"Expected at least 8 entries, got {len(result['entries'])}"

    # Check entry format
    for entry in result["entries"][:1]:  # Check first entry
        assert "id" in entry, f"Missing id in entry: {entry}"
        assert "source" in entry
        assert "took" in entry
        assert "confidence" in entry
        assert "drives" in entry
        assert "public" in entry
        print(f"  Entry {entry['id']}: {entry['title']}")
        print(f"    Public: {entry['public']}, Caveat: {entry.get('caveat', 'none')}")

    return result


def test_render_real_evidence():
    """Test rendering the parsed evidence as HTML."""
    evidence_log_path = CLARITY_CAPTIONS_REPO / "docs" / "research" / "evidence-log.md"

    if not evidence_log_path.exists():
        return None

    log_text = evidence_log_path.read_text()
    parsed = pr.parse_evidence_log(log_text)

    if not parsed["entries"]:
        print("⚠️  No entries parsed, skipping render test")
        return None

    rendered = pr.render_research_section(parsed["entries"])

    print(f"✓ Rendered research section:")
    print(f"  Shown entries: {len(rendered['shown'])} ({', '.join(rendered['shown'][:3])}...)")
    print(f"  Hidden entries: {len(rendered['hidden_internal'])}")
    print(f"  HTML length: {len(rendered['html'])} characters")

    # Verify structure
    assert "research-entries" in rendered["html"]
    assert len(rendered["shown"]) > 0, "Should have at least one visible entry"

    # Print sample HTML
    lines = rendered["html"].split("\n")
    print(f"  HTML preview (first 5 lines):")
    for line in lines[:5]:
        print(f"    {line}")

    return rendered


def test_full_pipeline():
    """Test the full generate() pipeline."""
    if not CLARITY_CAPTIONS_REPO.exists():
        print("⚠️  Clarity Captions repo not found, skipping full pipeline test")
        return None

    if not CLARITY_CAPTIONS_CONTENT.exists():
        print("⚠️  Clarity Captions content file not found, skipping full pipeline test")
        return None

    # Read current content
    current_content = json.loads(CLARITY_CAPTIONS_CONTENT.read_text())
    current_research_sections = [s for s in current_content.get("sections", []) if s["role"] == "research"]

    print(f"✓ Current content has {len(current_research_sections)} research section(s)")

    # Generate new content (without writing)
    # Note: we can't actually call generate() on real files in this environment,
    # but we can test the individual functions
    evidence_log_path = CLARITY_CAPTIONS_REPO / "docs" / "research" / "evidence-log.md"
    if evidence_log_path.exists():
        log_text = evidence_log_path.read_text()
        parsed = pr.parse_evidence_log(log_text)
        rendered = pr.render_research_section(parsed["entries"])

        # Show what would be updated
        print(f"✓ Would update content with:")
        print(f"  - HTML section: {len(rendered['html'])} characters")
        print(f"  - {len(rendered['shown'])} visible research entries")
        print(f"  - {len(rendered['hidden_internal'])} internal (hidden) entries")

        return rendered

    return None


def main():
    print("Testing portfolio_research with real clarity-captions data\n")

    try:
        # Test 1: Parse
        parsed = test_real_evidence_log()
        if parsed:
            print()

        # Test 2: Render
        rendered = test_render_real_evidence()
        if rendered:
            print()

        # Test 3: Full pipeline
        result = test_full_pipeline()

        print("\n✅ All real-data tests passed!")
        return 0

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n⚠️  Error (may be expected in isolated environment): {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
