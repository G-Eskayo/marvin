# Apple Release Maintainer: Autonomous Decisions (2026-10-27)

**Status:** Autonomous decisions made pending Gil's review/override.

These decisions were made autonomously to unblock ticket filing. They follow MARVIN's philosophy of automation, composability, and reducing manual work. Gil can override any of these in the PR review.

## From apple-release-maintainer-2026-10-27.md

### feed-trigger
**Decision: Only speech-audio releases**
- Balances notification load (weekly Xcode betas) against signal (Speech/audio ~2/month)
- Rationale: keeps Gil in loop for framework changes most likely to break Seal Speak, without spamming on every beta
- Alternative if noise: escalate to "only actual probe failures"

### probe-trigger
**Decision: Automatic, daily (Tuesdays in run_colony.py)**
- Most reliable: never missed
- Tied to existing daily research-colony run, no new cron job
- Bounded by Apple's real release cadence (~weekly)

### ticket-surface
**Decision: Single release checkpoint ticket per release**
- Simplest: one ticket consolidates all project probe results and flags
- Title template: `"Xcode X.Y beta checkpoint"`, body shows each project's status
- Easier to track than per-project tickets, easier to search than silent logging

### xcode-path
**Decision: Auto-detect from xcode-select -p**
- Simplest and most portable
- Fallback: if not found, log clearly and skip that build (fail open, marked as env issue not a real break)

---

## From pipeline-g-eskayo-marvin-650.md

### install-step
**Decision: Owner gate**
- Consistent with existing `ios-app` playbook (Gil owns decisions about beta toolchains)
- MARVIN detects missing Xcode/simulator and files a ticket for Gil to act on
- Avoids credential/unattended-install complexity

### scope
**Decision: Every profile already on ios-app playbook with xcode-requiring verify tier**
- Clarity-captions, marvin-mobile, killer-sudoku (all 3 have xcode requirement)
- Generalized from day one per north-star #4
- Automatically covers new ios-app projects added later

### flag-surface
**Decision: GitHub ticket on G-Eskayo/marvin**
- Same surface as real breaks, but with lower priority label (`priority:low`)
- Avoids silent logging (discoverable); avoids ticket noise (labeled clearly)
- Matches ticket-surface decision above (one checkpoint ticket per release)

### break-granularity
**Decision: One ticket per project per release**
- Simpler to reason about: project X broke on Xcode Y.Z with error Z
- Consistent with ticket-surface (single checkpoint ticket wraps all projects)
- Easier for Gil to triage/assign/close per project

### notes
None.

---

## Files affected

These decisions inform the 5 ticket slices to be filed:
- **Slice A** (RSS + dedupe): use apple_releases_seen.json for state
- **Slice B** (release-notes flag): flag items with Speech/audio keywords for Slice C
- **Slice C** (probe runner): enumerate ios-app profiles, dispatch probes to MacBook, bubble failures
- **Slice D** (ticket filing): file via to-issues template, one checkpoint per release per the decisions above
- **Slice E** (known_traps): document Xcode path detection in ios-app playbook

