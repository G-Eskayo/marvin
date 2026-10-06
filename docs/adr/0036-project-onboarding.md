# 0036. Project onboarding: a repo becomes a fully wired MARVIN project from one command

Date: 2026-10-06. Status: **accepted** (Gil confirmed D1-D4 on 2026-10-06); nothing built yet.

Not to be confused with ADR 0034's "add-project pipeline", which creates *portfolio website pages*. This is about
repositories that MARVIN builds, tests and merges for.

## Context

Getting clarity-captions, killer-sudoku and finance-os working took a long day of hand-built setup, and most of
the day's failures were setup gaps, not code bugs:

| What went wrong | The missing piece |
|---|---|
| finance-os ran "unit tests" 14 times with `Missing script: "test"` | the project had no test command; nothing checked |
| PR #8 "merged" but never reached main | nothing checked the PR's base branch |
| app builds collided ("database is locked") | build output folder was shared, set by hand |
| PRs conflicted on `graphify-out/` and the lockfile | generated-file rules did not exist, then were hand-added |
| no repo had CI | hand-written workflows, three times |
| `workflow` scope missing, pushes refused | discovered at push time |
| the pipeline would not run a repo at all | a hand-written `config/projects/<repo>.json` per project |

What is already automatic for any repo under G-Eskayo: a dashboard board (hourly discovery), the `claimed:*` and
`needs-reengagement` labels (created on first use), the ticket agents, and the MR Review checks that read GitHub's
own data (merge order, wrong base, conflicts, CI state). Everything else is per-project and manual.

## Requirements

1. **R1 One command, whole project.** Given `owner/repo`, produce every piece a project needs: execution profile,
   CI workflow, triage labels, agent docs, board, a clone and toolchain check.
2. **R2 Safe by default.** `dispatch` stays `off` and `merge_from_dashboard` stays `false` until a person turns them
   on, and onboarding refuses to *offer* either until the project's own checks pass on its main branch.
3. **R3 Reviewable.** Anything that lands in the target repo arrives as a pull request. Local configuration is
   written locally, with the diff shown first.
4. **R4 Idempotent.** Re-running fixes drift (a deleted label, a missing file) without duplicating or overwriting
   what a person edited.
5. **R5 Honest about unknowns.** An unrecognised stack, or a project with no test command, produces a short
   "needs a human" list, never a guessed command.
6. **R6 Proven, not assumed.** The plan ends with a real run of the project's checks on a throwaway worktree of
   main (the existing `project_profile.py selftest`), and records the baseline.
7. **R7 Visible.** Every project has a readiness row in Health: which pieces exist, which are missing, which need a
   person. A new repo gets that row automatically, with no action from anyone.
8. **R8 Reuse, compose.** Built from what exists: `board_registry.ensure_board`, `project_profile` (selftest,
   gate-info, verify), `generated_paths`, the `setup-matt-pocock-skills` doc templates. New stacks are data, not code.

**Non-goals:** portfolio pages (ADR 0034); production deploys or store submission; secrets handling; auto-switching
dispatch or merge on.

## Design

Four stages. Each prints a plan and changes nothing until told to apply.

1. **Inspect** (read-only). Repo visibility and default branch; the file tree for stack markers (`Package.swift`,
   `*.xcodeproj` / `project.yml`, `package.json` and its scripts, `pyproject.toml`, `.github/workflows/`); existing
   labels; `docs/agents/`; whether a test command exists; tracked lockfiles and generated directories.
2. **Plan.** One JSON document listing every piece with a state: `ok`, `missing` (onboarding can create it),
   or `needs-human` (it cannot, with the reason). This document *is* the Health readiness data (R7).
3. **Apply** (per group, all on by default except where noted):
   - **labels**: create the missing triage and claim labels (idempotent).
   - **profile**: draft `config/projects/<repo>.json` from the stack template, `dispatch: off`, `merge_from_dashboard: false`.
   - **repo PR**: `.github/workflows/ci.yml`, `docs/agents/*.md` and the CLAUDE.md "Agent skills" block, on a branch.
   - **board**: `ensure_board`.
   - **clone and toolchain**: resolve or create the clone; list missing tools for the profile's machines.
