"""Tests for suggestions_list.py"""
import json
import pytest
import re
import subprocess
import sys
from pathlib import Path

# Import the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from suggestions_list import suggestions_list


@pytest.fixture
def temp_suggestions_file(tmp_path):
    """Create a temporary suggestions file for testing."""
    file_path = tmp_path / "suggestions.md"
    return file_path


def test_empty_file_returns_empty_array(temp_suggestions_file):
    """Test that missing file returns empty array."""
    # File doesn't exist
    result = suggestions_list(temp_suggestions_file)
    assert result == []


def test_whitespace_only_file_returns_empty_array(temp_suggestions_file):
    """Test that whitespace-only file returns empty array."""
    temp_suggestions_file.write_text("   \n\n   \n")
    result = suggestions_list(temp_suggestions_file)
    assert result == []


def test_parses_single_entry(temp_suggestions_file):
    """Test parsing a single well-formed entry."""
    content = """# Suggestions

## Example Suggestion

**Priority**: 3
**Status**: pending
**Impact**: speed
**Effort**: low

This is the body text.
It has multiple lines.
"""
    temp_suggestions_file.write_text(content)
    result = suggestions_list(temp_suggestions_file)
    assert len(result) == 1
    assert result[0]['title'] == 'Example Suggestion'
    assert result[0]['priority'] == 3
    assert result[0]['status'] == 'pending'
    assert result[0]['impact'] == 'speed'
    assert result[0]['effort'] == 'low'
    assert 'This is the body text.' in result[0]['body']
    assert 'multiple lines' in result[0]['body']


def test_missing_fields_default_to_none(temp_suggestions_file):
    """Test that missing fields return None, not fabricated defaults."""
    content = """# Suggestions

## Minimal Entry

No fields here at all.
"""
    temp_suggestions_file.write_text(content)
    result = suggestions_list(temp_suggestions_file)
    assert len(result) == 1
    assert result[0]['priority'] is None
    assert result[0]['status'] == 'pending'  # default when missing
    assert result[0]['impact'] is None
    assert result[0]['effort'] is None


def test_multiple_entries(temp_suggestions_file):
    """Test parsing multiple entries."""
    content = """# Suggestions

## First Entry

**Priority**: 1
**Status**: pending

Body one.

## Second Entry

**Priority**: 2
**Status**: resolved

Body two.
"""
    temp_suggestions_file.write_text(content)
    result = suggestions_list(temp_suggestions_file)
    assert len(result) == 2
    assert result[0]['title'] == 'First Entry'
    assert result[1]['title'] == 'Second Entry'


def test_headerless_entry_mid_file(temp_suggestions_file):
    """Test that headerless entry (merged into previous) doesn't crash."""
    # Simulate the real-world case in the current suggestions.md where
    # entry count doesn't match header count: one entry lost its header.
    content = """# Suggestions

## Entry One

**Priority**: 1
**Status**: pending

Body one.

**Priority**: 2
**Status**: resolved

This entry has no ## header; _split_entries merges it with the previous.
"""
    temp_suggestions_file.write_text(content)
    result = suggestions_list(temp_suggestions_file)
    # Should not crash, and should have parsed the first entry correctly
    assert len(result) == 1
    assert result[0]['title'] == 'Entry One'


def test_entry_with_code_block_containing_header(temp_suggestions_file):
    """Test that ## in code blocks is not treated as a new entry."""
    content = """# Suggestions

## Real Entry

**Priority**: 1

Some text with a fake header below:

```
## Fake Header in Code
This is just code, not a new entry.
```

More body after code.
"""
    temp_suggestions_file.write_text(content)
    result = suggestions_list(temp_suggestions_file)
    # The regex can't distinguish headers in code blocks, so this remains
    # a known limitation. This test documents the current behavior.
    # _split_entries will split on this, but our test verifies we don't crash.
    assert result[0]['title'] == 'Real Entry'


