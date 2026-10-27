# ADR 0064: Auto-merge low-risk PRs, judged by what they touch, earned per project, braked by main-health

**Status:** Accepted (2026-10-09, Gil, #332 design session). Builds on ADR 0061 (overlap rule) and ADR 0063 (tests try
to break it). The governor (#327) later sets its pace.

## Context

A pipeline PR waits a median 9.4 h for Gil's Approve (last 46) while building takes ~25 min; only 5 pipeline PRs have
ever been closed unmerged. Gil approves almost everything, so the wait is pure cost. Gil wants MARVIN to own its own
systems ("things that don't affect core files or deleting my files", 2026-07-08).

## Decision

**Low-risk = what a PR touches**, with green checks, a passing merge gate and a green main always required:

- **Owned areas** auto-merge: pipeline workings, background jobs, ticket and board upkeep, Health + Metrics (fixes).
- **Core areas** always wait for Gil: the merge gate and auto-merge itself, hooks / settings / permissions, sync,
  secrets, anything that deletes files. One core file makes the whole PR wait.
- **Always waits too:** adding or upgrading a dependency; more than 1,500 changed lines; finance-os (always).
- **The rules** live in one readable file, which is itself core. A new folder inherits its parent's area; a new
  top-level folder counts as owned, at most 3 a week; Health tracks growth.
- **Tests must try to break it:** the PR's tests catch ≥ 80 % of bugs planted in its changed lines (mutation check).
- **Other projects earn it:** a trusted test command, core paths in the profile, then 5 clean pipeline PRs approved
  by Gil; a denial, revert or post-merge break resets the ramp to 5.

**Operation:**
- One auto-merge at a time, each waiting for main-health to pass on the previous one. A red main pauses all
  auto-merging (phone push); a red within 30 min of an auto-merge whose own tests fail on main is reverted
  automatically, once per incident; otherwise everything waits for Gil. No quiet hours.
- Gil sees an "Auto-merged" list with one-click **Revert** (immediate revert commit, optional one-line reason, ticket
  sent back with it, trust ramp reset), one line in the morning brief, and a phone push only on trouble.
- **Rollout:** 3 days of shadow mode on the mini (cards show what it would have done), then a report in the next
  session, the morning brief and an MR Review banner; it switches on only when Gil says yes.

## Consequences

- Most owned-area PRs merge within minutes of turning green; Gil reviews summaries, not every PR.
- Mutation checks add minutes to each PR and need tests that genuinely try to break the code (ADR 0063).
- The core list, the rules file and the brake are what keep this safe; none of them can change without Gil.

## Amendment (2026-10-26, Gil): a known incident's regression fix may merge itself, core areas included

Part of "solved problems stay solved" (`lib/incident_ladder.py`, CONTEXT.md). When a watched incident regresses and
first aid doesn't clear it, the ladder's rung 3 queues the incident for a pipeline build. Gil chose (Decisions,
`core-scope`): **that PR may merge without his Approve even when it touches a core area** (sync, hooks/settings,
deletion code), for **regressions of a known incident only**, with the auto-revert kept. Everything else here still
holds. The rules live in `config/auto_merge.json` (`known_incident_regressions`) and `lib/auto_merge_regression.py`:

- **Only a known incident's regression:** the PR was built for a ticket labelled `watch` and `regression`.
- **A failing-first regression test:** the PR's test files are run against the base commit (they must run and fail;
  a collection error doesn't count) and against the PR's head (they must pass).
- **The rest of this ADR:** mutation score ≥ 80 % (ADR 0063), a green main, passing checks, an open trust ramp; no
  dependency change, the size cap, plain paths, finance-os never.
- **Still core, even then (`still_core`):** the merge gate and auto-merge itself (this rules file, the policy, the
  trust ramp, the mutation check, main-health, the merge server) and secrets. A fix can never loosen the rules that
  let it merge.
- **One per incident per day.** After merge the incident's probe is re-measured over the time since the merge (after
  2 h); if it still trips, the merge is reverted (this ADR's revert path) and the trust ramp resets.
- **Rollout:** shadow first, like this ADR: each rung-3 PR records what it *would* do (merge; then keep or revert), and
  the morning brief carries the report. It switches on with this ADR's own switch, only when Gil says yes. Until then
  rung-3 PRs wait for his Approve like any core change.
- **Telling Gil:** a brief line and a phone notification when MARVIN fixed a regression itself, and when it couldn't.
