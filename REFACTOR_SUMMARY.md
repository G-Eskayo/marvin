# Morning Brief Refactoring Summary

## Changes Made

This refactoring implements the tiered item-based morning brief system described in the plan.

### 1. resume_check.py
- **Added**: `strip_markup(text: str, max_len: int) -> str` - Extracted core character-stripping logic
- **Updated**: `sanitize()` now calls `strip_markup()` with TITLE_MAX

### 2. morning_brief.py

#### New Data Structures
- **Item dataclass**: Represents a brief item with section, line, summary, source, and rank
- **SECTIONS tuple**: ("World & security", "Research", "Your day", "Your projects")
- **Constants**: LINE_MAX=100, SUMMARY_MAX=200

#### New Builder Functions
- `_item_from_red_check()` → Your projects
- `_item_from_open_pr()` → Your projects (excludes waiting_on_marvin)
- `_item_from_human_ticket()` → Your projects
- `_item_from_top_ticket()` → Your projects
- `_item_from_regression()` → Your projects (needs-you kind only)
- `_item_from_auto_merge()` → Your projects
- `_item_from_deadline()` → Your day
- `_item_from_research_idea()` → Research

#### Dropped from Items
- launches, merged, revisited, digest_idea, waiting_on_marvin PRs

#### New Processing Functions
- `_build_candidates()` - Converts gathered brief data into candidate items
- `_dedup_key()` - Returns de-duplication key for each item
- `rank_items()` - Applies tiered ranking, de-duplication, and truncation to 5

#### Rewritten render()
- Outputs four fixed section headings (always present with empty-state lines)
- Maintains "Waiting on MARVIN" section for PRs with decisions in
- Maintains "Balance" section for late-night notes
- Maintains "Gaps" section for missing sources
- All externally-sourced strings sanitized

### 3. test_morning_brief.py

#### Updated Tests
- `test_sections_appear_in_order()` - Verifies four sections in correct order
- `test_numbers_always_come_with_titles()` - Updated for new repo prefix format
- `test_deadlines_count_down_and_hard_ones_say_so()` - Updated section names
- `test_a_late_night_gets_a_factual_nudge_never_a_guilt_trip()` - Updated section names
- `test_a_failing_source_is_named_not_hidden()` - Updated section names
- `test_writing_and_reading_mark_consumption()` - Updated section names
- `test_the_session_report_shows_todays_brief_first_and_that_marks_it_read()` - Updated section names
- `test_the_auto_merge_shadow_report_appears_when_ready()` - Rewritten for new structure
- `test_a_pr_whose_decisions_are_in_waits_on_marvin_not_on_gil()` - Updated for item-based structure

#### Preserved Tests
- Idempotency tests for write()
- Sidecar reading tests (builder_of)
- Fallback gate tests (build)
- open_prs waiting marking tests

## Verification

✅ No other modules depend on old section names ("Needs you", "Overnight", "Today")
✅ Utility functions (show_today, builder_of, brief_dates, read_dates) unchanged
✅ All imports and syntax verified
✅ De-duplication by (repo, number) or normalized line implemented
✅ Tiered ranking (3 tiers → 5 ranks) with stable tie-breakers implemented
✅ Four fixed sections with empty-state lines implemented

## Next Steps

Run full test suite to verify:
```
MARVIN_MERGE_GATE=1 pytest -n auto
```

This will confirm:
1. All test_morning_brief.py tests pass
2. No other modules fail due to section name changes
3. Integration with session_start_report works correctly
