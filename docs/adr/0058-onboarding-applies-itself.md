# ADR 0058: Onboarding applies itself, so every project gets the same treatment

**Status:** Accepted (2026-10-08, Gil: "I want this to be automated so all projects get the same treatment from MARVIN").
Amends ADR 0036 ("each stage prints a plan and changes nothing until told to apply").

## Context

ADR 0036 built onboarding as plan-then-apply-on-command. The plans were refreshed hourly for every project with a
board, but nobody ran `apply`, and the plans themselves were wrong: the repo tree read had always failed (a POST
where a GET was meant), and a failed GitHub read was recorded as "missing". Of 13 projects with boards, 2 could be
built. Plan: `docs/plans/project-treatment-2026-10-08.md`.

## Decision

Every hour, for every project with a board, MARVIN applies the pieces that are safe without a person:

- **local, always:** triage and claim labels; a drafted execution profile with `dispatch: off` and
  `merge_from_dashboard: false`; the proof run once a profile exists;
- **in the project's repo, as a pull request, once:** the CI workflow and agent docs. The PR is the review (ADR 0036 R3).
  The PR closes an "Onboarding: agent docs and CI" ticket in that repo, filed first (reused if one is open) as
  `ready-for-human` with a complete "Your task", so the project's board has a card for it under In review and no agent
  builds it. No ticket, no PR: the run is `needs-human` and retried next hour. (Added 2026-10-09: the first seven
  onboarding PRs closed no ticket, so the MR Review/board parity check flagged every one.)

Still a person's decision (ADR 0036 R2 unchanged): switching dispatch or dashboard merges on, and anything the plan marks
`needs-human`.

A plan built from a failed GitHub read is never written over a good one; it's kept and marked stale.

## Consequences

- New repos reach the same standard without anyone remembering to onboard them.
- Each project's repo can receive one onboarding PR it didn't ask for; it waits in MR Review like any other.
- More GitHub calls per hour; onboarding re-inspects a repo only when it was pushed since the last plan, and stops when
  the budget is under the pipeline's guard.
