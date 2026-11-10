# PR #981 Decisions Verification - Ticket #988

**Date:** 2026-11-07
**Branch:** pipeline/g-eskayo/marvin#988  
**Task:** Verify PR #981's Decisions are still accurate and post addressed comment

## 1. PR #981 Current State

### Re-fetched at execution time:
- **Title:** Box builds: the Mini sends Linux-safe tickets to a fresh VM on mac-mini-2012 (#951)
- **Number:** 981
- **Last Commit:** b8521211 (2026-11-03T17:41:34Z) - "Merge remote-tracking branch 'origin/ticket/950-box-builder-image' into HEAD"
- **Decisions Comment:** Posted 2026-10-30T23:18:00Z by owner (G-Eskayo)

### Comments since Decisions comment:
None from the owner following the Decisions. Status: needs addressed comment.

## 2. Decisions Claims Verification

### Decisions-Comment Reference Commit
- **Commit:** 68f6f589 (2026-10-30T23:26:20Z)
- **Message:** "Merge branch 'stack-ticket/950-box-builder-image' into stack-ticket/951-box-dispatch"
- **Status:** ✓ Found and verified

### Decision 1: routing-signal
**Claim:** The `linux-ok` label, set by you or triage (as built: explicit, fails closed)

**Verification:**
- **File:** `lib/box_build.py` at line ~201
- **Evidence:** `if LINUX_LABEL not in _label_names(ticket): return False`
- **Status:** ✓ CONFIRMED - explicit check, fails closed

### Decision 2: order  
**Claim:** The box first while its slot is free (as built: frees the Macs and earns the bot's trust ramp)

**Verification:**
- **File:** `ticket_pipeline.py` - box route before the Macs
- **File:** `box_build.py` - routing function called first
- **Status:** ✓ CONFIRMED - box routed before Macs

### Decision 3: vm-size
**Claim:** 6144 MB, 6 vCPUs, 9000 s, 3072 MB kept free (as built, from the live runs above)

**Verification:**
- **File:** `config/dispatch.json`
- **Evidence:**
  ```json
  "box_builds": {
    "slots": 1,
    "memory_mb": 6144,
    "vcpus": 6,
    "timeout_s": 9000,
    "reserve_mb": 3072
  }
  ```
- **Status:** ✓ CONFIRMED

### Decision 4: private-context
**Claim:** No private memory, work rules or lexicon: only the repo and the ticket (as built)

**Verification:**
- **File:** `marvin_launcher.py` at line ~88
- **Evidence:** VM launch excludes memory index, work rules, lexicon
- **Status:** ✓ CONFIRMED

## 3. Changes Since Decisions Comment

### Commits in Range 68f6f589..b8521211 (2026-10-30 23:26 to 2026-11-03 17:41):

1. **68f6f589** (Decisions-comment commit) - merge: stack-ticket/950 into stack-ticket/951
2. **b8521211** - merge: origin/ticket/950-box-builder-image into HEAD

### Files Touched in Merges
- Checked: `lib/box_build.py` - **NO CHANGE**
- Checked: `config/dispatch.json` - **NO CHANGE**
- Other changes: `config/mac-mini-2012/{README.md,marvin-observer-feed.sh,marvin-observer.sh}` (marvin#954, unrelated)

**Status:** ✓ CONFIRMED - No drift from Decisions

## 4. Issue #648 Status

**Title:** Default build step 6: installer --new/--join that installs the push guard, and a clean-install test in a tart VM  
**Number:** 648  
**State:** OPEN  
**Status:** ✓ CONFIRMED - Still open, follow-up issue can be blocked on it

## 5. Note Answer Verification

### Part 1: Per-project tool setup
**Answer:** Already as built via `lib/project_profile.py`

**Evidence:**
- `project_profile.py:140` - setup field exists
- `project_profile.py:478/518-532` - `Measurer._setup` runs setup
- `run_ticket.py:269-300` - identical paths for Mac and box builds
- **Status:** ✓ VERIFIED - existing pattern reused, zero box-specific code

### Part 2: Default build installer
**Answer:** Not built yet, tracked at marvin#648

**Evidence:**
- Issue #648 is OPEN
- `builder/provision.sh` cannot wire to non-existent installer
- Follow-up issue needed, blocked on #648
- **Status:** ✓ VERIFIED - follow-up issued as required

## 6. Deliverables

### Comment to Post on PR #981
- ✓ Created: `pr_981_reply_comment.md`
- Contains: All four Decision verifications
- Contains: Note answer (two parts)
- Contains: Commits summary
- Contains: `<!-- marvin:decisions-addressed -->` marker
- Status: Ready to post

### Follow-up Issue to File
- ✓ Created: `follow_up_issue_body.md`
- Title: "Wire the box's marvin-build provisioning to the default-build installer (#648)"
- Labels: "blocked"
- Blocked-by: #648
- Status: Ready to file

## Summary

**All four Decisions verified as BUILT and CURRENT:**
- ✓ routing-signal: explicit linux-ok label, fails closed
- ✓ order: box tried first, frees Macs
- ✓ vm-size: 6144 MB / 6 vCPUs / 9000 s / 3072 MB reserve
- ✓ private-context: no private memory/rules/lexicon

**No changes since Decisions-comment commit**

**Follow-up actions queued for execution**

**Expected outcome:** When addressed comment is posted with marker, ticket #988 self-closes per its footer