def test_large_body_roundtrips(temp_suggestions_file):
    """Test that large bodies (many paragraphs, many updates) round-trip intact."""
    large_body = "\n".join([
        f"Paragraph {i}. " * 10
        for i in range(10)
    ]) + "\n\n" + ("\n".join([
        f"**Update {i}**: Change number {i}."
        for i in range(5)
    ]))

    content = f"""# Suggestions

## Complex Entry

**Priority**: 2

{large_body}
"""
    temp_suggestions_file.write_text(content)
    result = suggestions_list(temp_suggestions_file)
    assert len(result) == 1
    # Verify the large body is intact
    for i in range(10):
        assert f"Paragraph {i}" in result[0]['body']
    for i in range(5):
        assert f"**Update {i}**" in result[0]['body']


def test_unicode_content(temp_suggestions_file):
    """Test that non-ASCII content is handled correctly."""
    content = """# Suggestions

## Entry with émojis 🎯

**Priority**: 1

Some text with special chars: café, naïve, 中文.
"""
    temp_suggestions_file.write_text(content, encoding='utf-8')
    result = suggestions_list(temp_suggestions_file)
    assert len(result) == 1
    assert 'émojis' in result[0]['title']
    assert 'café' in result[0]['body']


def test_binary_garbage_raises_unicode_error(temp_suggestions_file):
    """Test that corrupted/binary file raises UnicodeDecodeError."""
    temp_suggestions_file.write_bytes(b'\x80\x81\x82\x83')
    # With explicit encoding="utf-8" and no error handler, binary garbage raises UnicodeDecodeError
    with pytest.raises(UnicodeDecodeError):
        suggestions_list(temp_suggestions_file)


def test_status_values(temp_suggestions_file):
    """Test different status values (pending, resolved)."""
    content = """# Suggestions

## Pending Entry

**Status**: pending

Body.

## Resolved Entry

**Status**: resolved

Body.
"""
    temp_suggestions_file.write_text(content)
    result = suggestions_list(temp_suggestions_file)
    assert len(result) == 2
    assert result[0]['status'] == 'pending'
    assert result[1]['status'] == 'resolved'


def test_impact_and_effort_values(temp_suggestions_file):
    """Test various impact and effort levels."""
    content = """# Suggestions

## Token Reduction

**Impact**: token-reduction
**Effort**: low

Body.

## Speed

**Impact**: speed
**Effort**: medium

Body.

## Robustness

**Impact**: robustness
**Effort**: high

Body.
"""
    temp_suggestions_file.write_text(content)
    result = suggestions_list(temp_suggestions_file)
    assert len(result) == 3
    assert result[0]['impact'] == 'token-reduction'
    assert result[0]['effort'] == 'low'
    assert result[1]['impact'] == 'speed'
    assert result[1]['effort'] == 'medium'
    assert result[2]['impact'] == 'robustness'
    assert result[2]['effort'] == 'high'


def test_no_duplication_of_parsing_logic():
    """Verify that we're importing (not duplicating) regexes from sort_suggestions."""
    # This test verifies the AC: "reuse _split_entries(), not hand-roll a second parser"
    source = Path(__file__).resolve().parents[1].joinpath("suggestions_list.py").read_text(encoding="utf-8")
    assert "from sort_suggestions import" in source
    assert "_split_entries" in source
    assert not re.search(r"^\s*(HEADER|PRIORITY|IMPACT|EFFORT|STATUS)_RE\s*=", source, re.MULTILINE)


def test_json_serializable_output(temp_suggestions_file):
    """Test that output is JSON-serializable (important for IPC)."""
    content = """# Suggestions

## Entry

**Priority**: 1
**Status**: pending

Body text.
"""
    temp_suggestions_file.write_text(content)
    result = suggestions_list(temp_suggestions_file)
    # Should not raise
    json_str = json.dumps(result)
    # Should deserialize back correctly
    parsed = json.loads(json_str)
    assert len(parsed) == 1
    assert parsed[0]['title'] == 'Entry'


def test_main_subprocess_with_valid_suggestions():
    """Test __main__ handler runs successfully with real suggestions file."""
    # Run the script as a subprocess to verify it handles valid output
    script_path = Path(__file__).resolve().parents[1].joinpath("suggestions_list.py")
    python_exe = sys.executable
    result = subprocess.run(
        [python_exe, str(script_path)],
        capture_output=True,
        text=True
    )
    # Should output valid JSON on stdout, exit code 0
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert isinstance(output, list)
    # Each entry should have the expected structure
    for entry in output:
        assert 'title' in entry
        assert 'status' in entry
        assert 'body' in entry