4. **Prove.** Run the selftest. If it fails, the plan says why and the project stays off. If it passes, the plan
   *offers* `merge_from_dashboard` and then `dispatch`, and waits for a person.

**Stack templates** live in `config/onboarding/<stack>/` as data: a profile fragment, a `ci.yml`, and a notes file.
v1 stacks: `swift-package`, `xcodegen-app`, `node-electron`, `python`. A new stack is a new folder. Templates encode the lessons
above: per-run build folders, generated-path rules for tracked lockfiles, `macos-26` only for public repos (macOS
minutes are 10x on private ones), a pinned Node version.

**Detection of generated files** is a *proposal*: tracked lockfiles and obvious generated directories are listed with
their `generated` rule, marked "confirm", never applied silently (some are deliberately tracked).

## Architecture

- `lib/project_onboard.py`: `inspect`, `plan`, `apply`, `prove`; CLI `project_onboard.py plan|apply|prove <repo>`.
  Pure planning functions over gathered facts (the pattern used by `ticket_evidence.py` and `generated_paths.py`), so
  every rule is unit-tested with fixtures, and `gh`/git sit behind small injectable wrappers.
- `config/onboarding/<stack>/`: the data above.
- **Trigger**: the hourly scan's board discovery already finds new repos; it additionally runs `plan` (read-only)
  and stores the result at `~/.claude/onboarding/<repo>.json`. `apply` and `prove` run only on request.
- **Health tab**: a "Project readiness" panel reading those files; a check flags a project that has tickets but no
  profile ("MARVIN cannot run this project").
- **Docs tab / catalog**: unchanged; the plan links to the repo's `CONTEXT.md` and ADR folder.

## Decisions (confirmed by Gil, 2026-10-06)

- **D1. Repo-changing files go through a PR**, not a direct push. (One review click per project.)
- **D2. Read-only `plan` runs automatically for every new repo**, and shows in Health.
- **D3. Switching on `merge_from_dashboard` and `dispatch` stays a human act**, offered only after a passing selftest.
  The alternative (auto-enable merge after a green selftest) was rejected.
- **D4. v1 stacks: `swift-package`, `xcodegen-app`, `node-electron` and `python`.** Python was added at Gil's request,
  against the recommendation to wait for a real project. Marvin's own suite shows why it is the hardest template:
  unpinned dependencies (chromadb, sentence-transformers, torch) and tests that read machine-local state. So the
  Python template must *detect* both (no requirements file; tests touching `~` or `~/.claude`) and report them as
  `needs-human` instead of generating a CI job that would be red for environmental reasons.

## Consequences

- A new project reaches "fully wired, awaiting your switch" in minutes instead of a day, and the same defects cannot
  recur silently: each row of the table above becomes a readiness check.
- Cost: template maintenance (a template that rots gives a wrong profile), and one more Health panel.
- Risk: a template encodes an assumption that is wrong for one project. Mitigated by R5/R6 (nothing is switched on
  without a real passing run) and by the dry-run diff.

## Tasks

Filed 2026-10-06 as tracer-bullet slices (test-first, each shippable on its own):

1. G-Eskayo/marvin#141 Onboarding plan for one stack: read-only `plan <repo>` (Swift package)
2. G-Eskayo/marvin#142 Onboarding plan for the Xcode-app and Node/Electron stacks
3. G-Eskayo/marvin#143 Onboarding plan for Python projects: detect unpinned environments and machine-local tests
4. G-Eskayo/marvin#144 Auto-plan new repos and show a readiness row per project in Health
5. G-Eskayo/marvin#145 Health check: a project with tickets but no profile is one MARVIN cannot run
6. G-Eskayo/marvin#146 Onboarding apply, local pieces: labels, board and a draft profile
7. G-Eskayo/marvin#147 Onboarding apply, repo pull request: CI workflow, agent docs and CLAUDE.md block
8. G-Eskayo/marvin#148 Onboarding prove: run the project's checks on main and record the baseline
9. G-Eskayo/marvin#149 Health switch-on controls for merge-from-dashboard and dispatch
10. G-Eskayo/marvin#150 First real onboarding run on a repo that has none of it, reviewed together
