# Merge system, next generation (design, 2026-10-21)

**Status:** design for Gil's approval. Gil approved the direction on 2026-10-21 and authorized this design. **No code
until Gil approves it.** ADR draft: `docs/adr/0070-test-exactly-what-lands.md` (amends ADR 0061).

**Read first:** `docs/north-stars.md`, `CONTEXT.md` "Triggers over polling" (and the polling guard, #556), ADRs 0032,
0046, 0052, 0061, 0064, 0069, and the measured pipeline review in draft PR #572 (`docs/plans/pipeline-review-2026-10-21.md`
on `docs/pipeline-review`, cited below as **R-F#** for findings and **R-P#** for proposals).

**The one-paragraph answer.** Today, Approve tests one thing and lands another. The gate rebases the PR branch, tests
it, force-pushes it, then asks GitHub to merge it onto whatever main is by then. It skips the test entirely when the
files don't overlap, so #557 and #559 slipped past each other. The queue lives in memory, so restarting the merge
server (which every dashboard rebuild does) drops in-flight merges, as happened to #559 today. The design replaces
that with one idea: **a test result belongs to a tree.** MARVIN builds the exact tree a merge would produce (main + PR
+ version bump), tests it in the background at low priority while the PR waits for review, and records the verdict
against that tree's git hash. Approve adds the PR to a queue saved on disk. The merge owner lands the PR by pushing
that exact tested commit to main with a plain push, which git refuses if main has moved. If git refuses, the owner
re-tests that PR. Main can't go red from a merge, Approve takes seconds when the verdict is already there, and a
restart can't lose a merge, because every step can be safely repeated. Most of the change is deletion: the overlap
heuristic, the rebase-and-force-push gate, the GitHub mergeability retry loop, the separate version-bump commit, the
second rebuild trigger, `kickstart -k`, the in-memory promise queue, and most main-health runs.

---

## 0. Vocabulary

| Term | Meaning |
|---|---|
| **Candidate** | For PR *p* with head *H* and base main at *M*: the merge commit *C* that would land, with parents (*M*, *H*) and tree *T* = merge(*M*, *H*) + version bump. Built locally with `git merge-tree --write-tree` and `git commit-tree`, with no checkout and nothing pushed. |
| **Verdict** | The test result for a tree: `{tree T, suite fingerprint, pass/fail, failing tests, wall s, cpu s, machine, at}`. Keyed by `(T, fingerprint)`. Git tree hashes are content addresses, so the same tree gives the same verdict no matter how it was produced. |
| **Suite fingerprint** | A hash of what the tests run with but the tree doesn't contain: the venv's resolved package list, node version, and the project's test command. A change invalidates all verdicts. |
| **Queue** | Per repo, the append-only journal of Approve requests and their outcomes, saved on disk. |
| **Merge owner** | The one process allowed to land merges for a repo. It's the merge service on the repo's owner machine (marvin: the M4, ADR 0032) that holds the owner lock. |
| **Red episode** | The span from the first red main tree to the next green one. One notification per episode. |

---

## 1. Today's evidence (what the design has to fix)

| Problem | Evidence | Source |
|---|---|---|
| Merges are lost on restart | #559 merged 19:26:32 UTC, the server restarted 19:26–19:33, the card stuck on "Merging…", and Gil merged #561, #567 and #562 on GitHub instead. The webhook restarted 20 times, 9 of the last 12 within about 4 min of a dashboard merge. 6 of 26 merges since 10-14 were done on GitHub. | R-F2 |
| Two rebuild triggers | `merge.js` `triggerRebuildIfDashboardChanged` and `rebuild_check.js` → `dashboard_rebuild.py` both start `rebuild_and_install.sh`, which always ends with `launchctl kickstart -k …dashboard-webhook`. `dashboard_rebuild.py`'s `APP_SOURCE_PATHS` already excludes `webhook-server/`, yet the script restarts the server for every app change and never for a server-only change. | R-F2, code |
| Approve tests one thing and lands another | `rebaseAndRetest` rebases and force-pushes the PR branch (`merge.js:212`), then `gh pr merge --merge` merges onto main as of *that moment*. The `mergeableNow` loop works around GitHub recomputing after our own push. | code |
| The overlap heuristic misses cross-file breaks | #557 (merged 16:11) added code that #559's repo-wide polling guard rejects. No file overlapped, so there was no retest. Main went red after #559 landed. | R-F12, brief |
| Red main is half-enforced | ADR 0061 says "merges are refused while main is red". No code does that for human Approves. Main was red at e5f8122 while #569 merged. | R-F11 |
| The gate is slow and imprecise | 20 gate runs since 10-10: 6 passed (median 198 s), 7 `GATE_INFRA` cut at 1201–1217 s (a per-command kill, likely a hang), 5 `MAIN_RED`. | R-F3 |
| Approve is slow even with no gate | 23.7 s end to end for #569: a 10.4 s client re-list, 5.5 s of 8 serial `gh` reads, 3.1 s merge, 3.8 s version bump. | R-F4 |
| Main moves for non-merges | 47 % of main's commits are auto-sync, 95 % of them one metrics file. Each re-runs main-health (433 s, an estimated 3.6–4.7 h of M4 CPU a day). Every merge adds a second commit ("Version 0.12.2", ee133ca). | R-F1, git |

Load: about 4 merges a day; 6 open PRs (1 draft) at the time of writing. M4: Apple M4, 10 cores (4 performance),
16 GB. MacBook: Apple M1, 8 cores, 16 GB, a laptop that sleeps. Both are on Tailscale.

---

## 2. GitHub's own merge queue: evaluated first

**Verdict: not available for this repo, and it wouldn't be sufficient if it were. Build our own, but only the small
core GitHub would have given us, and reuse git itself as the lock.**

- **Availability.** The GA changelog (2023-07-12) says: "Merge queue is available on private and public repos on the
  GitHub Enterprise Cloud plan and all public repos owned by organizations." `G-Eskayo/marvin` is public and
  **owned by a user** (`gh api repos/G-Eskayo/marvin` → `owner.type: "User"`). This wasn't probed empirically, because
  that would mean editing the live ruleset.
- **What it would take.** Transfer the repo to a free organization. That means rewriting 691 references to
  `G-Eskayo/marvin` in 177 files and re-pointing remotes on three machines and the phone backend. GitHub redirects
  old URLs, but our code compares repo names as strings. The ruleset bypass for code-sync would also need redoing.
- **Fit, even after a transfer:**
  - Checks must report on `merge_group`. Our Python suite can't run on GitHub-hosted runners (CI comment: torch and
    chromadb, plus machine state), so we'd need **self-hosted runners** on the Macs: a GitHub-controlled daemon on
    our machines, which goes against self-reliance.
  - It tests **after** enqueue, never while a PR waits for review, so Approve stays minutes long. That fails part 1.
  - During a GitHub outage nothing is tested or merged. Approve can't even be recorded.
  - Red main: a failing group is ejected, with no "wait for main, let the fix jump" behavior.
  - No after-merge steps per project.
  - Cost: $0 for a public repo in an organization, plus the runners' maintenance and the transfer.
