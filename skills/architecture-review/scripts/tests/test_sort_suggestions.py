"""
Test to verify that _sort_key() correctly handles missing Priority fields.
"""
import sys
from pathlib import Path

# Import the module being tested
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sort_suggestions import _sort_key  # noqa: E402


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
