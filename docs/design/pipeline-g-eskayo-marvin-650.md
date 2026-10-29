## North-star fit

**Reuses before adding anything new:**
- `lib/project_profile.py` (`PROFILES_DIR`, verify tiers, `EnvMissing`, `env.DEVELOPER_DIR.first_existing`) — the existing per-project build/verify/dispatch mechanism (#613-adjacent, decided 2026-10-05) is exactly the thing a "build against a new Xcode/SDK" job needs to call, for *any* project that has a profile, not just clarity-captions.
- `config/playbooks/ios-app.md` / `ios-app.json` (#613, built) — the stage/owner-gate/machine shape this ticket's "generalises to any app project" line is asking for already exists; the maintainer agent should add a trigger *into* this playbook's existing `build`→`app-build` stages, not invent a second build path.
- `skills/research-colony/scripts/source_monitor.py` (`fetch_arxiv`/`fetch_github`/`fetch_hackernews`) — the fetch‑normalize‑fail‑soft shape for pulling an external release feed.
- `dashboard/webhook-server/gh_watch.js`'s conditional-GET change-detector + CONTEXT.md's "Triggers over polling" (line 704) — Apple has no webhook, so the closest thing to a real trigger is this repo's own established pattern: a cheap conditional request against the one place state actually changes, not a full poll.
- `lib/seal_beta_ingest.py` (dedupe-by-known-id, private local store never a repo, loud failure on permission/IO problems, `feature_enabled()` gate) — directly reusable shape for "have we already filed a ticket for this release."
- `lib/task_dispatch.py` — machine selection / busy-state, to stop two machines double-triggering the same build.
- `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`, `docs/agents/decisions-format.md` — ticket filing/labeling conventions for the slices this ticket must produce.
- `docs/adr/0071-public-engine-private-instance.md` + `lib/instance.py::instance_dir()` + `lib/deliverable_location_guard.py` — **where the doc goes**, corrected below.

**Simplest sufficient approach:** no new runner, no new ticket-filing mechanism, no new build system — a small fetch/diff script feeding the *existing* profile+playbook dispatch path, plus ordinary `gh issue create` calls. Matches the ticket's own framing (north star 4: generalise via the playbook/profile layer MARVIN already has, don't build a one-off Seal-only watcher).

**Tokens/cost:** the watcher's steady-state cost is one cheap conditional request on a slow cadence (near-zero, 304-shaped, same as `gh_watch.js`); real cost (a full build+test cycle) is paid only when Apple actually ships something, which is rare — cost scales with real external events, not with polling frequency.

**More capable, not more passive:** replaces a chore nobody was doing (memory: `project-ios-update-maintainer-agent` — "nobody was tracking beta cadence proactively," which already caused one real timeline surprise) with an early-warning signal; it still stops for Gil at the playbook's existing owner gates (anything sent to Apple, signing, etc.) and only *reports*, it doesn't ship anything itself.

**Correcting the ticket's own stated acceptance criterion:** "A design doc in `docs/plans/`" is stale. ADR 0071 step 2 (commit `fee623d3`, 2026-10-25, same day this ticket's milestone was planned) moved `docs/plans/` into the **private instance repo**; it is now gitignored in this engine repo and `config/push-guard/paths.txt` (`^docs/plans/`) actively refuses any commit that touches it here. Precedent (`1127587d`, "move the pipeline review doc out of the engine") confirms this applies even to engine-feature design docs, not just owner-personal ones. `lib/instance.py::instance_dir()` resolves to `~/.agents/instance` — **outside this ticket's git worktree entirely**, a sibling location shared across all worktrees, with its own separate git history/remote. This worktree has no `instance/` checkout (correctly gitignored). I believe this exact mismatch is why the two prior automated attempts never reached a passing comparison: writing the doc inside this worktree's `docs/plans/` is either silently gitignored or refused by the push guard, so no verification path that expects "the acceptance criterion satisfied inside this PR's diff" can ever pass. The real fix: write the doc directly to `~/.agents/instance/docs/plans/ios-update-maintainer-2026-10-27.md` and commit+push it to the private instance repo *separately* from this ticket's engine-repo PR (exactly as `deliverable_location_guard.py`'s own reason text and the `1127587d`/`project-playbooks-2026-10-22.md` precedent describe). The engine-repo PR for ticket #650 itself should carry no `docs/plans/` content — only the ticket pipeline's own standard planning artifact (`docs/design/pipeline-g-eskayo-marvin-650.md`), which is a different, already-correct mechanism (ADR 0029).

