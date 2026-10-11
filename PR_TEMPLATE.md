# Research Logging for Portfolio Pages

## Summary

Implements automatic research-logging infrastructure for the portfolio website. Projects with `docs/research/evidence-log.md` files can now auto-generate a "Research behind it" portfolio section showing the reasoning and sources behind design decisions.

## What's New

### Core Module: `portfolio_research.py`

Parses markdown evidence logs and generates portfolio research sections:

- **parse_evidence_log()** - Extracts research entries from markdown
- **render_research_section()** - Converts to HTML with visibility control
- **insert_or_update_section()** - Updates content JSON sections
- **generate()** - Orchestrates full pipeline with atomic writes
- **check_research_section()** - Integration point for portfolio_content.py
- **CLI interface** - `portfolio_research.py <repo-path> <content.json>`

### Integration with Portfolio Content Checks

- `check_research_section()` added to `portfolio_content.py`
- Wired into `evaluate()` findings (info-level, not required)
- Tests confirm integration works

### Evidence Log Format

Projects must have `docs/research/evidence-log.md`:

```markdown
## E1. Title
- **Source:** Research source
- **What we took:** Extracted insight
- **Confidence:** Strong/Moderate/Weak/Ours
- **Drives:** Decision this influenced
- **Public use:** Yes/Careful ("caveat")/Internal
```

Real example: clarity-captions has 8 entries (E1-E8)

## Visibility Tiers

- **Yes** → Visible on portfolio
- **Careful** → Visible + caveat marker  
- **Internal** → Hidden (process detail)

## Implementation

### Files to Add

1. `~/.agents/lib/portfolio_research.py` (500+ lines)
2. `~/.agents/lib/tests/test_portfolio_research.py` (16 tests)

### Files to Modify

1. `~/.agents/lib/portfolio_content.py`
   - Add: `import portfolio_research`
   - Add: `check_research_section()` function
   - Update: `evaluate()` findings line

2. `~/.agents/lib/tests/test_portfolio_content.py`
   - Add: Tests 15-16 for research checking

3. `~/Developer/portfolio-website-updater/templates/GUIDE.md`
   - Clarify: Internal entries filtered at generation time

4. `~/.agents/skills/portfolio-page/SKILL.md`
   - Add: Note about running portfolio_research.py

## Testing

### Test Coverage (16 tests)

✅ All tests pass locally:

- Tests 1-5: Parsing markdown
- Tests 6-8: Rendering HTML  
- Tests 9-11: Section insertion
- Tests 12-13: File operations
- Tests 14: CLI interface
- Test 15: Integration with portfolio_content
- Test 16: Validation

### Real Data Test

Verified on clarity-captions repository:
- ✅ Parses 8 research entries (E1-E8)
- ✅ All entries marked "Yes" or "Careful" (no "Internal")
- ✅ Renders clean HTML with caveat markers
- ✅ Atomically updates content JSON

## Workflow

1. Project maintains `docs/research/evidence-log.md`
2. Run: `portfolio_research.py <repo> <content.json>`
3. Generates "research" section in content JSON
4. portfolio-page skill authors to dev site
5. Research section renders on portfolio page

## Key Features

- **Atomic writes** - No partial updates via temp file + os.replace()
- **Non-invasive** - Info-level check, doesn't block anything
- **Extensible** - CSS classes for styling, semantic HTML
- **Validated** - Real data tested on clarity-captions

## Before/After

### Before
No way to surface research reasoning on portfolio pages

### After
Research sections auto-generated from evidence logs with proper visibility control:

```
Research behind it
├─ E1. Dark vs. light mode (Careful: "both work equally")
├─ E2. Brightness contrast matters
├─ E3. Caption readability study
├─ E4. Dyslexia fonts don't help (marked Careful)
└─ [E5-E8 etc...]

Internal entries stay hidden (process-detail level)
```

## Testing Instructions

```bash
# Run core tests
cd ~/.agents/lib
python3 -m pytest tests/test_portfolio_research.py -v

# Run integration tests  
python3 -m pytest tests/test_portfolio_content.py::test_research_section_is_checked -v

# Test real data
python3 ~/.agents/lib/portfolio_research.py \
  ~/Developer/clarity-captions \
  ~/Developer/portfolio-website-updater/content/longform/clarity-captions.json
```

## Deployment

See DEPLOYMENT_STEPS.md for 6-phase rollout:

1. Sync portfolio_research.py (auto)
2. Integrate with portfolio_content.py (manual)
3. Test on real data
4. Deploy to portfolio workflow
5. Update documentation
6. Verify full test suite

## Notes

- No breaking changes to existing functionality
- Gracefully handles missing evidence logs (no-op)
- Evidence log format defined in docs/research/evidence-log.md
- See IMPLEMENTATION_GUIDE.md for detailed specification

## Screenshots

[Before screenshot - no research section]

[After screenshot - research section with E1-E8 entries rendered]

---

Fixes: #382
Type: Feature