- **What we take from it.** Its core idea, testing the combined tree and merging only that, is exactly part 2. Its
  other idea, batching several PRs in one test, is worthless at about 4 merges a day.

---

## 3. The design, part by part

Each part gives what it reuses, what it deletes, the mechanism, its state and time cost, its failure cases and its
north-star fit.

### Part 1. Pre-verified PRs

**Mechanism.**
1. **Triggers, never a timer:**
   - (a) A PR's head changes. `gh_watch` already detects PR updates and pings with topics.
   - (b) Main moves. The same detector fires for marvin, and the owner fetches and compares `origin/main` with the
     *M* it last verified against.
   - (c) An Approve arrives.
   - (d) The service starts. Start-up is an event: one reconcile pass.
   - (e) The suite fingerprint changes. This is checked when the service starts and after an after-merge step updates
     the venv or node modules.
2. On a trigger, recompute the candidate tree for each **reviewable** PR: open, not draft, not sent back, CI not red,
   Decisions answered or not required, and UI evidence present when needed (`decisions_gate.js`, `ui_evidence.js`, run
   as pure checks over one PR snapshot, R-P5). Computing a candidate is a `git merge-tree` of seconds, with no
   checkout. A PR whose merge conflicts is marked *conflicts* and not tested (as ADR 0061 does today).
3. If a verdict already exists for `(T, fingerprint)`, stop. Otherwise put the candidate in the **verify queue**.
4. **Priority:** the approved PR at the head of the merge queue first, then other approved PRs, then reviewable PRs,
   oldest review request first. One verification runs at a time per owner. With xdist the suite already fills the
   cores, so a second one only competes.
5. **Low priority without our own idle detection:** speculative runs start under `taskpolicy -b` (macOS background
   QoS: efficiency cores, throttled disk). The kernel sheds them when Gil or a pipeline build needs the machine, which
   is the Apollo lesson applied by the OS. A run is promoted to normal QoS (`taskpolicy -B` on the process group) once
   its PR is approved and at the head of the queue.
6. **Coalescing:** if main moves while a candidate is being verified, that run is **cancelled** (its tree can no longer
   land) and the PR's new candidate takes its place. At most one run per PR, and only for the latest main.
7. The run happens in a **reused scratch worktree per slot** (`git checkout --detach C && git clean -fdx`, except
   cached `node_modules`, which are reinstalled only when the lockfile hash changes). Disk stays constant, which
   matters because the M4 has 19 GiB free (R-F14).