## Tests (none in the ticket's own "How we'll try to break it" — it has no such section; the ticket is doc-first, acceptance criteria are a doc + filed tickets, not code. These are the mechanical/misuse checks that stand in for it, to be written before any content, and to be copied into the filed slice tickets' own acceptance criteria since the executable code lands with those, not with this doc-only ticket)

1. **Doc lands in the right repo, not the wrong one**: assert the design doc is written under `~/.agents/instance/docs/plans/` and that `git status` inside *this* engine worktree shows no `docs/plans/` entry at all (regression test for the exact failure mode diagnosed above).
2. **Doc shape**: assert required sections exist (Why / Decided-so-far / North-star fit / space-and-time cost / Stages or trigger table / Known traps), mirroring `project-playbooks-2026-10-22.md`'s own structure — a doc missing one of these is "not actually doc-first," not just incomplete.
3. **Bad/malformed input**: Apple's feed/HTML changes shape or returns non-UTF-8/garbage — fetch must fail soft (log + no-op), never crash the launchd job, matching `source_monitor.py`'s `except Exception: ... return []`.
4. **Empty input**: no new release found — no-op, no ticket filed, no false "all clear" ticket either.
5. **Huge/flood input**: several betas land in one check window (or the feed replays old entries) — only the genuinely newest unseen release triggers a build; no N duplicate build runs for one polling cycle.
6. **Each dependency failing**: feed endpoint unreachable; Xcode/beta download fails; the target project's own build fails for a reason unrelated to the OS bump (e.g. a pre-existing flaky test) — each must fail loud and distinguishably (reuse `EnvMissing`/`MeasureError`'s is-this-an-environment-problem-or-a-real-failure split from `project_profile.py`), never silently swallowed (the bare-except pattern the roadmap already flagged as systemic).
7. **Repeats/idempotency**: the same release is detected twice (a beta promoted straight to the GA build, or a restarted job re-reads its own state file) — never files a second ticket for a release already handled; reuse `seal_beta_ingest.py`'s dedupe-by-known-id shape.
8. **Concurrency**: Mini and MacBook both run the watcher's poll in the same window — only one actually dispatches the build (`task_dispatch.py` busy-state), the other no-ops.
9. **Wrong permissions/machine**: the beta Xcode isn't installed/selected on the machine that happens to pick up the dispatch — this is an `EnvMissing`-shaped environment gap, not a ticket defect (must not feed the failure breaker or count as a Seal regression).
10. **Stale/corrupt state**: the "last-seen release" bookmark file is missing or unparsable — must recover as "nothing seen yet," not crash, and must not mass re-file tickets for every release in the feed's current window.
11. **A person's mistakes**: Gil closes a filed compatibility ticket without a real fix; the next poll still sees the same broken release — must not refile the same release endlessly (one ticket per release key, reopened rather than duplicated, matching the existing ticket-key conventions already used elsewhere in the repo).
12. **Outward-facing / adversarial**: the fetched release-notes text is untrusted external content used to build a ticket title/body and to keyword-match "Speech"/audio-framework mentions — must never be interpolated into a shell command (reuse `--body-file`, not a heredoc/`-c` string, per the `gh-body-file-not-heredoc-substitution` memory) and must not let the feed's content path-traverse the local bookmark/cache file it's stored under.

## Decisions

