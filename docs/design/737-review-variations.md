# MR Review: feedback lands on the same PR right away, and unapproved looks stay as variations (marvin#737)

Status: **proposed**, waiting on the owner's Decisions in the draft PR. Nothing here is built.

Owner, 2026-10-28: "build up the MR reviews to have it update the MRs with feedback and show archived variations if
it isn't approved."

## What happens today

| Owner action | What reacts | When | Where the work lands |
|---|---|---|---|
| Submit decisions (dashboard) | `owner_decisions.py` in the hourly scan files "Act on owner decisions on PR #N" | after 4 h grace, next hourly scan (and the scan has failed since 2026-10-22, PR #724) | the follow-up is a normal ticket: the executor builds `pipeline/<ref>` **from main**, so it tends to open a new PR, not update #N |
| Deny with reasons | ticket gets `needs-reengagement`; refeed / sent-back loop | next hourly scan | `pipeline/<ref>` rebuilt **from main** and force-pushed with a lease; the old round survives only under `refs/rescue/` |
| Note on github.com | nothing until the hourly scan sees a Decisions comment (a plain note is not one) | | |

So feedback waits hours, often lands in a different PR, and a denied round's commits are replaced.

## 1. Feedback reaches the same PR right away (no second loop)

Reuse three things that exist:

1. **The trigger.** The dashboard already starts a scan on demand: `dispatch_concurrency.js` `scanNow()` runs
   `launchctl kickstart com.marvin.ticket-pipeline`, and `run_ticket.py` uses `redispatch_trigger.request_scan()`
   (debounced). `decisions_submit.js` and the Deny path (`mr_actions.js`) call that same kick right after GitHub accepts
   the write. No timer, no watcher.
2. **The follow-up ticket** from `owner_decisions.py`. When the scan was started by an owner action it files the
   follow-up with **no grace** for that PR; the 4 h grace stays only for answers it finds on its own (written on
   github.com, or a kick that was lost), so the hourly scan remains the fallback clock it already is.
   Deny with reasons files the same follow-up kind (marker `kind=deny`) instead of only labelling the ticket, so both
   paths run one agent prompt.
3. **The executor, pointed at the PR's branch.** A follow-up whose marker names `pr=N` is dispatched onto PR #N's
   head branch (a worktree of that branch, not `pipeline/<ref>` from main). It commits on top, pushes without force,
   runs `pr-shots` (#735) to retake and re-pin images, replies with `<!-- marvin:decisions-addressed -->` (#733), and
   ends with a fresh Decisions section (#729's "never silence"). One PR, one thread.

Fails safe: if the branch moved (someone pushed), the push is refused and the agent rebases on the new head; if the PR
closed, the follow-up closes itself (already in `owner_decisions.sync`).

Cost: one extra `launchctl kickstart` per owner action, and the scan's existing single GraphQL search (2 points).
Time O(P x C) as today; no new state on disk.

## 2. Every unapproved round is kept as a variation

A **round** is one `pr-shots` run on a PR: a commit SHA plus the images pinned to it. v1 is the first, each re-pin is
the next. The current round is the PR body's `<!-- marvin:shots -->` section (already the source of truth).

**Where the list lives (recommended): a comment per round, derived, not stored.** When `pr-shots` replaces the shots
section it first posts the outgoing round as a comment:

```
<!-- marvin:variation pr=171 v=2 sha=7be0d13… -->
### v2 (not approved)
![Caption language](https://raw.githubusercontent.com/…/7be0d13…/docs/images/pr/…/list.png)
…
```

MR Review lists earlier versions from those comments (one conditional comments read when a PR's detail opens, ETag
pattern from `gh_watch.js`; the MR list itself makes no extra call) and pairs each with the owner's Decisions/Deny record that followed it, which is the "your note on v2" line. GitHub is the
record, both Macs agree, append-only, and the body stays short.

**Keeping old commits alive.** A SHA-pinned image only loads while its commit is reachable. A squash merge, a deleted
branch, or the sent-back loop's force-push leaves round commits unreachable, and GitHub may drop them. `pr-shots`
therefore pushes `refs/marvin/variations/pr-<N>/v<k>` for each round (same pattern as `refs/rescue/`, but always pushed,
not best-effort). Engine images already go to the instance repo, so marvin PRs need only the ref there.

**"Go back to vN"** is an owner answer like any other: it posts a Decisions record (`variation=vN`) and kicks the scan;
the agent restores the look files from `refs/marvin/variations/pr-N/vN` on top of the branch (a new commit, never a
reset), so going back is itself a new round (v4 = v2's look). "Mix v1's header with v3" is a note on the same answer.

## 3. The mock-up

`docs/design/737-review-variations-mockup.html`, captured at 1280 px and 820 px, dark and light. Additions to the PR
detail, nothing else moves:

- a **round line** under the title: "v3 · current. Your answers from 09:12 are in. Applied on this PR at 09:31,
  screenshots retaken", with the SHA and a link to the reply;
- the images heading names the round ("v3, current");
- **Earlier versions (N)**: newest first, collapsed to one row each (version, "not approved", date, SHA, two
  thumbnails, the owner's note on it, "Go back to vN"). Expanded, each screen shows that version next to the current one.

The dashboard has no light theme today (`darkMode: 'class'`, no `dark:` classes). The light capture shows the palette
the section would use if one is added; it is not a request to add one.

## Overlap with open work (checked 2026-10-28)

- PR #724 and PR #734 both edit `lib/owner_decisions.py`; PR #734 also edits `mr_review.js` and `prState.js`.
- PR #736 adds `pr-shots` (`lib/pr_shots.py`), which section 2 extends.

Phase 2 waits for those to merge (or stacks on #736), and edits none of those files before then.
