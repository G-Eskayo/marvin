# Merge system, next generation (design, 2026-10-21) — WIP

**Status: WIP. Research notes only, design not written yet.** Gil approved the direction on 2026-10-21. This is
doc-first: no code until Gil approves the design.

## Research findings so far (verified 2026-10-21)

### GitHub's own merge queue
- Availability (GitHub changelog, 2023-07-12 GA): "Merge queue is available on private and public repos on the GitHub
  Enterprise Cloud plan and all public repos owned by organizations." `G-Eskayo/marvin` is a public repo owned by a
  **User** (`gh api repos/G-Eskayo/marvin` → owner.type "User"), so it can't use the merge queue as things stand.
- Getting it would mean moving the repo to a free organization: 691 references to `G-Eskayo/marvin` across 177 files,
  plus the ruleset and remotes. Its checks must report on `merge_group`. Our pytest suite can't run on GitHub-hosted
  runners (CI comment: torch/chromadb, machine state), so we'd need self-hosted runners on the Macs, which is a
  GitHub-dependent daemon. It tests only after enqueue, so it doesn't pre-verify while the PR waits for review, and
  Approve isn't seconds. During a GitHub outage, nothing merges. It has no after-merge steps and doesn't queue on a
  red main. Verdict so far: not available, and not sufficient even if it were.

### Landing exactly the tested tree
- `merge.js` lands with `gh pr merge --merge`, so GitHub builds its own merge against whatever main is at that moment,
  which isn't the tree that was tested.
- Ruleset "main is PR-only (ADR 0069)" has a `non_fast_forward` rule, with a bypass for the repo-admin role (the Macs
  push as the admin). A plain, non-force `git push <C>:refs/heads/main` of the tested merge commit C (parents M, H)
  succeeds only if main is still M. That gives an atomic compare-and-swap for free. GitHub marks a PR merged once its
  head is reachable from main. A sandbox repo has to prove this in phase 1.
- The version bump (`changelog.js` `applyVersionBump`: VERSION + CHANGELOG.md) is a **second** commit on main after
  each merge (for example ee133ca "Version 0.12.2"). Fold it into the candidate tree so the bump is tested and lands
  in one main move.

### Zero-downtime service
- Node 24.9 on macOS: `listen({ reusePort: true })` → **ENOTSUP** (tested on the MacBook). Both instances can't
  overlap on the same TCP port. Plan: a durable on-disk queue plus a lock that marks the merge owner. The old instance
  keeps accepting enqueues while it drains, then exits, and launchd restarts it in about 1 s. Clients retry
  connection-refused for a few seconds. As an alternative, an atomic rename lets two instances overlap on a Unix
  socket, but remote clients (MacBook, phone) use TCP 7878.
- `rebuild_and_install.sh` always runs `launchctl kickstart -k com.marvin.dashboard-webhook`, even though
  `dashboard_rebuild.py`'s `APP_SOURCE_PATHS` already excludes `webhook-server/`. A change to the webhook alone never
  restarts the server, and an app-only change always does. The restart should key on the server's own code tree hash.

### Machines
- M4 (mac-mini-1): 10 cores (4 P), 16 GB. MacBook (macbook-pro-1): Apple M1, 8 cores, 16 GB, a laptop that sleeps.
- For low priority, use macOS `taskpolicy -b` (background QoS: efficiency cores, throttled I/O), so the kernel sheds the
  work. We don't need our own idle detection. Raise the priority for the approved PR at the head of the queue.

### Phone notification
- `mr_notification.py` push goes through headless `claude -p`, which depends on Claude. ADR 0046 sets the self-reliant
  path: APNs through the mobile backend. Red-main notifications should go there.

### Evidence (PR #572 pipeline review)
- No-gate Approve took 23.7 s end to end (#569), and the gated pass median is 198 s. Gate since 10-10: 20 runs, 14 failed,
  7 cut at 1201–1217 s (per-command 20 min kill, likely a hang). The webhook restarted 20 times, 9 of the last 12 within
  about 4 minutes of a dashboard merge. #559's merge was lost to a restart. 6 of 26 merges were done on GitHub instead.
  About 4 merges a day, 26 dashboard merges logged. Main-health: 433 s per main move, an estimated 3.6–4.7 h of M4 CPU a
  day. 47 % of commits on main are auto-sync, 95 % of them one metrics file.

## Next steps
Write the design (parts 1–7 with north-star fit, state and time complexity, failure cases), phases with acceptance
tests and metrics, an ADR draft amending 0061, a draft PR with Decisions, and the HTML summary.
