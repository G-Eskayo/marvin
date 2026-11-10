# Ticket #988 - Remaining Actions

**Status:** Verification complete, artifacts prepared, final actions pending

## Completed Verification (Steps 1-3)
✓ Re-fetched PR #981's current comments and commit log at execution time
✓ Confirmed `lib/box_build.py` / `config/dispatch.json` match all four Decisions claims  
✓ Re-checked issue #648 is still OPEN

## Prepared Artifacts (Ready to Use)

### 1. Follow-up Issue
**File:** `follow_up_issue_body.md`
**Command to execute:**
```bash
gh issue create --repo G-Eskayo/marvin \
  --title "Wire the box's marvin-build provisioning to the default-build installer (#648)" \
  --body "$(tail -n +2 follow_up_issue_body.md)" \
  --label "blocked"
```
**Expected outcome:** New issue created with number reported

### 2. PR Comment  
**File:** `pr_981_reply_comment.md`
**Command to execute:**
```bash
gh pr comment 981 --repo G-Eskayo/marvin \
  --body "$(cat pr_981_reply_comment.md)"
```
**Expected outcome:** Comment posted to PR #981 with `<!-- marvin:decisions-addressed -->` marker

## Verification After Actions

After posting the comment, verify with:
```bash
# Check that PR #981 shows as addressed
python lib/owner_decisions.py pr_status  # or check dashboard

# Ticket #988 self-closes when the comment is posted (per its footer hook)
```

## Key Evidence Files

For reference during execution:
- `DECISIONS_VERIFICATION.md` - complete verification of all Decisions claims
- `follow_up_issue_body.md` - ready-to-post issue body
- `pr_981_reply_comment.md` - ready-to-post comment body

## Blockers

Permission restriction: `gh` commands cannot be executed in current session mode ("don't ask" mode). 
These operations require elevated permissions that must be granted by the session operator.

## Next Steps for Operator

1. Run the two gh commands listed above from the worktree directory
2. Verify both operations completed successfully  
3. Check that the Decisions addressed marker was recognized
4. Confirm ticket #988 self-closes (usually via footer trigger)

---

**All verification work is complete. These are the only remaining operations needed to close ticket #988.**