8. The verdict is written to the verdict store, and the PR card shows "Pre-verified ✓ against main @abc123" or the
   failing tests (pushed through #569's event stream, topic `merge`).

**What counts as "affected".** A candidate's tree depends on main, so with exact trees every reviewable PR is
affected by every main move. There's no honest shortcut, and reintroducing one is how #557 and #559 slipped through.
The cost is bounded instead by four things:
- After R-P1 (metrics off main), main moves only for merges and real code edits: an **estimated** 5–8 times a day
  instead of about 50.
- Only *reviewable* PRs are tested (drafts, sent-back, conflicting and red-CI PRs aren't).
- Coalescing never tests a stale main.
- The verdict cache keys on the tree, so a PR re-tested against an unchanged tree costs nothing.

**State and time.**
- Verdict store: one small JSON line per verdict, keyed by `(T, fingerprint)`, capped at the last 2,000 (LRU), about
  1 MB. Space O(1) with that cap.
- Per-PR candidate record: O(R) for R reviewable PRs.
- Work per main move: O(R) merge-trees (each O(changed paths)) plus up to R suite runs, run one at a time and cancelled
  when stale. Estimate: R ≈ 4, suite ≈ 90–150 s with xdist (not yet measured), so ≈ 6–10 CPU-min per main move, at
  background QoS. **Estimate: 1–1.5 h/day of M4 CPU, against today's 3.6–4.7 h/day of main-health alone (R-F1).** The
  verdict store records CPU seconds, so this becomes a measurement, not an estimate.
- Work per PR push: one merge-tree plus at most one suite run.

**Failures.**
- *Restart or crash mid-run:* the run dies with its process group. On start, the reconcile pass sees no verdict for
  that tree and queues it again. Nothing is half-written: the verdict is appended only on completion, as one line
  under `O_APPEND`.
- *Duplicate triggers* (one merge is several GitHub events): the verdict and candidate keys make a second trigger a
  no-op. The merge-tree is recomputed (seconds), and the test is skipped on a cache hit.
- *GitHub outage:* candidates are built from the last fetched refs, so verification continues offline. Freshness is
  shown on the card ("against main as of 14:02").
- *A flaky test:* a failing verdict re-runs only the failing tests once. Both runs are recorded, and a test that passes
  on the re-run is reported as **flaky**, not as the PR's fault (Health lists flaky tests).
- *A hung test:* it depends on R-P3's per-test timeout (another agent's work). Without it, a hang burns the run's time
  cap and the verdict is `infra` (not the PR's fault), as today.

**North-star fit.**
- *Reuses* `gh_watch` triggers, `git merge-tree` (already in `conflictsWithBase`), the gate's test commands, #569's event
  stream and the existing pure checks.
- *Deletes* the main-health run after every merge (see part 5) and the gate's sequential re-reads.
- *Simplest sufficient:* a content-addressed cache is the underlying principle (Colton), so no "is this affected?"
  logic is needed.
- *Saves* M4 CPU (estimate above) and Gil's time: Approve becomes seconds.
- *Phone-OS:* the work happens proactively and the result is waiting when Gil looks.
- *Human experience:* Gil reviews code with its test result already on the card. That's more information, not less
  judgment.
- *Against:* it spends CPU on PRs Gil might never approve. Historically about 95 % are approved (ADR 0064 context: only
  5 pipeline PRs ever closed unmerged), so the speculation is almost always used.

### Part 2. Test exactly what will land, and land only what was tested

**Mechanism.**
1. At land time the owner holds the candidate *C* (parents *M*, *H*, tree *T*) whose verdict passed.
2. Two checks run first:
   - The PR's head is still the *H* that Gil approved (one `gh pr view`, folded into the single R-P5 snapshot).
   - CI on *H* is green.
3. **Land:** `git push origin C:refs/heads/main`, a plain push without `--force`.
   - The ruleset "main is PR-only (ADR 0069)" has a `non_fast_forward` rule, so GitHub accepts the push only if *C*
     is a descendant of current main, which means main is still *M*. **Git's ref update is the compare-and-swap.** No
     lock of our own can give that guarantee across machines, GitHub's UI and auto-sync, and this one comes free.
   - The Macs push as the repo admin, which the ruleset's bypass allows, the same way code-sync pushes today.
4. GitHub marks a PR **merged** when its head commit becomes reachable from the base branch, and *C* has *H* as a
   parent. *Phase 3 must prove this on a sandbox repo before relying on it* (see "Verified, not assumed").
5. **Rejected (main moved):** the PR keeps its place at the head of the queue. Its new candidate is built against the
   new main and verified at normal priority, then landing is tried again. A rejection costs one re-verification and
   never a broken main.
6. **The version bump goes in the candidate.** `bumpVersion` reads `VERSION` from *M*, and the bump type comes from
   the PR's labels, so the bumped `VERSION` and `CHANGELOG.md` lines are written into *T* before testing. The bump
   is tested, lands in the same commit, and main moves **once** per merge instead of twice. Today's second commit made
   every other PR's candidate stale for nothing.
7. The commit message keeps GitHub's form ("Merge pull request #N from owner/branch") plus a trailer
   `Verified-Tree: <T>` and `Verified-By: <machine>`, so anyone can check after the fact that main's tree is the one
   that was tested.

**Deleted.**
- `_defaultShouldGateMerge` (the overlap heuristic) and ADR 0061's at-Approve rule.
- `rebaseAndRetest`'s rebase and `--force-with-lease` push of the PR branch. We never rewrite a contributor's branch
  again.
- `mergeableNow` and its six-try retry loop (GitHub's mergeability no longer matters, because we push the merge
  ourselves).
- The separate version-bump commit.
- The `MAIN_RED` baseline re-run at Approve (part 5 replaces it with a verdict comparison).
- The client's `guardApprove` re-list of 13 repos (R-F4, 10.4 s); order is now the queue's job (part 4).

**Fallback if the push route is rejected** (Decisions: `landing`). Use `PUT /repos/{repo}/pulls/{n}/merge` with
`sha=H`, straight after confirming that `git ls-remote` still shows *M*, then compare the landed commit's tree with *T*.
A mismatch means main moved in that window of about a second, and the commit is flagged **landed untested** and verified
at once. This keeps every merge inside GitHub's PR flow, at the price of a small race that's detected rather than
prevented.

**State and time.**
- No new state beyond the candidate already held.
- Per land: one snapshot read, one push. That's O(1) GitHub calls, down from 8 reads + merge + bump push (R-F4).
- Push size: O(new objects), usually just the merge commit and the bump blobs.

**Failures.**
- *Crash between push and journal:* on restart the journal shows `landing` with no outcome. The owner checks whether
  *C* (or *H*) is reachable from `origin/main`. If yes, it records `landed`. If no, it retries. Pushing *C* twice is
  harmless: the second push is a no-op, or is rejected because main moved past *C*, which already contains it.
- *GitHub outage:* the push fails with a network error, the entry stays at the head as "waiting for GitHub", and the
  next successful `gh_watch` probe (the existing 20 s change detector, already allowlisted) triggers a retry. It isn't a
  new timer.
- *Another writer lands first* (a GitHub-UI merge, auto-sync, the MacBook): the push is rejected → re-verify → land.
  Correct by construction.
- *Network split* (owner can't reach GitHub but the MacBook can): the owner simply can't land. The MacBook can't land
  either without owning the queue (part 4). Even two owners at once (split brain) can't break main, because only one
  push per *M* succeeds and the loser re-verifies.
- *Head moved after Approve:* refused as `HEAD_CHANGED` and dropped from the queue, with "new commits since you
  approved". Gil approved specific code (Decisions: `head-moved`).

**North-star fit.**
- *Reuses* git's own atomic ref update and the existing ruleset. It deletes more than it adds: 5 mechanisms and about 1
  commit per merge.
- *Simplest sufficient:* the guarantee "main only ever holds tested trees" comes from one push flag, not from new code.
- *Reliability* (precondition of north star 2): nothing breaks silently, and `Verified-Tree` makes it auditable.
- *Saves* about 15 s per Approve of GitHub round trips, plus a whole main move per merge.
- *Against:* direct pushes to main use the admin bypass, which ADR 0069 keeps only for code-sync. This extends it to
  the merge owner. The ADR draft records that, and the fallback avoids it if Gil prefers.

### Part 3. A merge service with no downtime

**Measured constraint.** Node 24.9 on macOS refuses `listen({ reusePort: true })` with `ENOTSUP` (tested on the MacBook
on 2026-10-21; libuv supports it only on Linux and some BSDs). Two processes therefore **can't** share TCP port 7878
on macOS. A Unix socket could overlap by atomic rename, but the MacBook and the phone reach the M4 over TCP. So
"blue/green on the same port" is impossible as literally stated. The design gets the same guarantee, no lost merge and
no refused Approve, by separating **accepting** from **executing**:

1. **Accepting** is a durable append to the queue journal (part 4). It's tiny, so either instance can do it.
2. **Executing** needs the **owner lock**, an OS file lock (`flock`) on `merge/<repo>/owner.lock` held by the worker.
   The OS releases it when the process dies, so a crashed owner can never leave a stale lock.
3. **Handoff when the service's own code changes:**
   - The service knows its **code fingerprint**: the git tree hash of the paths it runs, kept in one list,
     `SERVICE_PATHS` (`dashboard/webhook-server/`, plus `dashboard/src/lib/merge_progress.js` which it imports, plus
     `package-lock.json`).
   - After-merge step `merge-service` (part 7) compares the checkout's fingerprint with the running one.
   - If they differ, the service enters **drain**: it keeps accepting Approves (appending to the journal), starts no
     new job, finishes the job in flight, releases the lock, closes the listener and exits 0.
   - launchd (`KeepAlive`) starts the new code in about 1 s. It takes the lock, folds the journal and carries on.
4. **The ≈1 s gap** when nothing listens is absorbed by the clients:
   - The dashboard main process and the mobile backend retry `ECONNREFUSED` up to 3 times over ≈5 s. That's a bounded
     retry for one request, not polling.
   - If all retries fail, the client keeps the Approve in its local pending list and resends it on the next event from
     the owner (its refresh ping on start-up). The enqueue key (repo, PR, head) makes the resend idempotent.
   - The card shows "Approved — waiting for the merge Mac" at once (the local-first principle, R-P4).
5. **The app rebuild never restarts the service.** Delete the `launchctl kickstart -k` block from
   `rebuild_and_install.sh`. The only things that restart the service are a change to its own code (step 3), a crash
   (launchd), or a boot.
6. **Drain is capped** at the job's own time limit. Since every step can be safely repeated (part 2's land check,
   part 1's verdict keys), even a hard kill loses nothing: the next instance resumes the journal's open entry. Drain is
   courtesy, and the journal is the guarantee.

`merge-inflight.json` (from #569) is absorbed: the journal *is* the in-flight record. "Interrupted" becomes
"resumed".

**State and time.**
- Lock: O(1).
- Handoff: O(remaining time of the in-flight job), at most the cap. Typically 0, since most of the time nothing is in
  flight.
- Start-up fold: O(journal lines), bounded by compaction (part 4).

**Failures.**
- *Crash:* the lock is released by the OS, launchd restarts the service, and it resumes the open entry.
- *Restart storm* (bad new code crashes on start): launchd throttles to one restart per 10 s. Approves are still
  appended by the clients' pending lists. Health's `webhook:build` check alerts. Fixing that check's false "not
  running" (R-F14) is a precondition.
- *Two instances alive* (a manual start during a drain): only the lock holder executes. The other accepts or fails to
  bind, and either is safe.
- *Code changes mid-job:* the running process loaded its modules at start, and jobs run in scratch worktrees, not the
  live checkout. The fingerprint check happens only between jobs.

**North-star fit.**
- *Reuses* launchd `KeepAlive`, OS file locks and the existing fingerprint idea from `dashboard_rebuild.py`'s path
  list.
- *Deletes* `kickstart -k`, the second restart path and `merge-inflight.json`.
- *Simplest sufficient:* separating accept from execute removes the need for two live servers.
- *Phone-OS:* the service is always reachable, and a restart is invisible.
- *Grounded:* we say plainly that literal blue/green on one port isn't possible on macOS. This design meets the
  requirement behind it (never lose or refuse a merge) with less machinery.

### Part 4. One queue, one merge owner per repo (absorbs #231)

**Mechanism.**
- **Journal**, per repo: `merge/<repo>/queue.jsonl`, append-only. Events:
  - `enqueued{id, pr, head, by, device, at}`
  - `verifying{id, tree}`
  - `blocked{id, reason}`
  - `landing{id, commit}`
  - `landed{id, commit, at}`
  - `refused{id, code, remediation}`
  - `cancelled{id, by}`
- `id = sha256(repo, pr, head)`. A second Approve of the same head is a no-op that returns the existing position, so
  Approves from the phone and the MacBook at once give one entry.
- **Owner per repo** is set in the project profile (`merge_owner: "mac-mini-1"`, defaulting to the M4 per ADR 0032).
  Approve from any device posts to the owner's `/approve`. The owner is the only writer of its repo's journal, so the
  file has a single writer.
- **The worker** is one event-driven loop per repo, no `setInterval`. It wakes on: enqueue, verdict written, main moved,
  `gh_watch` probe after a GitHub error, and start-up. It takes the first entry that isn't blocked and is either
  (a) green-verified for current main → land (part 2), or (b) not yet verified → promote its verification.
- **Order:** first come, first served, except that stacked PRs (base = another PR's branch) wait for their parent. The
  ordering lives in the queue, and the old "Merge #208 first" refusal goes away.
- **Progress** streams to every dashboard and the phone through #569's events (`queued` with position, `verifying` with
  the live test count, `landing`, `landed`, `refused`), plus a `blocked` stage for part 5. The reducer in
  `src/lib/merge_progress.js` is reused, with new stages added.
- **Cancel:** a "Remove from queue" action appends `cancelled`. Cancelling an entry that's already landing is refused
  with "already landing", because the push can't be recalled.
- **Compaction:** when an entry reaches a terminal event it's folded into `merge-history.jsonl` (existing file and
  format). The live journal is rewritten (atomic temp file and rename) when it passes 500 lines. Space is O(live
  queue) plus the history tail.

**#231 acceptance criteria, mapped.** Approving three PRs merges all three in order without more clicks (yes). A
failure records its reason and the queue moves on (yes: `refused` plus `failure.js`). Each queued PR shows its position
and step (yes). The queue survives a restart (yes: the journal). Desktop and mobile share one queue (yes: the owner's
journal). #231 is closed as superseded by this design's phase 2, and its stale `claimed:mac-mini` label released
(R-F6).

**State and time.**
- Enqueue: O(1) (one append and fsync).
- Fold on start: O(lines ≤ 500).
- Worker step: O(1) plus the land or verify work.

**Failures.**
- *Duplicate events and double clicks:* idempotent `id`.
- *Owner offline or network split:* clients hold the Approve in their local pending list, the card says "waiting for
  the merge Mac", and the client resends on reconnect.
- *No automatic failover* (Decisions: `owner-failover`). Split brain can't break main (part 2), but it would duplicate
  work and confuse the journal. A manual switch is one profile field. The new owner fetches the journal from the old
  owner over Tailscale `ssh`, or starts empty and Gil re-approves.
- *Journal corruption* (a torn last line after power loss): the fold ignores a line that doesn't parse, logs it to
  Health, and every complete event before it stands.

**North-star fit.**
- *Reuses* `merge-history.jsonl`, #569's stream and reducer, `failure.js` refusals and the device identity.
- *Deletes* the in-memory `inRepoQueue` promise chain, `queueDepth`, `merge-inflight.json` and the client's order guard.
- *Phone-OS:* Approve from anywhere, one truth.
- *Self-reliance:* the queue is a file MARVIN owns, readable with `cat`. Nothing depends on GitHub to record intent.

### Part 5. A red main queues instead of blocking (amends ADR 0061)

**Mechanism.**
- **Main's state is a verdict lookup.** If main's tree has a verdict, that's main's color. Merges through the queue
  always have one (part 2), so the main-health full-suite run after a queued merge becomes a cache hit and is deleted.
- Main-health keeps one job: verifying **trees nobody verified**. Those come from auto-sync code commits, merges on
  GitHub's site, or a changed suite fingerprint. It runs through the same verify queue at normal priority, which
  replaces `main_health.py`'s own runner (and with it the single-flight and timeout problems, R-F11).
- **When main is red:**
  - Approve still enqueues, and the card says "Waiting: main is red (2 failing tests from abc123)".
  - Each queued candidate is still verified. A candidate is **blocked by main** if its failing tests are a subset of
    main's (it can't be judged yet, and it isn't sent back). It's the **PR's fault** if it fails tests that pass on
    main (sent back, as `GATE_TESTS_FAILED` today).
  - **A candidate that passes completely lands**, even ahead of earlier entries. Passing on top of a red main means it
    fixes main. That is the "fix jumps the queue" rule, and it needs no special case: the worker lands the first entry
    with a green verdict.
  - Once main is green, blocked candidates are re-verified (main moved) and land in order.
- **Exactly one notification per red episode:**
  - When main's verdict turns red and no episode is open, open one (`merge/<repo>/red.json`: first red tree, commit
    range since the last green, failing tests) and send **one** push.
  - The push names what broke it. If one commit separates the last green tree from the first red one, name it (the PR
    number and title, or "auto-sync from mac-mini: 2 files"). If several do, the push lists them, and the verifier
    bisects the range at background priority (O(log k) suite runs for k commits) and updates the dashboard. There's no
    second push.
  - The flaky re-run (part 1) runs before an episode opens, so one flake never wakes Gil.
  - The episode closes when main is green again, shown in the dashboard, with no push by default (Decisions:
    `green-ping`).
  - Only the merge owner sends, so two Macs can't double-notify.
- **Delivery path, self-reliant:** ADR 0046's mobile backend → APNs, marked urgent (bypasses quiet hours: a red main
  blocks merges). Fallback is the existing desktop notification (`notify.py`, osascript). **Not** the
  `claude -p PushNotification` path in `mr_notification.py`, which depends on the Claude subscription.
- **Auto-merge (ADR 0064)** stays consistent: an auto-merge is a queue entry with `by: auto`. "A red main pauses all
  auto-merging" becomes "auto entries never jump the queue on a red main; only a human-approved fix does" (Decisions:
  `auto-fix-jump`).

