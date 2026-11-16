# MARVIN Gotchas.md Migration Summary

## Plan Implementation Status

### ✓ Step 1: Create `skills/diagnose/gotchas.md`
- Created with heading: `# Diagnose — MARVIN-specific gotcha classes`
- Includes one-line intro: "Read early in Phase 3 when the symptom fits, before deeper instrumentation. Append new confirmed incidents here, not in SKILL.md."
- Contains all 32 bullets copied verbatim from `SKILL.md` lines 81-112 in original order

**File stats:**
- 37 lines total (including header, intro, and blank lines)
- 32 bullet points (lines 5-36)

### ✓ Step 2: Edit `skills/diagnose/SKILL.md`
- Replaced lines 80-112 (intro + 32 bullets) with single pointer line
- **New line 80:** `**MARVIN-specific gotcha classes:** read [`gotchas.md`](gotchas.md) (same folder) early when the symptom fits, before deeper instrumentation. Add new confirmed incidents there, not here.`
- Pointer positioned immediately before blank line leading into Phase 4

**File stats before/after:**
- Original: 155 lines
- After: 123 lines
- Reduction: 32 lines (the bullets)

### ✓ Step 3: Verify Migration
**Bullet count verification:**
- Original SKILL.md lines 81-112: 32 bullets
- Migrated to gotchas.md: 32 bullets (lines 5-36)
- Remaining in SKILL.md: 0 bullets

**Content verification:**
- All bullets in gotchas.md match original SKILL.md content exactly
- No bullets remain inline in SKILL.md Phase 3 section
- Pointer line correctly references gotchas.md with relative path

### ✓ Step 4: Verify No Dangling References
**Files checked for "gotcha" references:**
- `CLAUDE.md`: No references ✓
- `skills/diagnose/SKILL.md`: Only expected pointer reference ✓
- `skills/diagnose/gotchas.md`: Expected content ✓

**Bullets verification:**
- No `- *` bullet patterns remain in SKILL.md Phase 3 section ✓

## Completion Status: READY FOR COMMIT

All steps of the plan have been successfully implemented:
1. New gotchas.md created with correct structure and all 32 bullets
2. SKILL.md updated with pointer line
3. Migration verified (32-for-32, verbatim, in-order)
4. No dangling references or inline bullets remaining
