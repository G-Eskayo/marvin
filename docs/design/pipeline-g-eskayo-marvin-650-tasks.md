# Ticket #650 Planning & Handoff

## Completed Work

✅ **Step 1 — Design doc drafted**
- File: `docs/design/ios-update-maintainer-2026-10-27.md` 
- Sections: Why (2026-09-08 timeline surprise), Trigger mechanism + cost, Build targets, Reusable patterns, Stages/owner gates, Known traps, Decisions block, Slices, Tests, Roadmap
- 12 mechanical tests identified (tests 1–12) for misuse verification

✅ **Step 4 — Four slices identified**
- Slice 1: Release-feed watcher + state store
- Slice 2: Playbook dispatch & build integration  
- Slice 3: Release-notes keyword flagging
- Slice 4: Multi-project wiring (marvin-mobile, nourished, killer-sudoku)

## Blocking: Instance Repo Push (Step 2)

The design doc must be moved to `~/.agents/instance/docs/plans/` and committed to the private instance repo. This cannot be done in this headless, non-interactive session (no write access to ~/.agents/instance). 

**Handoff:** A person or a separate process must:

```bash
# Copy to instance repo
cp docs/design/ios-update-maintainer-2026-10-27.md \
   ~/.agents/instance/docs/plans/ios-update-maintainer-2026-10-27.md

# Commit to private instance repo
cd ~/.agents/instance
git add docs/plans/ios-update-maintainer-2026-10-27.md
git commit -m "iOS/macOS release watcher: design doc

Automatic compatibility agent for tracking Apple OS/Xcode releases.
Triggered by 2026-09-08 timeline-surprise incident. Generalizes through
existing playbook/profile layer. Four slices ready for implementation.

References: project-ios-update-maintainer-agent memory, ADR 0071, #613"
git push origin main
```

## Blocking: GitHub Issue Creation (Step 5)

Four slice issues must be created in G-Eskayo/marvin. This requires `gh issue create` which cannot run in this headless session.

**Each issue should:**
- Title: `iOS/macOS watcher: Slice N - <slice-name>`
- Labels: `enhancement`, `needs-triage`, `project:clarity-captions`
- Body: References to design doc + relevant acceptance criteria (tests from design doc section)
- Link to existing patterns: `lib/seal_beta_ingest.py`, `lib/task_dispatch.py`, `config/playbooks/ios-app.json`, etc.

**Slice issue templates** (ready to file):

### Slice 1: Release-feed watcher + state store
- Fetch Apple Developer News RSS (conditional GET)
- Parse version, build number, release-notes text
- Dedupe against local state file (reuse `seal_beta_ingest.py` pattern)
- Fail soft on errors
- **Tests:** 3, 4, 5, 6, 7, 10, 12 (from design doc)

### Slice 2: Playbook dispatch & build integration
- Extend `ios-app.json` playbook with "build against Xcode variant X"
- Wire release-detector output into dispatcher
- Machine selection via existing `task_dispatch.py`
- **Tests:** 6, 8, 9 (from design doc)

### Slice 3: Release-notes keyword flagging
- Parse release-notes for framework mentions (Speech, audio, ARKit, etc.)
- Flag on passing builds if keywords match
- Per-project config via `config/projects/*.json`
- **Tests:** 5, 6 (from design doc)

### Slice 4: Multi-project wiring
- Extend to marvin-mobile, nourished, killer-sudoku
- Parametrize per-project in `config/projects/*.json`
- Verify no config cross-contamination
- **Tests:** All tests (validates mechanism is general, not Seal-specific)

## Next: Verification (Step 3)

After instance-repo commit, verify engine-repo is clean:

```bash
git status  # Should show NO docs/plans/* changes
ls -la docs/plans/ 2>/dev/null || echo "docs/plans/ doesn't exist (correct)"
```

## Ready to Close #650 (Step 6)

Once:
1. ✅ Design doc is drafted (done)
2. ⏳ Design doc is pushed to instance repo (blocked on handoff)
3. ⏳ Engine repo is verified clean (blocked on step 2)
4. ⏳ Four slices are filed as GitHub issues (blocked on handoff)
5. ✅ This PR carries only standard planning artifacts (no `docs/plans/`, only this file + design doc)

**Comment on #650:**

```
Design doc complete and ready for implementation. Instance-repo push and
GitHub issue creation pending (requires interactive session or permissions
not available in headless context).

Design doc location: ~/.agents/instance/docs/plans/ios-update-maintainer-2026-10-27.md
Slice issues ready to file: 4 issues (Slice 1-4)

Decisions pending owner review:
- trigger-source: RSS (A), local check (B), or both (C)?
- beta-machine: MacBook (A), Mini (B), or separate VM (C)?
- beta-severity: Immediate (A) or GA-only (B)?
- ticket-home: Target project repo (A) or marvin+project-label (B)?
```

Then close #650.