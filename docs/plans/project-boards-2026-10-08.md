# Tickets show up where the work matters, not where the code lives — 2026-10-08

Gil: "We have been doing a lot of stuff for portfolio-website-updater but I think all those tickets are getting routed to
the MARVIN Dashboard. Would it make sense to have an overarching dashboard and then subdashboards for every project?"
then "How do we make sure this isn't a repeating issue?" and, on archiving, "when a project has all cards completed it
can be moved to Archived, but when we want to start a new project related to that one or a new sub project, instead of
making a new board, MARVIN can check archived boards as well to see if we already covered it."

## What's wrong (measured 2026-10-08)

- A board is **one repo's** tickets (`dashboard/electron/main/boards.js` `fetchBoardData(repo)`).
- Of 97 open tickets in G-Eskayo/marvin, **22 are another project's work**: 12 for the website, 10 for MARVIN Mobile.
  They sit there because their **code** does (the portfolio tools, the map, the image maker, the mobile backend), and
  the pipeline can only build a repo with a profile (the portfolio repo has none yet, #235). The portfolio repo's own
  board shows 4.
- Nothing decides a ticket's project at filing time, so it will keep happening.

## Decision (ADR 0060)

1. **A ticket's project is its repo, unless it says otherwise.** A ticket for another project carries
   `project:<catalog id>` (e.g. `project:portfolio-website-updater`, `project:marvin-mobile`). The code stays where it
   lives; the label says whose work it is.
2. **A board is a project, not a repo.** A project's board = its own repo's tickets without another project's label
   + every ticket in any registered repo labelled for it. MARVIN's board stops showing other projects' work, and lists
   it in one folded "for other projects" row instead.
3. **The dashboard home is the overarching view**: every project's open work, what's running, what needs Gil. The
   per-project boards are the sub-dashboards. A UI change, not a rebuild: the project board gets the cross-repo
   tickets, MARVIN's board gets the folded row, the home gets one card per project.

## Making sure it doesn't come back

- **Rule where every filer reads it:** `docs/agents/issue-tracker.md` (the to-issues, triage and ticket agents read
  it) says when to add `project:<id>`.
- **An automatic tagger, no AI:** hourly, with the ticket agents. A ticket whose title or body names another project
  (its catalog id, name or aliases, its site paths like `gileskayo.me` / `/wp-content/`, its code like
  `lib/portfolio_*`, `mobile-backend/`) gets that project's label when the signal is unambiguous; anything else is
  listed for Gil to pick, never guessed. Rules live in `config/project_tags.json`, so a new project is a data change.
- **A Health check:** "N tickets look like another project's but aren't labelled". Red when it grows, so drift is
  visible the day it starts.

## Archive lifecycle (Gil's addition)

- **Done means archived, automatically:** a project whose board has every ticket closed and no open PR, quiet for
  14 days, moves to the dashboard's **Archived** section. Nothing is deleted; the board, its history and its docs stay
  searchable. Archiving the GitHub repo stays a person's decision (it makes the repo read-only, and discovery already
  retires the board of a GitHub-archived repo).
- **Before any new board, check the archive.** When MARVIN would create a board (a new repo, onboarding, "start a
  project for X", a sub-project), it first searches active **and archived** boards and the catalog: name, aliases,
  description, and meaning (the local `nomic-embed-text` embeddings already on both Macs). A close match is offered
  instead: reopen that board, or add the work to it as a sub-project (`project:<parent>` + `area:<sub>`). A new board
  is made only when nothing fits, and the check's top matches are shown so the choice is visible.
- Why: boards, labels, onboarding plans and profiles accumulate per project; reusing what exists keeps them bounded.

## Done today

- Labels created and applied: `project:portfolio-website-updater` on #189, #235, #268, #269, #270, #281, #283, #284,
  #285, #286, #287, #288; `project:marvin-mobile` on #152, #153, #154, #162, #163, #164, #165, #167, #272, #273.
- Personal-Website and Portfolio_Website (earlier versions of the portfolio site) archived on GitHub; discovery now
  retires the board of any GitHub-archived repo.

## Tickets

1. Project boards gather tickets across repos by `project:` label; MARVIN's board folds other projects' tickets.
2. Dashboard home: one card per project (open, running, needs Gil) as the overarching view.
3. The project tagger + `config/project_tags.json` + the Health drift check; the filing rule in `issue-tracker.md`.
4. Archive lifecycle: auto-archive a finished, quiet board; check archived boards (and the catalog) before creating one.