**State and time.**
- Episode record: O(1) per repo.
- Notification: O(1) per episode.
- Naming the culprit: O(1) when the range has one commit, otherwise O(log k) background runs.
- Blocked entries: O(queue), re-verified once per main move.

**Failures.**
- *Duplicate red verdicts* (two triggers): the episode is already open, so no push.
- *Restart mid-episode:* `red.json` persists, so no re-notify.
- *Flapping (red, green, red within minutes):* a new episode opens only if the previous one closed more than 10 min ago.
  Otherwise the old one reopens without a push. Gil heard about it once.
- *Mobile backend down:* desktop fallback. The episode records which channel delivered.
- *Red caused by the environment* (suite fingerprint changed, for example a package upgrade): the push says "tests
  changed environment" rather than blaming a commit.

**North-star fit.**
- *Deletes* main-health's per-merge suite runs (most of R-F1's estimated 3.6–4.7 h/day), `baselineFailsOnMain` at
  Approve and a "refuse while red" rule that never existed in code.
- *Simplest sufficient:* "land the first green candidate" gives the fix-jumps rule for free.
- *Human experience:* one precise ping instead of silence or a flood, and Gil keeps control because Approve always
  works.
- *Self-reliance:* the push moves to MARVIN's own path.

### Part 6. Both Macs share test work: measure before building

