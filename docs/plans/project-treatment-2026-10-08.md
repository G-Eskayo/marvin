# Every project gets the same treatment from MARVIN — 2026-10-08

Gil, looking at the website map: "a lot of the project nodes are not connected… maybe gaps we need to fill with more
and better piping", then: "I want this to be automated so all projects get the same treatment from MARVIN."

## What the map showed, and why

Of 34 projects in the catalog, **13 have a ticket board**, and **2 can be built by the pipeline** (clarity-captions,
killer-sudoku). Everything else floats on the map, because nothing connects it.

Digging in found that most of this isn't the projects. It's MARVIN's onboarding, which is meant to bring every repo
up to the same standard (ADR 0036) and was quietly reporting nonsense:

| Finding | Effect |
|---|---|
| **The repo file list was never read.** `project_onboard.inspect()` calls `gh api …/git/trees/main --field recursive=true`; `--field` makes `gh` send a POST, GitHub answers 404, and the tree comes back empty. | Every project, MARVIN itself included, reads as "no recognised stack", "no test command", "missing docs/agents". So CI, the profile and the test command all became "needs a human" for all 13. |
| **A failed GitHub read is written as "missing".** At 16:44 on 2026-10-08 the GraphQL quota was exhausted; the hourly refresh rewrote all 13 plans saying triage labels were missing (they exist). | The readiness data can't be trusted; a quota outage looks like 13 broken projects. |
| **Plans are only made, never acted on.** Onboarding applies nothing unless someone runs `apply` by hand per repo. | 11 projects have had "missing" pieces since the plans were introduced. |
| **Most local copies live in iCloud `~/Documents`.** 13 projects, including clarity-captions, finance-os and killer-sudoku, sit in the folder that stopped being readable on the mini today (#192 fixed only the portfolio repo). | Background jobs block on them; the same failure is waiting for each. |
| **The GitHub budget runs out every hour.** 5,000 GraphQL points were used up twice in one afternoon. | Every check that needs GitHub (the pipeline, onboarding, the catalog) fails for part of each hour. |
| **The map draws only `builds`.** A project with a board, docs or a portfolio page shows no line for any of it. | Projects look disconnected even when MARVIN is tracking them. |

## The same treatment, automatically

One standard for every project, applied by MARVIN on its own every hour, reported in one place, drawn on the map. Each
row is a piece of the standard; the "how" column says what happens without anyone asking.

| Piece | Automatic | Needs Gil |
|---|---|---|
| Ticket board (Activity tab) | already automatic for every G-Eskayo repo | - |
| Triage + claim labels | **applied every hour** when missing | - |
| Execution profile (`config/projects/<repo>.json`) | **drafted** from the detected stack, `dispatch: off` | switching dispatch on (ADR 0036 R2, kept) |
| Test command | detected from the stack (once the tree is read) | only when the stack is unknown |
| CI workflow + agent docs | **opened as a pull request** in the project's repo, once; it appears in MR Review | approving the PR |
| Proof run (selftest on a clean worktree of main) | **run** once a profile exists, baseline recorded | - |
| Local copy outside iCloud | **flagged**; one command moves it (copy whole, verify HEAD/status/fsck, old copy renamed) | one approval for the batch |
| GitHub budget | onboarding re-reads a repo only when it changed (pushedAt), and backs off when the budget is low | - |
| On the map | `tracked` (board → Activity tab), `documented` (docs → Docs tab), `builds` (dispatch on), and a "not ready" look with the missing pieces in the hover line | - |

A project MARVIN should **not** build (a dormant course project, the Eagle Scout folder) still gets the same look:
it's marked `archived` in the catalog overrides and the map says so, instead of showing as a gap.

## Order

1. **Done:** **Fix the tree read** and make a failed GitHub read keep the last good plan, marked stale (bug, first: everything
   below depends on true data).
2. **Done:** **Auto-apply** the safe pieces every hour (labels, profile draft with dispatch off). The one-time PR for CI
   + agent docs: #259. ADR 0058 amends ADR 0036's "apply only on command".
3. #260 **Readiness on the map and in Health:** new thread types and a per-project "ready / not ready (why)" line.
4. #261 **Budget:** onboarding skips unchanged repos and backs off below the pipeline's 20% guard.
5. #262 **Move repos out of iCloud** with the #192 procedure as a command, after Gil approves the batch.
6. #263 **Archive** state for projects MARVIN should leave alone.

## Decisions

- 2026-10-08, Gil: automate it, so every project gets the same treatment (this plan, ADR 0058).
- Kept from ADR 0036: a person switches `dispatch` and `merge_from_dashboard` on; anything that changes a project's
  own repo arrives as a pull request.
- **Open, for Gil:** approve moving the 12 remaining repos out of iCloud `~/Documents` as one batch (step 5).
