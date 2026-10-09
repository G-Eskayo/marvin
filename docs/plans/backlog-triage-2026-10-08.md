# Backlog triage, 2026-10-08 (marvin#305)

The one-time triage that output contracts asked for. Three piles had been filling with nobody acting on them. The
numbers come from `lib/output_contracts.py` and the files themselves, and the Health readout is live. **Nothing
has been deleted, archived or labelled.** Each proposal below needs your yes.

## Where things stand

| Producer | Output | Waiting | Last consumed | Health |
|---|---|---|---|---|
| architecture-review | `~/.claude/suggestions.md` | 50 pending | 40 days ago | red: removal candidate |
| safety-monitor | `~/.claude/quarantine.md` | 67 entries | never (no review ever recorded) | red: removal candidate |
| improvement-sweep | `~/.claude/improvement-queue.md` | 162 items in 32 dated sections | auto-fix, recently | yellow: 25 sections overdue |
| daily / research digest | `~/.claude/digest/`, `research-digest/` | n/a | not measured | yellow until the morning brief (#306) |

## Suggestions: 50 pending

- **Age:** 11 are under 14 days old, 5 are 14 to 30 days, 18 are 30 to 60 days, and 16 are 60 days or more.
- **Priority:** most are 3 to 4. Only 6 are 7 or higher.
- **Stale statuses:** some are already done but still marked pending.
  - The top one (priority 9) has three update notes saying most of it shipped; only `correlate.py`'s keyword table remains.
  - One suggestion says two others are already implemented.
- **Now wired:** ticket promotion takes the top 2 pending each day, on the Mini.
  - The writer includes only what the finding's own updates say remains, and marks the finding resolved when nothing does.
  - Promoted findings become `needs-triage` tickets, never `ready-for-agent`.
  - A dry run on the top suggestion produced a correct, well-formed ticket. It also showed why the "only what remains" rule was needed.

**Proposal S1:** let promotion drain the pile (about 25 days at 2 a day).
**Proposal S2:** mark the 16 suggestions that are 60+ days old with priority 4 or below as `declined` in one pass, so promotion spends its slots on live ideas.

## Quarantine: 67 entries, never once reviewed

- **Sources:** research_colony 34, daily_digest 20, improvement_sweep 11, self_improve 2.
- **Age:** 53 are older than 30 days (the oldest is 96 days).
- **They're stale:** most are sections of daily digests, so their content was overtaken by the next day's digest.
- **Don't bulk-label them:** a review is a calibration label (approve or deny tunes the safety threshold). Labelling 53 stale entries in bulk would teach the threshold nothing true.

**Proposal Q1:** move the 53 entries older than 30 days to `quarantine-archive.md` without labels, and review the 14 recent ones.
**Proposal Q2:** decide whether digests need a safety gate at all once the morning brief is their single reader. If the brief quotes its sources, a person reads the brief and the gate adds little. Under the 30-day cut rule, the safety monitor stays a removal candidate until someone reviews regularly.

## Improvement queue: 162 items

- **By type:** VERBOSITY 110, KISS (function length) 34, NAMING 18. These are lint-style findings from `qa_scan`.
- **Auto-fix runs:** it fixes NAMING and VERBOSITY daily.
- **But the queue is a log, not a state:** fixed items are never removed, so the pile only grows and overstates what's left.

**Proposal I1:** make the sweep rewrite the queue to current findings each run (state, not history). Then "waiting" means "still true".
**Proposal I2:** stop queueing KISS "function is N lines long". It's a weak signal, and the north-star fit check on PRs already flags size where it matters.

## What changed in code (PR for #305)

- **Contracts:** every producer has an output contract, and Health shows each one.
- **Ticket promotion is wired:** daily on the Mini, top 2, as `needs-triage` tickets, and it skips what's already done.
- **The 30-day cut rule is live:** a producer whose output nobody consumes for 30 days shows red as a removal candidate.
