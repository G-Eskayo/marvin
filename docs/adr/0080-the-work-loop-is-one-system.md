# 0080 — The work loop is one system: its rules are invariants, enforced where every path passes

## Status

Proposed (2026-10-28, marvin#737). Waiting on the owner's Decisions on the PR that adds this file.

## Context

MARVIN's work loop runs from an idea to code that ships: ticket, mock-up, owner's answer, build, review, merge, ship.
That loop has many surfaces: the hourly pipeline, the dashboard (MR Review, Approve, Decisions), MARVIN Mobile, and
interactive chats on either Mac. Each surface grew its own rules, and fixes went to the surface where a problem was
seen. The same problems kept coming back through the other surfaces. On 2026-10-28 alone:

- **Screenshots.** The pipeline and the dashboard's Approve required them; interactive chats went around both, so PRs
  reached the owner with no images, broken links or old pictures, over and over. #735 moved the rule into `bin/gh`,
  which every chat and agent write passes. But the dashboard merges through Homebrew's `gh` (its launchd PATH has no
  `~/.agents/bin`), with its own copy of the rule in `webhook-server/ui_evidence.js`, and PR #734 adds a third
  copy to the merge gate. Three copies of one rule drift apart.
- **Questions to the owner.** The dashboard only shows questions written in its format. Chats were told the format
  in their prompts. PRs clarity-captions #179 and #181 wrote a prose list anyway, so the owner was asked nothing.
- **Owner answers.** The dashboard recorded them. The scan that acts on them failed every run for six days (#724),
  and nothing noticed, because each part worked on its own and nothing checked that the loop finished.
- **Stale evidence.** clarity-captions #155 kept screenshots from before the commit that changed the screen.
- **Stuck PRs.** After a gate refusal, a pushed fix didn't bring Approve back (#678). A mock-up PR stops after its
  look is approved, because only a merge moves it on (#729).

A rule written in a prompt or a memory note is advice. A rule held by one surface is bypassed by the others.

## Decision

1. **The loop's goal is a short list of invariants**, written once, below. Each one names its single **choke point**:
   the place every path to that state goes through. Surfaces (dashboard, Mobile, pipeline, chats) display and act;
   they don't hold rules.
2. **One implementation per invariant.** Other code calls it; it never re-implements it.
3. **One end-to-end loop test** walks a fake ticket through every step in a sandbox (temp HOME, a fake GitHub) and
   fails if any surface or job drops it, including a job that silently fails (the #724 case).
4. **A recurring mistake is fixed only when it is one of these invariants, enforced at its choke point.** The memory
   note about the mistake links to the invariant that now prevents it. A memory note or a prompt line alone doesn't
   count as the fix for a second occurrence.

### The invariants

| ID | Always true | Choke point (the one implementation) |
|---|---|---|
| **I1 Current evidence** | A PR that changes how something looks shows images that load, pinned to a full commit SHA, newer than the last look change. | `lib/pr_images.py`, called by `bin/gh` (chats, agents, pipeline) **and** by the dashboard's merge server. `ui_evidence.js` and the merge-gate copy call it instead of repeating it. |
| **I2 Askable questions** | Every question to the owner is machine-readable: a body with a Decisions section carries the `<!-- marvin:decisions -->` block. | `bin/gh` refuses `pr create/edit` and `issue create/edit/comment` bodies that break it. |
| **I3 Answers are acted on** | Every owner answer (Decisions, Deny with reasons, a note) gets acted on in the same PR and replied to with `<!-- marvin:decisions-addressed -->`. A bare commit isn't a reply. Earlier unapproved rounds stay viewable as variations. | One trigger at the place answers are stored (the owner-decisions store), fired by the GitHub change watcher. The hourly scan is the backstop. |
| **I4 A next step, always** | Every open ticket and PR has exactly one **next owner** (MARVIN or the owner) and **next action**, all the way through merge and ship. Approving a look starts the build (#729), approving a PR queues the merge (#231), and a merge runs the project's ship step. | One function, `next_step(item)`, **derived** from GitHub and local state, never stored. The dashboard, Mobile, the pipeline and a `marvin next` command all read it. |
| **I5 Nothing stuck silently** | A step MARVIN owns that hasn't moved within its limit is re-dispatched. A step the owner owns gets one nudge with the exact question. A step nobody owns is a Health fault. A scheduled job failing run after run is a Health fault. | One liveness checker over `next_step` and the job logs, run on change events, with a timer only as a backstop. |
| **I6 One truth** | A decision that replaces an earlier one updates the repo and memory together (#652). A memory note about a recurring mistake links to the invariant that prevents it. | The memory-write path plus `memory_lint` (#695), which flags a recurring-lesson note with no invariant link. |

## Consequences

- Fixing a surface without its invariant is no longer "done". A ticket about a recurring problem names the
  invariant it touches.
- The dashboard merge server must reach the invariant code: either through `bin/gh` (its PATH changes), or by calling
  `lib/pr_images.py` directly. Either way, its own copy goes.
- The loop test is the definition of "the loop works". A new step or surface adds its case to it.
- The pieces already built or open become parts of this system, not separate fixes. Their places are in
  `docs/life-of-a-ticket.md`, section "The rules that always hold".