**Recommendation: don't build sharding unless the measurement below says so.** Expected outcome (an estimate, to be
measured): not worth it.

- **Why it's doubtful:**
  - Parallel pytest-xdist (being added by another agent) uses all 10 M4 cores. The serial suite is 433 s, so an
    **estimated** 70–150 s with xdist, depending on which tests share state.
  - Sharding adds fixed costs per shard: moving the candidate to the MacBook (`git fetch` over Tailscale `ssh` from the
    M4, with no GitHub involved), a worktree, `node_modules` if the lockfile changed, and venv drift checks.
  - The MacBook is Gil's laptop: on battery, often in use, and asleep when the lid is shut.
  - Pre-verification (part 1) already moves the suite off the Approve path, so wall time matters much less.
- **Measurement (phase 6, XS):**
  1. After xdist lands, record the suite's wall and CPU time per verification in the verdict store (free with part 1).
  2. Time the shard overhead once, by hand: fetch + worktree + install on the MacBook for a typical candidate.
  3. **Build only if** p50 xdist wall time is over 120 s for candidates **on the Approve path** (verifications that
     weren't already done when Gil clicked), **and** the measured overhead is under 25 % of the time saved.
- **If built:**
  - Shards are split by recorded per-test durations (longest first, O(n log n)).
  - The MacBook takes a shard only if it's on AC power and the user has been idle for at least 5 min, read at dispatch
    time.
  - A shard that doesn't report within 2× its expected time is re-run on the M4. A verdict never depends on the
    MacBook being awake.

**State and time.** Per-test duration table O(tests) ≈ 2,600 rows. The split is O(n log n). Transfer is O(new
objects).

**Failures.** *MacBook sleeps or the network splits mid-shard:* timeout, then rerun locally. The verdict is correct and
only slower. *Duplicate shard results:* keyed by `(tree, shard index)`.

**North-star fit.**
- North star 1 argues *against* building this before measuring: two machines, a transfer protocol and a stragglers
  policy, for a wall-time gain that pre-verification already hides.
- The design keeps the option cheap: the verdict store already records the timings needed to decide.

### Part 7. After-merge steps per project, each triggered once

**Mechanism.**
- **One trigger:** each machine's service sees "main moved for repo X" (the `gh_watch` change detector + fetch, which
  runs on every Mac) and runs that project's **after-merge steps** as declared in its profile:

  ```json
  "after_merge": [
    { "step": "dashboard-app",  "paths": ["dashboard/src", "dashboard/electron", "..."], "run": "lib/dashboard_rebuild.py", "machines": ["mac-mini-1", "macbook-pro-1"], "when": "idle" },
    { "step": "merge-service",  "paths": "SERVICE_PATHS", "run": "drain-and-restart", "machines": ["mac-mini-1"] }
  ]
  ```

  Other projects declare their own steps (clarity-captions: none today; a portfolio deploy step later), or none.
