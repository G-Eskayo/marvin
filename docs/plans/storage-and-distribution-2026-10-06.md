# Plan: storage, cleanup agents and resource distribution (2026-10-06)

Status (updated 2026-10-06 evening): **reclaim A1/A2/A4(brew)/B1/B3/B4(partial) done with Gil's approval, C2/C5/C6 built and live; mini 13 → 37 GiB free, laptop 94 → 136 GiB free.** Originally: measured, design proposed, nothing changed. Every reclaim step below waits for Gil's explicit go-ahead, item by item. Measurements were read-only (`du`, `git`, `gh`, `find -flags`) on both machines, 2026-10-06 ~15:00 MT. Source: the handoff `handoff-2026-10-06-14-30-storage.md`.

## 1. The headline

| | Mac mini (mac-mini-1) | MacBook Pro (macbook-pro-1) |
|---|---|---|
| Disk | 228 GiB | 460 GiB |
| Free | **13 GiB (94% full)** | 94 GiB (79% full) |
| Biggest MARVIN-owned item | pipeline worktrees, **39 GiB** | Hugging Face cache, 31 GiB |

The primary automation host is the machine that's nearly full, and the main cause is MARVIN's own ticket pipeline. The laptop's space is mostly personal app data plus one-off caches.

A full disk also causes failures elsewhere. On the mini, **15,933 of the 16,905 files in the portfolio repo (94%) are evicted to iCloud** ("dataless"), including 417 files inside its `.git`, and 117,678 files across `~/Documents`. macOS evicts aggressively when space is low. A background read of an evicted file then has to wait for a download, on top of the TCC block (memory: launchd-documents-tcc-block). The tidy-agent's `Resource deadlock avoided` errors on the mini are the same thing. Freeing space on the mini is the precondition for most of the other fixes.

## 2. What takes space

### Mac mini (187 GiB used)

| Size | What | Owner / purpose | Note |
|---:|---|---|---|
| 39.2 | `~/.agents-pipeline-worktrees` (33 worktrees) | ticket pipeline | see §3.1. 16 clarity-captions worktrees at ~2.1 GiB each, all of it `Packages/CaptionCore/.build` |
| 24.3 | `/Applications` | apps | |
| 21.2 | `/Library/Developer` | Xcode, iOS 26.5 simulator runtime (7.9) | needed for Clarity verification |
| 14.8 | `~/.ollama` | qwen2.5 14b (9.0), 7b (4.7), 3b (1.9), nomic-embed (0.3) | nomic-embed is used by MARVIN; which qwen models are used is to be checked |
| 8.9 | `/opt/homebrew` | tools | |
| 6.9 | Docker Desktop disk | 6 images, all in use (portfolio dev site, n8n) | |
| 6.7 | Claude desktop `vm_bundles` | Claude app | managed by the app |
| 6.3 | Messages, 5.6 wallpaper | personal / system | out of scope |
| 4.4 | `~/.cache/huggingface` | | to be identified |
| 3.2 | `~/.agents` (venv 1.9, dashboard 0.7, browser-profile 0.4) | MARVIN | |
| 3.0 | `/private/tmp/claude-501` | session scratchpads | cleared on reboot |
| 2.5 | `~/Developer` (clarity-captions 1.3, data 0.7, ML project 0.5) | | |
| 1.8 | `~/.agents-pipeline-cache` (Clarity DerivedData + Sortformer model) | pipeline | shared cache, working as designed |
| 1.6 | `~/Documents/old-mac-mini-backup-2026-07-10` | backup | |
| 1.5 | Homebrew download cache | | `brew cleanup` |
| 1.0 | `~/.Trash` | | |
| 0.9 | `~/portfolio-dev` | dev site backups | |

### MacBook Pro (341 GiB used)

