# A MARVIN page that keeps up with MARVIN — 2026-10-08

Gil, after the map went live: "given the amount of changes we constantly make, should we build automations set off by
triggers for when to update the website with more accurate marvin architecture, descriptions, functionality?" and
"we have the phone connection and app coming up, we will add the linux box … use cases of everything that is a
functional tool is important to convey to users."

## The problem, measured

The map now updates itself (ADR 0057). The rest of the page is typed by hand and already wrong on 2026-10-08:

| On the page | Reality |
|---|---|
| "32 skills" (subtitle, heading, facts strip) | 35 |
| "2,102 tests on every change" | about 2,400 (1,362 library + 1,015 dashboard) |
| "30 pull requests it wrote that I merged" | far more (PRs #200 to #265 this week alone) |
| No mention of the mobile app, onboarding, parallel dispatch, the website map | all built or being built |

Copy goes stale whenever MARVIN changes, which is daily. Nobody can keep a hand-written page in step with that.

## Proposal: three layers, each updated by the cheapest thing that can do it right

### 1. Facts: automatic, no AI, published like the map

The facts strip, counts in headings and lists (skills by category, agents, machines, projects) come from the system:
the skill index, JOB_PLACEMENT, the machine registry, test runs (`bench/metrics`), merged PR counts from GitHub, the
catalog. `export_snapshot.py` writes them to `facts.json` in the map folder, behind the same privacy scan. The page shows
them with a small script, so a number changes on the live site the night it changes in MARVIN, without anyone touching
the page. This extends ADR 0057 to generated facts (needs Gil's yes).

### 2. Use cases: one card per functional tool, kept complete automatically

"What it can do" becomes a grid of use-case cards, one per tool a person would use or benefit from: each skill, each
background agent, each dashboard tab, the mobile app, each machine (the Linux box when it joins). Each card says:

- **the use case** in one line, from the user's side ("When a bug report comes in, `diagnose` …"),
- **a real example** (a ticket, a PR, a screenshot: proof, not a claim),
- **status**: live, being built, or planned (from the roadmap and open tickets).

The cards come from the map's own tree, so a new tool gets a card the day it appears. Like the plain hover lines, a
tool without a written use case is named by the build (never silently missing) and drafted for Gil to approve. Planned
tools (MARVIN Mobile, the Linux box) show as "coming next" with their ticket, and flip to live when the work ships.

### 3. The story: drafted on real triggers, approved by Gil

The narrative sections (why, how a session gets its context, failures, two Macs) change only when the architecture does.
Triggers, checked by the existing hourly reactive job:

- an ADR accepted, a new skill / agent / dashboard tab / machine, a new project in the catalog that MARVIN builds;
- not ordinary fixes (those only move facts).

On a trigger, MARVIN drafts the affected section in Gil's voice (`writing-style`), applies it to the **dev** page, and
opens a review item listing what changed and why. Gil approves; production stays his promotion. This is the only layer
that uses a paid model, a few times a month.

## The page rework this implies

1. Hero (matches the card, regenerated with the map).
2. **Explore the map** (live).
3. **Facts strip** (live, layer 1).
4. **What it can do**: use-case cards (layer 2), with "coming next".
5. The story sections, shorter, each linking to its cards (layer 3).

## Layer 4: every claim is checked, so the page stays TRUE (Gil, 2026-10-08)

Current is not the same as true. Layers 1-3 keep the page up to date; this layer proves what it says.

- **Claims ledger.** Each factual sentence on the page ("it runs on two Macs", "it proves every change with tests before
  I see it", "it's open source", "it keeps working while I'm away") is registered with a check that reads the system:
  the machine registry, the pipeline's verify step and merge gate, the repo's visibility, the scheduled jobs and their
  last runs. Numbers already come from facts.json.
- **Nightly truth check.** Runs every check. A claim that no longer holds marks its section **untrue** on the dashboard
  (Portfolio tab), triggers a redraft of that section (layer 3), and is never left silently on the page.
- **New copy can't add an unchecked claim.** A drafted section is checked for sentences that state a fact without a
  ledger entry; those are listed for Gil to either back with a check or cut.

| Section | Updates itself today | Checked as true today |
|---|---|---|
| Map | yes (nightly + on change) | yes (built from the system) |
| Numbers strip | yes (facts.json) | yes (counted from the system) |
| Hero + card images | regenerated on demand | yes (a picture of the real map) |
| Lead, story sections | no (#269) | no (layer 4) |
| What it can do (use cases) | not built yet (#268) | layer 4 |

## Decisions (Gil, 2026-10-08)

1. **Facts and use-case cards publish themselves like the map** (ADR 0057 extended). Story text still waits for Gil.
2. **MARVIN drafts every use case** in one pass, in Gil's voice; Gil reviews them as one list and edits what's off.

## Done today, on dev only

- Hero and card now come from one picture of the current map (`render_map_images.py`).
- The old static map in "32 skills, loaded on demand" is gone; the section points at the live map.
- No full-screen link: clicking the map's empty background opens it full screen (PR #265).