- **Once per change, by key:** a step's key is `(machine, step, git tree hash of its paths at new main)`. The ledger
  `merge/after-merge.json` keeps the last key that ran successfully per (machine, step). A repeated event, a second
  trigger, or a main move that didn't touch the step's paths gives the same key, so nothing runs. Matching paths by
  tree hash is exact, not a heuristic.
- **"When idle", for the app on a Mac Gil is using:**
  - Build in the background at once at background QoS. Building doesn't interrupt anything.
  - **Install and relaunch** only when the user is idle (HID idle at least 5 min, read when the trigger fires).
  - If Gil isn't idle, the dashboard shows an "Update ready, restart now" chip, and the install runs on the click, on
    the next idle trigger, or at the code-sync cycle (an existing backstop, not a new timer) (Decisions:
    `app-update-busy`).
- **Deleted:**
  - `merge.js` `triggerRebuildIfDashboardChanged` (the duplicate trigger; `rebuild_check.js` already covers every merge
    path, #443).
  - `kickstart -k` in `rebuild_and_install.sh`.
  - The DMG and zip targets (`electron-builder --mac dir`; the MacBook built 18 DMGs for 19 installs, R-F2).
  - The post-merge `rebaseOpen` call from inside the merge job. Conflict checks move into part 1's candidate pass,
    which computes the same merge-tree anyway.

**State and time.**
- Ledger: O(machines × steps), latest key only.
- Per main move: O(steps) tree-hash lookups (milliseconds) plus the steps that actually changed.

**Failures.**
- *A step fails:* its key isn't recorded, so it retries on the next main move. The existing `dashboard-rebuild-failed`
  back-off stays (retry when newer code lands).
- *Machine asleep during the merge:* on wake, code-sync pulls (an existing trigger), the key differs and the step runs
  once.
- *Duplicate events:* same key, so nothing runs.
- *Network split:* each Mac acts on what it fetched, and catches up on reconnect.

**North-star fit.**
- *Deletes* a duplicate module and a restart path.
- *Reuses* `dashboard_rebuild.py`'s `decide` and `rebuild_check.js`.
- *General:* every project gets after-merge steps from one mechanism, which serves north star 4 (tools for making
  tools).
- *Human experience:* the app never yanks itself out from under Gil mid-task.

---

## 4. Where state lives (self-reliance)

All new state goes in a MARVIN-owned directory, never in `~/.claude`, and works with no Claude subscription
(Decisions: `state-home`; recommended `~/.marvin/`):

```
~/.marvin/merge/<owner>__<repo>/queue.jsonl    journal (part 4)
~/.marvin/merge/<owner>__<repo>/owner.lock     flock (part 3)
~/.marvin/merge/<owner>__<repo>/red.json       red episode (part 5)
~/.marvin/merge/verdicts.jsonl                 verdict store, LRU 2,000 (part 1)
~/.marvin/merge/after-merge.json               after-merge ledger (part 7)
```

Existing files the merge path writes under `~/.claude/logs` (`merge-history.jsonl`, `gate-run-durations.jsonl`) move
in the same phase that touches them. Tests point `MARVIN_HOME` at a temp dir (R-P9's rule, enforced).

## 5. Robustness matrix

| Case | Part 1 pre-verify | Part 2 land | Part 3 service | Part 4 queue | Part 5 red main | Part 7 after-merge |
|---|---|---|---|---|---|---|
| **Restart** (new code) | run cancelled, re-queued on start | journal `landing` → reachability check → record or retry | drain, then ≈1 s gap absorbed by client retry | journal folded on start | `red.json` persists, no re-ping | ledger keys persist |
| **Crash** | same as restart | same | OS frees lock, launchd restarts | torn last line ignored and logged | same | step re-runs (key not recorded) |
| **Network split between Macs** | owner verifies alone | owner lands alone; the MacBook can't, by design | n/a | clients keep pending Approves and resend | only the owner pings | each Mac acts on its own fetch |
| **GitHub outage** | continues on last fetched refs | push fails, entry waits, `gh_watch` probe triggers retry | n/a | Approve still recorded locally | verdicts continue | steps run on local fetch when it resumes |
| **Duplicate events** | verdict key → no-op | push of an already-landed *C* is a no-op | lock → one worker | idempotent `id` | open episode → no ping | ledger key → no-op |
| **Another writer moves main** | coalesce: cancel stale run | push rejected → re-verify | n/a | entry keeps its place | unverified tree verified at normal priority | step runs once for the new key |

## 6. Phases (smallest valuable slice first)

Sizes: XS < 1 h, S ≈ half a day, M ≈ 1–2 days. Each phase is tests-first (`tdd`, ADR 0063: tests try to break it) and
goes through the gate like any PR. **Prerequisites owned by other agents or PRs:** R-P1 (metrics off main), R-P3
(per-test timeout), xdist, #457 (main-health single-flight). The phases below don't block on them, but phase 2's CPU
numbers depend on R-P1.

| Phase | What | Size | Acceptance test (adversarial) | Measure |
|---|---|---|---|---|
| **1. Can't lose a merge** | Journal + owner lock + resume on start (part 4 core, part 3). Delete `kickstart -k` from `rebuild_and_install.sh`. Self-drain on own code change. Delete `triggerRebuildIfDashboardChanged` (one rebuild path). Client retry + local pending Approve. `merge-inflight.json` absorbed. Merges still land as today. | **M** | (a) `kill -9` the service at each stage of a merge (fetching, tests, after `gh pr merge` returns, before the journal write): the next instance finishes or records it, and the PR is merged exactly once. (b) A dashboard-only merge rebuilds the app on both Macs and doesn't restart the service (its pid is unchanged). (c) A webhook-server change triggers drain: an Approve sent during the drain is accepted and lands after the restart. (d) Three Approves of the same PR from two devices at once give one entry. (e) A journal with a torn last line loads. | Lost merges (≥ 1 on 10-21, plus 6 of 26 done on GitHub) → **0**. Service restarts not caused by its own code → 0. "Interrupted" events → 0. |
| **2. Pre-verify in the background** | Candidate builder (merge-tree + bump in tree), verdict store, verify queue with `taskpolicy -b` and promotion, coalescing, triggers (head change, main move, start, fingerprint). At Approve, a matching green verdict skips the gate (fast path); otherwise today's gate runs. Card shows "Pre-verified". | **M** | (a) Main moves during a run: the run is cancelled within 5 s and the new candidate queued. (b) Two triggers for the same tree run one suite. (c) A flaky test (passes on re-run) is reported flaky, not failed. (d) With a CPU hog running at normal priority, the speculative run's share drops (it's shed) and Gil's interactive latency doesn't regress. (e) Suite fingerprint change invalidates verdicts. | Share of Approves with a ready verdict (target ≥ 80 %). Approve→merged p50 for those (23.7 s → ≤ 10 s). Verification CPU-s/day from the verdict store vs main-health's estimated 3.6–4.7 h. |
| **3. Land exactly what was tested** | Sandbox proof first: a throwaway public repo with the same ruleset checks that a plain push of *C* is accepted only while main is *M*, and that GitHub marks the PR merged. Then CAS landing, `Verified-Tree` trailer, the bump inside the candidate, `HEAD_CHANGED` refusal. Delete the overlap heuristic, rebase + force-push, `mergeableNow`, the separate bump commit and the client's order re-list. ADR 0070 accepted. | **M** | (a) Main is moved by another writer between verify and push: the push is rejected, the PR is re-verified and lands, and main's tree always equals a green verdict. (b) Replay #557 + #559 on a fixture repo: #559's candidate fails on top of #557 and never lands. (c) The PR head changes after Approve: refused `HEAD_CHANGED`. (d) Crash after the push, before the journal write: recorded `landed`, with no second merge commit. (e) GitHub unreachable at push: the entry waits and lands when the probe succeeds. | Red-main incidents caused by a merge → **0** (audit: every main commit since the phase has a `Verified-Tree` matching a green verdict, or is flagged unverified). Commits per merge: 2 → 1. GitHub calls per Approve: about 10 → ≤ 3. |
| **4. Red main queues** | Blocked-by-main classification, first-green-lands, episode file, one push via the mobile backend (ADR 0046) with desktop fallback, bisect for multi-commit ranges. Main-health reduced to verifying unverified trees through the verify queue. ADR 0064 auto-merge wording updated. | **S** | (a) Main is red because of commit X, and 3 PRs are queued, one of which fixes X: the fix lands first and the other two land after, in order. (b) Ten red verdicts in a row send exactly 1 push. (c) Red, green, red within 10 min: still 1 push. (d) A restart mid-episode sends no push. (e) A flaky single failure sends no push. (f) Mobile backend down: the desktop fallback fires once. | Pushes per red episode = 1. Time from red to Gil knowing ≤ 1 verification. Main-health suite runs/day (estimated 30–39 → only unverified trees, expected ≤ 5). |
| **5. After-merge steps per project** | `after_merge` in profiles, ledger by tree key, idle install with an "Update ready" chip, DMG/zip removed, conflict check folded into the candidate pass. | **S** | (a) Five events for one merge run each step once per machine. (b) A merge touching only `docs/` runs no step. (c) MacBook asleep through a merge: one run on wake. (d) Gil active in the app: the build happens, the install waits, and the chip appears. (e) A failed step retries on the next main move and never loops. | Rebuilds per dashboard merge per Mac = 1 (today: up to 2 + a restart). DMG builds → 0. M4 CPU-minutes in rebuilds per day. |
| **6. Measure sharding** | Read xdist wall/CPU times from the verdict store, and time the MacBook shard overhead once. Write the result into this doc. Build (an M) only if the rule in part 6 passes. | **XS** (+M if built) | n/a for measuring. If built: the MacBook sleeps mid-shard and the verdict still arrives, from the M4. | Off-path verification p50 wall time; overhead ratio. |

**Running totals to watch, once per phase in the PR body and on Health:** Approve→merged p50/p90 (journal timestamps),
lost merges (journal entries `enqueued` that are never terminal, plus merges done on GitHub while the queue was
non-empty), red-main incidents split into *from merges* (target 0) and *from unverified writers*, and M4 CPU-hours a
day spent on verification (verdict store `cpu s`).

## 7. What gets deleted (deletion test)

| Removed | Why nothing is lost |
|---|---|
| `_defaultShouldGateMerge` overlap heuristic | Every candidate is tested exactly. The heuristic's job (skip unnecessary tests) is done by the tree cache. |
| `rebaseAndRetest` rebase + force-push of the PR branch | We test and push the merge commit. The PR branch is never rewritten. |
| `mergeableNow` retry loop | GitHub's mergeability isn't consulted. The push itself is the test. |
| Separate version-bump commit | The bump is inside the tested candidate. |
| `baselineFailsOnMain` at Approve | Replaced by comparing verdicts: candidate failures vs main's. |
| Client `guardApprove` re-list of 13 repos | Ordering is the queue's job, on the owner. |
| In-memory `inRepoQueue` / `queueDepth` | The journal plus one worker loop. |
| `merge-inflight.json` | The journal is the in-flight record. |
| `triggerRebuildIfDashboardChanged` | `rebuild_check.js` + after-merge ledger covers every merge path. |
| `kickstart -k` in `rebuild_and_install.sh` | The service restarts only for its own code, by draining. |
| DMG/zip build targets | Nothing installs them. |
| Main-health full run after every merge | Main's tree already has a verdict. |
| `main_health.py`'s own runner and lock | Verification of unverified trees goes through the one verify queue. |

## 8. North-star fit, overall

- **Minimise resources (1):**
  - One main move per merge instead of two.
  - About 15 s less GitHub I/O per Approve.
  - Main-health's per-merge runs gone.
  - Speculative work at background QoS, which the kernel sheds.
  - It spends CPU on speculation, but about 95 % of it is used. Net M4 CPU is expected to fall (estimate; measured
    from phase 2).
- **Phone-OS (2):** reliable (nothing lost or silent), reachable from any device, proactive (results waiting), and
  partly offline (Approve and verification survive a GitHub outage).
- **Raises the human (3):** Gil keeps the judgment (Approve, and Decisions below) and gets better information (test
  result on the card, one precise red ping). Nothing that was Gil's to decide is automated away.
- **Tools for making tools (4):** after-merge steps and the exact-tree gate serve every project, not just MARVIN.
- **Watts / Colton:**
  - The underlying principle is that a test result is a function of a tree. Everything else (cache, fix-jumps, main
    color, step dedup) follows from keying on tree hashes.
  - GitHub's merge queue is the surface. Git's own compare-and-swap ref update is the principle beneath it.
- **Against:** direct pushes to main extend the admin bypass beyond code-sync. Recorded in ADR 0070, with a fallback.

## 9. Open decisions

See the PR's **Decisions** section (the source of truth for Gil's answers): `state-home`, `landing`,
`speculative-scope`, `head-moved`, `owner-failover`, `green-ping`, `auto-fix-jump`, `app-update-busy`, `sharding`.

## 10. Evidence sources

- Draft PR #572 (`docs/plans/pipeline-review-2026-10-21.md`): R-F1–F14 and R-P1–P10.
- `merge-history.jsonl` on the M4 (26 lines; 10-21: #559 19:26, #569 20:24, #574 21:36).
- `gh api repos/G-Eskayo/marvin` (owner type User, public); ruleset 25272465 (`non_fast_forward`, `pull_request`,
  admin-role bypass).
- `git log origin/main` (ee133ca "Version 0.12.2" after df17433 "Merge #569").
- Code read on origin/main 7a7560b: `merge.js` (`inRepoQueue`, `rebaseAndRetest` force-push at line 212,
  `mergePrUnqueued`, `triggerRebuildIfDashboardChanged`), `index.js` (`/approve`, inflight),
  `rebuild_check.js`, `lib/dashboard_rebuild.py` (`APP_SOURCE_PATHS`), `rebuild_and_install.sh` (`kickstart -k`),
  `changelog.js`, `lib/main_health.py`, `lib/mr_notification.py`, CONTEXT.md "Triggers over polling".
- Node `reusePort` probe on the MacBook (Node 24.9, macOS): `ENOTSUP`.
- GitHub merge queue GA changelog, 2023-07-12; GitHub Docs "Managing a merge queue" (`merge_group` requirement).
- CPU: `sysctl` on both Macs (M4 10 cores, M1 8 cores, 16 GB each).