<!-- marvin:decisions -->
### trigger-source: Which Apple signal counts as "a new release", given there's no real webhook?
- [ ] A: Apple Developer News RSS/Atom feed, conditional-GET on a slow cadence (matches existing `gh_watch.js` pattern) — covers both betas and GA announcements in prose, needs text parsing to extract version/platform
- [ ] B: `xcodebuild -downloadPlatform`/`softwareupdate --list-full-installers` style local check for newly available Xcode/SDK versions — structured, but only sees what's downloadable on the machine, not Apple's announcement text (so it can't catch "Speech framework changed" from release notes)
- [ ] C: Both — the feed drives the "flag release notes even if the build passes" requirement, the local check drives "a new Xcode/SDK is actually buildable now"

### beta-machine: Which machine installs/runs a beta Xcode against clarity-captions?
- [ ] A: MacBook (per the ticket's own text) — keeps the Mini's stable Xcode untouched for all other production pipeline work
- [ ] B: Mini, parametrized via a second `DEVELOPER_DIR` candidate (`env.DEVELOPER_DIR.first_existing` already supports a list) — simpler, but risks a broken/incompatible beta Xcode affecting the Mini's normal dispatch if `xcode-select` state leaks
- [ ] C: Neither pipeline Mac — a separate, disposable VM/clone just for beta verification (most isolated, most new infrastructure)

### beta-severity: What happens when a **beta** (not GA) build breaks?
- [ ] A: File a ticket immediately, same as GA — betas are often where real incompatibilities first show up
- [ ] B: Log/flag only (Health card or a digest line), file a real ticket only once the same break persists into GA or a later beta — betas churn and break for unrelated reasons often

### ticket-home: Where do the generated compatibility tickets, and this ticket's own slices, get filed?
- [ ] A: In the target project's own repo (e.g. `G-Eskayo/clarity-captions`), since that's the code that needs fixing — matches "which project a ticket belongs to" (ADR 0060)
- [ ] B: In `G-Eskayo/marvin` with the target project's `project:<id>` label, since the *maintainer agent itself* is marvin infra (matches how #613's playbook tickets were filed)
<!-- marvin:decisions -->

## Task List

1. Draft the design doc content: Why (cites the real 2026-09-08 timeline-surprise motivation already in memory), the trigger mechanism and its space/time cost, which machine builds what, how it generalises through `config/playbooks/*` + `config/projects/*.json` rather than being clarity-captions-specific, a stages/owner-gates table in the existing playbook-doc shape, and the Decisions block above.
2. Write that doc to `~/.agents/instance/docs/plans/ios-update-maintainer-2026-10-27.md` and commit+push it directly to the private instance repo (outside this engine worktree's branch, per ADR 0071) — not into this worktree's `docs/plans/`.
3. Verify placement: confirm `git status` in this engine worktree shows no `docs/plans/` file, and that the instance-repo commit actually landed (test 1/2 above).
4. From the doc, derive concrete slices (mirroring #613's "slice 1/2/3" breakdown) — e.g.: (a) the release-feed/local-check watcher + its idempotent state store, (b) the project-profile/playbook extension to dispatch a build against a new Xcode/SDK on the chosen machine, (c) release-notes keyword flagging (Speech/audio) even on a passing build, (d) wiring into the other `ios-app`/`macos`-playbook projects (marvin-mobile, nourished, killer-sudoku) so the mechanism isn't Seal-only.
5. File each slice as a GitHub issue per `docs/agents/issue-tracker.md`/`triage-labels.md` conventions, labeled per the `ticket-home` decision above, each referencing the instance-repo design doc path and carrying the relevant subset of the misuse-test list (6–12 above) as its own acceptance criteria.
6. Confirm this ticket's own engine-repo PR carries only the standard per-ticket planning artifact (`docs/design/pipeline-g-eskayo-marvin-650.md`/`-tasks.md`, ADR 0029) and no `docs/plans/` content, then close #650 once the instance-repo doc is pushed and the slice tickets exist.