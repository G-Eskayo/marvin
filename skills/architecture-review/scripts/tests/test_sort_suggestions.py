"""
Test to verify that _sort_key() correctly handles missing Priority fields,
and that _looks_merged() correctly detects entries merged with neighbors.
"""
import sys
from pathlib import Path

# Import the module being tested
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sort_suggestions import _sort_key, _looks_merged  # noqa: E402


def test_missing_priority_field_sorts_below_every_real_priority():
    """
    Verify that an entry without a Priority field sorts worse than any entry
    with an actual Priority value. This prevents suggestions created without
    the field from appearing at the top of the list.
    """
    # Fixture: entry with Priority=1 (the highest explicit priority)
    entry_with_priority_1 = """## Test suggestion
**Priority**: 1
**Status**: pending
**Impact**: token-reduction
**Effort**: low
**Why**: something
**What**: something
**How**: steps
**Added**: 2026-11-12
"""

    # Fixture: entry with no Priority field (the bug case)
    entry_without_priority = """## Test suggestion without priority
**Status**: pending
**Impact**: token-reduction
**Effort**: low
**Why**: something
**What**: something
**How**: steps
**Added**: 2026-11-12
"""

    key_with_priority = _sort_key(entry_with_priority_1)
    key_without_priority = _sort_key(entry_without_priority)

    # The entry with Priority=1 should sort BEFORE (better than) the entry without Priority.
    # In tuple sorting, this means its key should be less than the missing-priority key.
    assert key_with_priority < key_without_priority, (
        f"Entry with Priority=1 should sort better than entry without Priority. "
        f"Priority=1 key: {key_with_priority}, "
        f"No-Priority key: {key_without_priority}"
    )


# Tests for _looks_merged() function
def test_looks_merged_single_added_field():
    """A normal entry with a single **Added**: field should not look merged."""
    entry = """## Test suggestion
**Priority**: 1
**Status**: pending
**Impact**: token-reduction
**Effort**: low
**Added**: 2026-11-12
"""
    assert not _looks_merged(entry), "Entry with single **Added**: field should not look merged"


def test_looks_merged_single_priority_field():
    """A normal entry with a single **Priority**: field should not look merged."""
    entry = """## Test suggestion
**Priority**: 1
**Status**: pending
**Impact**: token-reduction
**Effort**: low
**Added**: 2026-11-12
"""
    assert not _looks_merged(entry), "Entry with single **Priority**: field should not look merged"


def test_looks_merged_multiple_added_fields():
    """An entry with multiple **Added**: fields looks merged (missing ## separator)."""
    entry = """## Test suggestion
**Priority**: 1
**Status**: pending
**Impact**: token-reduction
**Effort**: low
**Added**: 2026-11-12
**Added**: 2026-11-13
"""
    assert _looks_merged(entry), "Entry with multiple **Added**: fields should look merged"


def test_looks_merged_multiple_priority_fields():
    """An entry with multiple **Priority**: fields looks merged (missing ## separator)."""
    entry = """## Test suggestion
**Priority**: 1
**Status**: pending
**Impact**: token-reduction
**Effort**: low
**Added**: 2026-11-12
**Priority**: 2
**Status**: pending
**Impact**: organization
**Effort**: medium
"""
    assert _looks_merged(entry), "Entry with multiple **Priority**: fields should look merged"


def test_looks_merged_multiple_added_and_priority():
    """An entry with both multiple **Added**: and **Priority**: fields looks merged."""
    entry = """## Merged entry one
**Priority**: 1
**Added**: 2026-11-12
## Merged entry two
**Priority**: 2
**Added**: 2026-11-13
"""
    assert _looks_merged(entry), "Entry with multiple **Added**: and **Priority**: fields should look merged"


def test_looks_merged_no_added_or_priority():
    """An entry without **Added**: or **Priority**: fields should not look merged."""
    entry = """## Test suggestion
**Status**: pending
**Impact**: token-reduction
**Effort**: low
**Why**: something
"""
    assert not _looks_merged(entry), "Entry without **Added**: or **Priority**: should not look merged"


def test_looks_merged_single_fields_no_duplication():
    """An entry with properly separated sections should have single fields."""
    entry = """## First suggestion
**Priority**: 1
**Status**: pending
**Added**: 2026-11-12
**Why**: explanation here

## Second suggestion
**Priority**: 2
**Status**: pending
**Added**: 2026-11-13
**Why**: another explanation
"""
    # Only check the first entry (lines before second ##)
    first_entry = entry.split("## Second")[0]
    assert not _looks_merged(first_entry), "Properly separated entries should have single fields"


def test_looks_merged_case_sensitive():
    """Field matching should be case-sensitive (only **Priority**: and **Added**: count)."""
    entry = """## Test suggestion
**priority**: 1
**added**: 2026-11-12
**Status**: pending
**Impact**: token-reduction
"""
    # Lowercase variants should not match the regex
    assert not _looks_merged(entry), "Lowercase **priority**: and **added**: should not match"


def test_looks_merged_whitespace_variations():
    """The regex should handle whitespace after the field name."""
    entry = """## Test suggestion
**Added**:   2026-11-12
**Added**: 2026-11-13
**Priority**: 1
**Status**: pending
"""
    assert _looks_merged(entry), "Entry with multiple **Added**: regardless of whitespace should look merged"
