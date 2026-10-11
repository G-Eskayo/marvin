# Deployment Steps for Research Logging Feature

## Overview

This document describes how the research-logging feature will be deployed from this worktree to the live system.

## File Sync Map

The following files in this worktree need to be synced to their real locations:

### Primary Implementation Files

1. **portfolio_research.py** (worktree)
   → `~/.agents/lib/portfolio_research.py` (real location)
   
2. **test_portfolio_research.py** (worktree)
   → `~/.agents/lib/tests/test_portfolio_research.py` (real location)

### Integration Files (require manual edits or patches)

3. **portfolio_content_additions.py** (worktree - reference only)
   → Edit `~/.agents/lib/portfolio_content.py`:
   - Add import: `import portfolio_research`
   - Add function: `check_research_section()`
   - Update `evaluate()`: Add `+ check_research_section(c)` to findings line

4. **PORTFOLIO_CONTENT_CHANGES.md** (worktree - reference only)
   → Edit `~/.agents/lib/tests/test_portfolio_content.py`:
   - Add tests 15-16 for research section checking

### Verification Scripts (worktree only - for reference)

5. **run_tests.py** - Local test runner for core functionality
6. **test_portfolio_content_research.py** - Isolated integration tests
7. **test_clarity_captions_pipeline.py** - Real data tests
8. **IMPLEMENTATION_GUIDE.md** - Implementation reference
9. **PORTFOLIO_CONTENT_CHANGES.md** - Detailed change list

### Documentation Updates (requires manual edits)

10. **templates/GUIDE.md** (in portfolio-website-updater repo)
    → Update to describe actual enforcement:
    - Internal entries never render
    - Careful entries carry a caveat marker
    - This is NOT a live cross-repo drift check

11. **~/.agents/skills/portfolio-page/SKILL.md**
    → Add note: "If the project has docs/research/evidence-log.md, run portfolio_research.py before authoring"

## Deployment Process

### Phase 1: Core Implementation (Auto-sync)

Files 1-2 are the main implementation. After this sync:

```bash
# Verify the implementation
cd ~/.agents/lib
python3 -m pytest tests/test_portfolio_research.py -v
```

Expected: All 13 core tests pass (tests 1-14, excluding 15-16 which require portfolio_content.py changes)

### Phase 2: Integration with portfolio_content.py (Manual)

Apply changes from PORTFOLIO_CONTENT_CHANGES.md:

1. Add import to `~/.agents/lib/portfolio_content.py`
2. Add `check_research_section()` function
3. Update `evaluate()` to call it
4. Add tests 15-16 to test file

Verify:
```bash
cd ~/.agents/lib
python3 -m pytest tests/test_portfolio_content.py::test_research_section_is_checked -v
```

### Phase 3: Real Data Test

After both phases are deployed:

```bash
cd ~/.agents/lib
python3 -m pytest tests/test_portfolio_research.py -v
```

Then run on real clarity-captions data:

```bash
python3 ~/.agents/lib/portfolio_research.py \
  ~/Developer/clarity-captions \
  ~/Developer/portfolio-website-updater/content/longform/clarity-captions.json
```

This reads the evidence log and updates the content JSON with a new research section.

### Phase 4: Portfolio Integration (Manual via portfolio-page skill)

Run the portfolio-page skill with the updated clarity-captions.json:

```bash
# Step 5 of portfolio-page skill
python3 ~/.agents/lib/portfolio_longform.py ~/Developer/portfolio-website-updater

# Then sync/evaluate
python3 ~/.agents/lib/portfolio_sync_dev.py
```

Verify on dev site: research section renders correctly with visible entries and hidden internal entries.

### Phase 5: Documentation Updates (Manual)

1. Edit `~/Developer/portfolio-website-updater/templates/GUIDE.md`:
   - Clarify that Internal entries are filtered at generation time, not at rendering
   - Careful entries get caveats but still render

2. Edit `~/.agents/skills/portfolio-page/SKILL.md`:
   - Add: "If the project has docs/research/evidence-log.md, run portfolio_research.py before authoring"

### Phase 6: Verification

Full test suite:

```bash
cd ~/.agents/lib
python3 -m pytest tests/ -v -k research

cd ~/Developer/portfolio-website-updater
python3 -m pytest tests/ -v -k research
```

## Testing Checklist

- [ ] `test_portfolio_research.py` tests 1-14 pass
- [ ] `test_portfolio_content.py` test 15 passes (research-section-is-checked)
- [ ] `test_portfolio_content.py` test 16 passes (research-section-is-included-in-evaluate)
- [ ] Real data pipeline runs successfully on clarity-captions
- [ ] Research section renders on dev site with correct entry order
- [ ] Internal entries do NOT appear on dev site
- [ ] Careful entries show caveat text
- [ ] No regressions in existing portfolio tests

## Rollback Plan

If issues are found:

1. **Implementation issue** → Remove `~/.agents/lib/portfolio_research.py` and revert tests
2. **Integration issue** → Revert changes to `portfolio_content.py`
3. **Data issue** → The atomic writes mean bad data never replaces good data; just re-run with correct inputs

## Success Criteria

- ✅ All 16 tests pass
- ✅ Real clarity-captions evidence log parses without warnings
- ✅ Research section generates with 8 visible entries (E1-E8)
- ✅ Internal entries (if any) are hidden
- ✅ Dev site renders the section correctly
- ✅ No existing functionality is broken
