# Final Verification Checklist — Ticket #646

## After Both Agents Complete

### 1. Verify No Errors in Agent Output
- [ ] Agent 1 (Batch A): All 17-18 files updated successfully
- [ ] Agent 2 (Batches B-E): All 30+ files updated successfully

### 2. Run Tests to Confirm Changes
```bash
# Python tests
~/.agents/venv/bin/python -m pytest lib/tests/test_instance.py -v

# Should show all 34+ tests passing
# Especially:
# - test_no_new_engine_file_hard_codes_an_owner_account_or_machine PASSED
# - test_the_grandfathered_list_only_shrinks PASSED
```

### 3. Empty the Grandfathered List
Once agents complete and tests pass:
```bash
# Empty the list (all files should be cleaned)
echo "" > lib/tests/instance_grandfathered.txt

# Verify it's empty
cat lib/tests/instance_grandfathered.txt  # Should output nothing
```

### 4. Re-run Ratchet Tests with Empty List
```bash
~/.agents/venv/bin/python -m pytest lib/tests/test_instance.py::test_no_new_engine_file_hard_codes_an_owner_account_or_machine -xvs
# Should PASS (no new offenders beyond grandfathered, which is now empty)

~/.agents/venv/bin/python -m pytest lib/tests/test_instance.py::test_the_grandfathered_list_only_shrinks -xvs
# Should PASS (grandfathered list is now empty, so the test confirms it)
```

### 5. Batch F — Evidence Scripts (if agents didn't complete this)
Required changes for 8 files in dashboard/scripts/*_evidence.mjs:
- [ ] Replace real repo names (G-Eskayo/clarity-captions, etc.) with generic fixtures (acme/example, etc.)
- [ ] Resolve HOME sentinel per Decision F (check for sandbox suffix, not hardcoded path)
- [ ] Files: check_progress, merge_progress, local_first, docs_merge, docs_saved, docs_search, files_viewer, chat_helpers

### 6. Batch G/H — Portfolio Add-on Identity (if agents didn't complete this)
Depending on decision outcome (new instance.json fields vs. document-as-Gil-only):
- [ ] brain-map/deploy_snapshot.py: WP_USER handling
- [ ] lib/portfolio_apply.py: WP_USER handling
- [ ] lib/portfolio_elements.py: © Copyright line
- [ ] brain-map/publish_map.py: REMOTE publish target

### 7. Batch I — Launchd Prefix Check (if agents didn't complete this)
- [ ] health_checks.py line ~159: Generalize `("com.marvin.", "com.giles.", "com.gileskayo.")` from `instance.owner().lower()`

### 8. Batch J — Historical Literals Exemption (if agents didn't complete this)
For files that describe historical data (NOT current owner):
- [ ] migrate_ticket_stages.py: `OLD_OWNER="G-Eskayo"` → add `# marvin:identity-literal` marker
- [ ] ticket_stages.py: `KNOWN_OWNERS={"g-eskayo":"G-Eskayo"}` → add `# marvin:identity-literal` marker

Update test regex to respect markers if using Decision J-A

### 9. Batch K — Remaining Stragglers (if agents didn't complete this)
Review instance_grandfathered.txt for any remaining files not covered in prior batches:
- [ ] lib/owner_decisions.py
- [ ] lib/sandbox_orchestration.py
- [ ] dashboard/webhook-server/* (if any still remain)

### 10. Batch L — Plist Templating
Create plist template substitution for 14 committed files:
- [ ] Create function in setup.sh or installation script to substitute `{{HOME}}` with actual `$HOME`
- [ ] Update all `*.plist` files to use `{{HOME}}/...` instead of `/Users/gileskayo/...`
- [ ] Extend `test_no_hardcoded_home.py` to scan `*.plist` files
- [ ] Add test for:
  - [ ] Missing HOME env var → clear error
  - [ ] Plist without `{{HOME}}` placeholder → left untouched
  - [ ] Plist with placeholder → substitution works

### 11. Final Ratchet Test
```bash
# Verify nothing new was added after the grandfathered list was emptied
~/.agents/venv/bin/python -m pytest lib/tests/test_instance.py::test_no_new_engine_file_hard_codes_an_owner_account_or_machine -xvs
# Should PASS
```

### 12. Run Full Test Suite
```bash
# All instance tests
~/.agents/venv/bin/python -m pytest lib/tests/test_instance.py -v
# Should show 34+ tests passing

# Boot data tests (if they exist and weren't changed to break)
# (Verify no regressions in related boot sequence tests)
```

### 13. Verify Git Status
```bash
git status
# Should show:
# - Modified: 84 files (approximately)
# - New files: lib/tests/instance_grandfathered.txt (now empty or removed)
# - Deleted: nothing (all changes are additions, not deletions)
```

### 14. Create Commits (if Decision pr_batching = A)
One PR with commits organized by category:

```bash
# Stage and commit by category (A through L)
# Category A commits (repos/owners as defaults):
git add lib/ticket_pipeline.py lib/run_ticket.py ... 
git commit -m "Batch A: use instance.tickets_repo() instead of REPO constant defaults

Applies the repo/owner constant pattern to 17 files in lib/. Changes function
signatures from \`repo: str = REPO\` to \`repo: str | None = None\` and add
\`repo = repo or instance.tickets_repo()\` at function start. Each file's
existing tests now exercise non-default repo values.

Fixes #646."

# Category B commits (owner-as-URL-builder):
# ... similar pattern for each batch
```

### 15. Open PR for Review
```bash
gh pr create --title "Make MARVIN configurable for different owners (ADR 0071 step 3)" \
  --body "..."
```

## Common Ratchet Test Errors

**Error: "no longer hard-codes an identity; remove from instance_grandfathered.txt"**
→ A file was fixed but not removed from the grandfathered list. Remove the file name from the list.

**Error: "use lib/instance.py instead of hard-coding: [files...]"**
→ A file still has hardcoded owner/account/machine. Run grep to find it and fix.

**Error: "if any(IDENTITY.search(l) and not COMMENT.match(l) for l in lines)"**
→ Your change has a quoted owner name. Ensure it's inside a function call like `instance.owner()` or a comment starting with `#`.

## Timeline Estimate
- Agents running: ~5-10 minutes (Batches A-E: ~40 files)
- Batches F-K: ~5-10 minutes (if not in agent work)
- Batch L (plist): ~5-10 minutes
- Tests + cleanup: ~2-3 minutes
- **Total**: ~20-30 minutes total for the full ticket

Once agents complete, the PR can land in one session.