| Size | What | Note |
|---:|---|---|
| ~115 | personal app data (Messages 52, Photos library + Pictures 43, Podcasts downloads 20) | out of scope for MARVIN. Podcasts downloads are the easy personal win if wanted |
| 31.4 | `~/.cache/huggingface`: FLUX.1-schnell | downloaded 2026-10-05 for the one-off Seal icon generation. Re-downloadable |
| 28.4 | `/Applications` | |
| 21.8 | `/Library/Developer`: 3 simulator runtimes (iOS 26.3, iOS 27.0, watchOS 27.0) = 18.9 | the mini only keeps one |
| 15 | `~/Library/Developer/CoreDevice` | physical-device support data (iPhone builds) |
| 13.4 | `~/Documents/Projects/Aero Heaven` | personal project, iCloud-synced |
| 11 | `~/.npm/_cacache` | npm download cache, rebuilt on demand (`npm cache clean`) |
| 9.3 | `~/Library/Developer/Xcode` (iOS DeviceSupport 6.5, DerivedData 2.8) | DeviceSupport for old iOS versions can go |
| 11.2 | `~/Library/Caches` (Google 3.4, Comet 1.7, …) | app-managed |
| 7.5 | Docker Desktop disk | |
| 2.5 / 2.2 | `~/.agents` / pipeline worktrees (11, all marvin) | |
| 1.3 | `~/.claude` (transcripts 1.2) | transcripts older than ~30 days are already pruned (only Sep and Oct exist). Self-limiting |
| 0.8 + 0.5 | `~/.Trash`, `~/.agents.pre-git-backup-20260709-1422` | |

**Duplicates on the laptop:** clarity-captions has two clones, `~/Developer/clarity-captions` (the working one) and `~/Documents/Projects/clarity-captions` (stale since 2026-10-03, in iCloud). `~/marvin.superseded-by-agents-20260709` is the old marvin checkout (4 dirty files). The 15 ingested repos (1.9 GiB, kept on purpose) live in iCloud-synced `~/Documents`, so the mini holds a partly evicted second copy.

## 3. Do the cleanup agents work?

| Agent | Scheduled? | Actually runs? | Does what it claims? |
|---|---|---|---|
| Pipeline worktree removal on resolution | n/a | **No.** `run_ticket.py` never removes a worktree after raising its PR. `cleanup_sweep`'s docstring says this is "immediate-on-resolution (ExitWorktree remove …)", but ExitWorktree is a Claude Code tool the pipeline doesn't use | **Broken.** Every ticket leaks one worktree permanently. The only removal is when the *same* ticket is re-dispatched |
| `cleanup_sweep.py` (safety net) | **No.** No launchd job, no cron entry, nothing imports it outside tests | Never. `~/.claude/logs/mr-pipeline-sweep.md` doesn't exist on either machine | **Also wrong if scheduled:** it is hardcoded to `G-Eskayo/marvin` and `~/.agents`. With clarity-captions and finance-os worktrees present, it would check their issue numbers against *marvin's* issues and run `git worktree remove` from the wrong repo |
| tidy-agent, laptop (`com.giles.tidy-agent`) | yes, 03:00 daily | **Failing every night since 2026-07-13.** `PermissionError: … ~/Desktop` | Fixed 2026-10-06: TCC checks the path `/usr/bin/python3` (the shim is the responsible process); FDA added for that path |
| tidy-agent, mini | yes | yes, exit 0 | files nothing: `filed=0` on 65 of 68 logged runs. 19 `Resource deadlock avoided` skips on iCloud-evicted Desktop files. It mostly fails silently |
| Health tab / cron-health | yes (mini) | yes | doesn't check any of the above: no disk-free check, no worktree count, no "last successful sweep" |
| Transcript pruning (Claude Code built-in) | n/a | yes | works: only the last ~30 days kept |

### 3.1 The pipeline worktrees in detail (mini)

PR state checked with `gh`, local state with `git status` / `rev-list`:

- **clarity-captions, 16 worktrees, ~33 GiB.** 14 have a **merged** PR and no uncommitted changes (#13 #21 #23 #25 #26 #27 #34 #35 #50 #51 #54 #55 #56 #58): **~29.6 GiB**. #37 (7 changed files) and #44 (1) have no PR and hold uncommitted work, so keep them until someone looks.
- **marvin, 14 worktrees, ~4.3 GiB.** Merged and clean: #141 #142 #144 #146 #155 #32 #35 #37 #41 (~2.8 GiB). PR still open: #143 #147. No PR: #148 (5 changed files: keep), #30, #38.
- **finance-os, 3 worktrees, 1.8 GiB.** Not ahead of main, no changes, no PR: empty attempts.

The laptop has 11 marvin worktrees (2.2 GiB), five of them still at the pre-rename `#` paths from August–September.

**Why a Clarity worktree is 2.1 GiB:** the required check `swift test` leaves its SwiftPM `.build` in the worktree. The Xcode step already builds into a `mktemp` dir and deletes it on exit; the SwiftPM step has no equivalent. Marvin worktrees carry a 0.3–0.5 GiB `dashboard/node_modules` each for the same reason.

## 4. Public repos on demand

Measured: every G-Eskayo repo is small on GitHub (the largest, marvin, is 15.8 MB). A full clone of marvin took 1.9 s (30 MB), clarity-captions 1.0 s (3 MB). Blobless (`--filter=blob:none`) was *slower* at these sizes (3.2 s / 1.3 s) and saved only 25%.

What this means:

- **Source code isn't where the space goes.** Build output is (`.build`, `node_modules`, DerivedData). Dropping local clones of public repos would save megabytes, not gigabytes.
- **Token cost: effectively zero either way.** The pipeline already gives every ticket a fresh worktree from `origin/main`, so the agent always reads a "cold" checkout. Prompt caching keys on content, not on where the files sit, and nothing in the executor relies on a warm checkout. The real cost of cold is *build time*: a fresh `.build` or `npm install` per ticket. That's handled better by a shared build cache (below) than by keeping the clones.
- **CI/CD effect:** `project_profile.find_clone` needs a base clone to make worktrees from. Keeping one base clone per active project per machine (`~/.agents-pipeline-clones/<repo>`, already the pattern for finance-os and killer-sudoku) costs a few MB each. That's the right shape. What should go is the *per-ticket* copies after resolution.
- **Where on-demand does pay off:** big third-party repos only. The ingested repos (1.9 GiB, two copies via iCloud) are kept for reference by Gil's decision. They could move out of iCloud to one machine, stay full clones there, and `pull_all.sh` keeps working. Their value is unchanged, the second copy and the eviction churn go away.

Recommendation: keep one warm base clone per *active* project (cheap, already the pattern), remove per-ticket worktrees on resolution, and share build caches across worktrees. Don't build an on-demand cloning system: the numbers don't justify it.

## 5. "RAID across machines"

Judged on quality and functionality for 2–3 Macs on Tailscale, one of them a laptop that sleeps and travels.

| Option | Verdict |
|---|---|
| Striping or parity across machines (RAID 0/5-style, e.g. a distributed filesystem) | **No.** Any striped file is unreadable whenever the laptop is asleep or away, which is most of the time. Fragile, complex, and capacity isn't the actual problem (the laptop has 94 GiB free) |
| Mirroring everything (RAID 1-style, e.g. Syncthing on all of `~`) | **No.** Doubles every cache and build artifact, and syncing live git directories is the same corruption risk iCloud already poses (§6) |
| **Placement by role plus replication of what can't be rebuilt** | **Yes.** Covered below |

The design that delivers the quality wanted:

1. **Classify data by whether it can be rebuilt**, not by machine:
   - *Rebuildable* (caches, build output, models, simulator runtimes, worktrees): kept only where it's used, never replicated, reclaimed by policy.
   - *Source of truth in git* (all code, MARVIN state in `~/.agents` / `~/.claude`): already replicated by GitHub plus code_sync and `~/.claude-sync.git`. Nothing new needed.
   - *Irreplaceable, not in git* (personal documents, photos, finance data, the portfolio's WordPress backups): replicated by iCloud / Time Machine. MARVIN doesn't touch these.
2. **Put work where it runs.** The mini runs the pipeline, the models and Docker, so it holds their caches. The laptop holds interactive work. Large but rarely used items (the FLUX model, old simulator runtimes, the ingested repos) live on whichever machine has room. Today that's the laptop.
3. **Grow storage, not complexity.** If the mini needs more room after the cleanup, a USB-C/Thunderbolt external SSD on the mini as a cache and archive tier (Ollama models, Docker data, pipeline cache, ingested repos) is the robust move: simple, fast, always attached. The planned third node would add capacity in the same placement-by-role way, not as part of an array.

## 6. Moving the portfolio repo out of `~/Documents`

Facts (2026-10-06):

- Both Macs show the identical repo state (HEAD `c7d2e59`, 24 commits ahead of `origin/main`, 60 uncommitted files). **iCloud is syncing the live `.git` directory between machines.** This is how in-progress work moves today, and it's also a corruption risk (two machines writing to one `.git` via a sync service). The clarity-captions notes already say "iCloud races git".
- On the mini, 94% of the repo's files are evicted, and launchd jobs can't read it (TCC).
- `wordpress/` (938 MB) and `backup/` (607 MB) make up almost all of its 1.5 GiB; `.git` is 4.4 MB. Whether those two directories are tracked or ignored has to be checked before the move.
- Hardcoded paths: 11 `lib/portfolio_*.py` / `project_catalog.py` modules, `dashboard/electron/main/portfolio.js`, `skills/improve/scripts/improvement_sweep.py`, the `portfolio-page` skill, `CONTEXT.md`, ADR 0050, ~9 test files, and 2 memory notes.

Proposed:

1. **Target path `~/Developer/portfolio-website-updater` on both Macs.** Matches clarity-captions, outside iCloud and TCC.
2. **One path constant.** Add `PORTFOLIO_REPO` to `project_catalog` (or the project's config JSON) and make every module, the Electron main process and the skill read it. The move then changes one value, and a test fails if a hardcoded path reappears.
3. **Sharing in-progress work without iCloud:** push to a non-deploying branch (`wip/<machine>`) on `origin`. Pushing `main` deploys, but a branch doesn't. If the repo is private and that's sufficient, no new transport is needed. If WIP must never reach GitHub, use the existing self-hosted bare-repo pattern (`~/.claude-sync.git` style) on the mini.
4. **Order:** commit the 60 uncommitted files (Gil reviews) → push the 24 commits to a WIP branch (not `main`) → fresh clone into `~/Developer` on each Mac → copy over untracked/ignored content (`wordpress/`, `backup/`) with `rsync --checksum` and compare → switch the path constant → verify the dev site, `portfolio_sync_dev.py` from launchd on the mini, and the dashboard Portfolio tab → only then, with approval, archive the old `~/Documents` copy (move to an archive, don't delete).

## 7. Design summary (proposed, to grill before building)

1. **Pipeline worktrees are released on resolution.** When a ticket's PR merges or closes, its worktree and branch are removed, after `_preserve_prior_attempt` has rescued anything unique (that primitive already exists).
2. **The sweep becomes the multi-repo safety net and actually runs.** Driven by the project catalog (each project's repo + base clone), it removes worktrees whose PR is merged/closed or that are empty and older than N days, and leaves dirty or no-PR worktrees alone but reports them. Daily launchd job on both machines, logged.
3. **Shared build caches.** SwiftPM scratch path in `~/.agents-pipeline-cache/<project>/swiftpm` (`swift test --scratch-path`, or delete `.build` after verify). `node_modules` either symlinked from the base clone when the lockfile matches, or removed after verify.
4. **A storage health check.** Health tab: free space per machine (warn below 20%, alert below 10%), worktree count and size, last successful sweep and tidy run (a non-zero exit or 7 days of `filed=0` is a failure, not a pass). **Implemented:** disk ledger (`lib/disk_ledger.py`, appends daily per machine), auto-trim when free% < 20% (`lib/disk_trim.py`), and headroom forecast in days using linear regression of 14-day trend (`lib/health_checks.py` disk:headroom check). See ADR 0056.
5. **Placement by role** (§5). No striping, no blanket mirroring.
6. **Portfolio repo moved** (§6), behind a single path constant.

## 8. Task list

Each "reclaim" task is a proposal. It runs only after Gil approves that specific item.

**A. Immediate reclaim on the mini (approval needed per item)**
- [x] A1. (done 2026-10-06: 14 removed, 29.9 GiB, branches kept) Remove the 14 merged, clean clarity-captions worktrees + branches (~29.6 GiB). Run `_preserve_prior_attempt` first anyway.
- [x] A2. (done: 9 marvin + 3 finance-os, 4.6 GiB; the sweep later removed the empty marvin#38) Remove the 9 merged, clean marvin worktrees (~2.8 GiB) and the 3 empty finance-os worktrees (1.8 GiB).
- [ ] A3. Review the dirty / no-PR worktrees (clarity #37 #44, marvin #148 #30 #38) with Gil: rescue to a branch or drop.
- [~] A4. `brew cleanup` done on both (2.4 GiB). Trash not touched.
- [ ] A5. Check which qwen2.5 Ollama models are used. Unused ones can be re-pulled later (up to 14 GiB).

**B. Immediate reclaim on the laptop (approval needed per item)**
- [x] B1. (done: FLUX removed, 31 GiB; icon art + source are committed in clarity-captions) FLUX.1-schnell Hugging Face cache (31 GiB, re-downloadable). Or keep it here as the "large rarely used" tier, Gil's call.
- [ ] B2. Old simulator runtime iOS 26.3, plus iOS DeviceSupport for iOS versions no device runs any more (up to ~13 GiB).
- [x] B3. (done: 11 GiB) `npm cache clean --force` (11 GiB, rebuilds on demand).
- [~] B4. (#32, #35 removed, 1.1 GiB; the other 7 hold work and are listed by the sweep) Stale marvin worktrees (2.2 GiB, same merged/clean check as A1).
- [ ] B5. Duplicates: `~/Documents/Projects/clarity-captions`, `~/marvin.superseded-by-agents-20260709`, `~/.agents.pre-git-backup-20260709-1422`. Archive or delete, Gil's call.

**C. Fix the cleanup agents (TDD, each its own ticket)**
- [x] C1. (superseded 2026-10-06: the daily C2 sweep removes a worktree within a day of its PR merging or closing, and C3 drops its build output as soon as the run ends, so a per-PR hook adds little) `run_ticket` / PR-resolution hook releases the worktree once the PR is merged or closed (rescue first).
- [x] C2. (done: commit 0ea5fcd, job installed and run on both machines) `cleanup_sweep` made multi-repo via the project catalog, with the current wrong-repo hazard covered by a test, then scheduled daily on both machines.
- [x] C3. (done 2026-10-06: chose removal after the run over a shared SwiftPM scratch path, which parallel dispatch would contend on. `run_ticket` calls `cleanup_sweep.drop_build_output` when a run ends, pass or fail; each profile lists `build_output`, marvin defaults to `dashboard/node_modules`. Only git-ignored dirs inside the worktree are removed; an untracked symlink to a shared cache is unlinked, never followed. Existing worktrees are untouched) Clarity profile: SwiftPM scratch path in the shared cache, or `.build` removed after verify. Same decision for marvin's `dashboard/node_modules`.
- [x] C4. (done 2026-10-06: TCC checks the path `/usr/bin/python3`, not `com.apple.python3`; Gil added that path, laptop run exit 0, filed=38, undo script `~/.claude/organize/undo-20261006-214858.sh`. Visibility: health-check now reads every com.marvin.*/com.giles.* job's launchd last exit code on every machine over ssh (`jobs:exit@<device>`, red when an idle job last exited non-zero)) Laptop tidy-agent: grant FDA to the Python it actually runs, or pin the plist to an interpreter that already has it. Then make a failed run visible.
- [x] C5. (done: tidy_agent.materialize downloads evicted files before moving) Mini tidy-agent: handle dataless files (skip with a single summary line, or `brctl download` first), and treat a long `filed=0` streak as a signal.
- [x] C6. (done: disk:space per machine in the Health tab; extended with disk:headroom forecast and auto-trim via ADR 0056) Health tab storage check (§7.4).

**D. Portfolio repo move (§6)**
- [ ] D1. Gil reviews and commits the 60 uncommitted files. Push the 24 commits to a WIP branch.
- [ ] D2. Single `PORTFOLIO_REPO` path constant + test that no hardcoded path remains (TDD).
- [ ] D3. Clone into `~/Developer` on both Macs, copy untracked content with checksum verification.
- [ ] D4. Switch the constant, verify dev site, launchd sync on the mini, dashboard tab. Update the skill and memory.
- [ ] D5. Archive the old `~/Documents` copy (after approval).

**E. Placement (after A–D, only if still needed)**
- [ ] E1. Move the ingested repos out of iCloud to one machine.
- [ ] E2. Decide on an external SSD for the mini as the cache/archive tier.

## Open questions for Gil

1. Approve A1–A2 now (~34 GiB on the mini, merged and clean only)?
2. Keep FLUX and the ingested repos on the laptop as the "rarely used" tier, or remove FLUX?
3. Portfolio WIP sharing: a WIP branch on GitHub (private repo) or the self-hosted bare repo on the mini?
4. Is an external SSD for the mini on the table?
