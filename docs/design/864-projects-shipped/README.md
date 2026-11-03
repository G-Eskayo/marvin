# Workshop ▸ Projects and Shipped (marvin#864), mock-up

**Status: mock-up for the owner's sign-off. The real dashboard (`dashboard/src`) is unchanged.**

#864 finishes the Workshop: **Projects** and **Shipped** join Now (#1030) and Proposals, and the MR Review and Activity
tabs go away. The look of Projects and Shipped wasn't mocked yet; this is that round, with #1028's lanes folded in (its
comment on #864: do the Projects mock-up together with #1028's design).

## What it shows

- **Projects**: one box per active project.
  - Header: the name (tapping it opens or folds the box), "N stuck · N your move · N in motion · N up next", what
    your moves are ("1 decision · 2 to approve"), and moving / stuck with PRs a week.
  - Under it: the goal's first clause with its signals, the **life track** (every open item as a mark on Ticket →
    Shipped, with how many sit at each stage, in the most urgent colour) and 14 days of ships, then the lanes (#1028).
  - Open: every ticket and PR in it, as Now's rows with a life strip each.
  - "Open the board ▸" shows the board. Its In review column holds the items themselves, each opening the item page
    (#863), not "N waiting in MR Review →".
  - Parked, done and archived fold into "N parked or done". Other (a PR whose project can't be worked out) comes last,
    with why. The parity line closes the list.
- **Shipped**: MR Review ▸ Merged's history, plus where each merge is live once its project has a ship step
  (ADR 0080 I4: both Macs pulled, a TestFlight build, a site published). **▶ A merge arrives** plays the merge motion
  and a ship step running.
- **Now**: built (#1030). Shown only for where #1041's Auto throttle card sits (its `place` was answered: Workshop ▸ Now).
- **Proposals**: unchanged (ADR 0068). Only its place moves.
- **What goes away**: before / after tabs, and every panel the old tabs show with where it lives after (the ticket's
  "nothing lost" checklist).

## Where each part comes from

| Part | From |
|---|---|
| Group order (most for you first, then size, then name; Other last), quiet groups folded, your choice saved, the name as the toggle, "what's yours" line, tiers inside a group, Other with why, one name per project | PR #935 (`mr_groups.js`, `MrGroups.jsx`, `project_names.js` / `project_catalog.display_name`) |
| Goal and signals, moving / stuck / held, PRs a week, "N parked or done", the board and its columns, due date | Activity (`ProjectGoals.jsx`, `project_progress.js`, `DashboardHome.jsx`, `ProjectBoard.jsx`) |
| Day groups, 5 days a page, refused approvals, reverted by, you / auto-merge, merge motion | MR Review ▸ Merged (`MrHistory.jsx`, `mr_history_view.js`, `MergeMotion.jsx`) |
| Rows (verb first, worker, waiting time), the as-of line | Now (#1030, `WorkshopTab.jsx`, `next_step.js`) |
| Tickets and PRs together per project, the life track and strip on every row, the lanes line, ships per day, "where it's live" | New |

## Open it

Inside MARVIN: the PR's **Try the mock-up** button (#938), or
`marvin-show docs/design/864-projects-shipped/index.html --pr 1052`. The dashed buttons at the top pick a view and
each Decision's options. Link a state with the hash: `index.html#view=projects&words=935&lanes=groups`,
`#view=shipped&ship=today`, `#view=gone`.

`node docs/design/864-projects-shipped/shoot.mjs <outDir>` takes the PR's screenshots and warns if a width scrolls
sideways.

## How it's made

- `projects_shipped.js` holds every rule, no DOM: the order, the fold, the header lines, the headings, the lanes, the
  track, the strip, where it's live, the day groups, the pages and the ledes. The page calls it on every click.
  `dashboard/test/projects_shipped_proto.test.js` tries to break it.
- `sample_data.js` is shaped like the real sources (catalog names, profile goals, next_step sections, `mr_groups.js`
  tiers, the Merged history rows). No private names.
- The look is the celestial-navigation tokens (#428, as `show_window.css` and #1041's mock-up). Fonts are bundled
  beside the page (OFL, from `@fontsource`), because the mock-up window has no network.
