# iOS/macOS Release Watcher: Automatic Compatibility Agent

## Status
Active planning — ready for slice-based implementation. Decisions section pending owner review.

## Why

**Timeline surprise, 2026-09-08:** During clarity-captions design work, the project owner discovered iOS's public release was weeks nearer than assumed ("a couple months away" → actually imminent), because nobody was tracking Apple's beta/release cadence proactively. A standing agent watching Apple's release cycle catches timeline surprises like this automatically, instead of discovery happening by chance in conversation.

**Concrete impact:** App Store deadline was 2026-10-25. Compatibility breaks on a new iOS GA release discovered *after* launch are high-risk (forces an emergency update, uses launch momentum for bug fixes instead of feature land). A running watch system flags breaks *before* launch, when there's still time to delay, notify customers, or iterate.

**Scope:** The mechanism generalizes to any iOS/macOS project in the portfolio (clarity-captions, marvin-mobile, nourished, killer-sudoku), not just the triggering app. Once built for the first project, adding the second is mechanical.

## Trigger Mechanism & Space/Time Cost

**Signal source:** Apple Developer News RSS feed (covers both beta announcements and GA releases in prose; includes release-notes text for keyword matching) via conditional GET.

**Polling cadence:** Once per day (same cost profile as existing `gh_watch.js` pattern). Steady-state cost is near-zero (304 Not Modified), paid only when Apple ships something — cost scales with real external events, not polling frequency.

**Failure mode:** Fetching fails (network down, feed endpoint unreachable, malformed response) → log + no-op, no crash. Never leave a stale state that makes the next run do the wrong thing.

**Idempotency:** A release ID (iOS version + build number) is tracked in a local state file (same shape as `lib/seal_beta_ingest.py`). Once seen, never files a duplicate ticket for the same release. If the state file is corrupt/missing, recover as "nothing seen yet" and fetch the feed; do not mass-refile old releases.

## Build Targets & Machine Selection

**Which machine:** Parametrized per the `beta-machine` decision (see Decisions section). Current working assumption: MacBook runs beta Xcode against the primary app (clarity-captions); stable Mini Xcode remains untouched for production dispatch.

**Which projects:** A project profile (`config/projects/<name>.json`) declares whether it watches for updates and which Xcode variant to use. Existing profiles (`project_profile.py`, built #613) already cover:
- Version tier (stable, beta, current)
- `DEVELOPER_DIR` alternatives
- `env.DEVELOPER_DIR.first_existing` for failover selection

No new project infrastructure needed; reuse the existing layer.

**Dispatch path:** When a new release is detected:
1. Playbook checks `config/playbooks/ios-app.json` for the project's build stages
2. Inserts a dispatch into the existing `build`→`app-build` stage (no new pipeline path)
3. Respects all existing owner gates (code signing, App Store submission decisions stay with the owner)
4. Records outcome in the filed ticket

## Reusable Patterns This Agent Leverages

- `lib/project_profile.py` — `EnvMissing`/`MeasureError` distinction for "environment problem vs. real failure"; per-project build verification
- `config/playbooks/ios-app.json` (built #613) — stages, owner gates, machine selection
- `skills/research-colony/scripts/source_monitor.py` — fetch/normalize/fail-soft shape for external feeds
- `dashboard/webhook-server/gh_watch.js` — conditional-GET change detection (no real Apple webhook exists)
- `lib/seal_beta_ingest.py` — dedupe-by-known-ID, local state file, loud failure on I/O
- `lib/task_dispatch.py` — busy-state checking to prevent duplicate builds on concurrent polls
- `docs/agents/issue-tracker.md`, `triage-labels.md` — ticket filing conventions for filed slices

## Stages & Owner Gates

| Phase | Owner | Input | Action | Gate | Output |
|-------|-------|-------|--------|------|--------|
| **Monitor** | Agent (cron) | Apple RSS feed | Fetch new releases daily (conditional GET) | None — agent-driven, non-interactive | Release ID + notes captured |
| **Detect** | Agent | Release ID vs. local state | Compare against dedupe bookmark | None — automatic comparison | Pass/fail → "new release?" |
| **Triage** | Agent | Release notes text | Keyword-match "Speech", "audio" frameworks; classify as beta or GA | None — automatic parsing | Categorized release |
| **File** | Agent | Categorized release | Create GitHub issue per conventions; reference design doc; link to existing playbook | None — automated `gh issue create` | Ticket filed in project repo |
| **Build** | Owner (via playbook) | Filed ticket | Dispatch build against beta Xcode (or defer if beta, per `beta-severity` decision) | Owner gate: "proceed with build?" | Build runs on chosen machine |
| **Verify** | Machine | Build environment | Run test suite against new SDK/OS version | Implicit in app tests | Pass/fail result |
| **Report** | Agent | Build result | Update ticket with pass/fail; flag framework breaks ("Speech changed") even on build pass | Owner gate: "is this actionable?" | Ticket updated with findings |
| **Act** | Owner | Ticket + findings | Decide: ship update, delay, or hold issue open until next release | Owner gate: "proceed with store submission?" | Outcome persisted in ticket |

## Known Traps & Mitigations

1. **Feed is untrusted external content**: Never interpolate release notes into shell commands. Use `--body-file` for ticket bodies (per `gh-body-file-not-heredoc-substitution` memory). Sanitize text before storing in state file (path-traversal risk if feed contains `/../../`).

2. **Concurrent polls on two machines**: Both Mini and MacBook could detect the same new release in the same poll window. Task dispatch's busy-state check (from #613) prevents duplicate builds.

3. **Same release, different channels**: iOS 18.1 beta 3 and iOS 18.1 GA may have the same version string but differ in build number. State file keys must include build number, not just version, to avoid false dedupes.

4. **Stale state file**: Missing, corrupt, or weeks out of sync. Recovery: treat as "nothing seen yet," fetch full current feed, file tickets for releases newer than the system's own OS (already running a newer iOS means we've passed that checkpoint). Do not bulk-refile the entire feed.

5. **Beta churn**: Betas often break for reasons unrelated to app code (SDK internals, simulators, toolchain). `beta-severity` decision governs whether to file immediately or collect data until GA. Either way, the ticket gates on owner review, so a false alarm doesn't unblock a ship.

6. **Environment mismatches**: Beta Xcode isn't installed yet, or `xcode-select` points to stable. Use `EnvMissing` pattern from `project_profile.py`. Loud failure, counted as "environment gap" not "regression," does not block other builds.

7. **Release notes keyword changes**: "Speech" framework renamed or documentation changed in future OS releases. Keyword list lives in `config/projects/*.json`, not hardcoded, so it can be updated per-project.

## Decisions

<!-- marvin:decisions -->
### trigger-source: Which Apple signal counts as "a new release"?

- [ ] A: Apple Developer News RSS feed + conditional GET on slow cadence (matches `gh_watch.js` pattern) — covers both betas and GA in prose; needs text parsing to extract version/platform
- [ ] B: Local `xcodebuild -downloadPlatform` / `softwareupdate --list-full-installers` check — structured data, but only sees what's downloadable on chosen machine; misses release-notes context (Speech framework changes, etc.)
- [ ] C: Both — feed drives release-notes flagging; local check drives "buildable now" gating

### beta-machine: Which machine runs beta Xcode builds?

- [ ] A: MacBook (per ticket text) — keeps Mini's stable Xcode untouched for production dispatch
- [ ] B: Mini (parametrized via second `DEVELOPER_DIR` candidate, already supported) — simpler, but risks broken beta Xcode affecting Min's other jobs if `xcode-select` leaks
- [ ] C: Separate disposable VM/clone — most isolated, most new infrastructure

### beta-severity: What happens when a **beta** (not GA) build breaks?

- [ ] A: File ticket immediately, same as GA — betas are where real incompatibilities first show up
- [ ] B: Log/flag only (Health card, daily digest); file real ticket only once break persists into GA or a later beta — betas churn and break for unrelated reasons

### ticket-home: Where are generated tickets filed?

- [ ] A: Target project repo (e.g. `G-Eskayo/clarity-captions`) — code that needs fixing lives there; matches ADR 0060
- [ ] B: `G-Eskayo/marvin` with `project:<id>` label — watcher agent itself is marvin infra; matches #613's playbook-ticket pattern

<!-- marvin:decisions -->

## Acceptance: Slices & Implementation

The work breaks into four concrete slices (similar to #613's breakdown):

1. **Slice 1: Release-feed watcher + state store** — fetch Apple feed daily (conditional GET), parse for version + build + release notes, dedupe against local state file, fail soft on any error
2. **Slice 2: Playbook dispatch & build integration** — extend `ios-app.json` playbook to accept "build against Xcode variant X"; wire release-detector output into dispatcher; machine selection via existing `task_dispatch.py`
3. **Slice 3: Release-notes keyword flagging** — parse release-notes text for framework mentions (Speech, audio, ARKit, etc. per `config/projects/*.json`); flag on passing builds if keywords match
4. **Slice 4: Multi-project wiring** — extend mechanism to marvin-mobile, nourished, killer-sudoku; parametrize per-project in `config/projects/*.json`; verify no one project's config breaks another

Each slice is filed as a GitHub issue with:
- This design doc's path as reference
- Subset of mechanical tests (6–12 below) as acceptance criteria
- Links to existing code patterns to reuse
- Owner gates clearly marked

## Tests (Mechanical/Misuse Checks)

1. **Doc lands in right repo**: Design doc under `~/.agents/instance/docs/plans/`, not in engine worktree's `docs/plans/` (which is gitignored). Engine PR for #650 shows no `docs/plans/` entry.

2. **Doc shape**: Sections present (Why, Trigger, Machines, Reuse, Stages, Traps, Decisions, Slices, Tests). Missing section = "not doc-first."

3. **Feed fetching fails soft**: Endpoint unreachable, malformed UTF-8, invalid XML → log error + no-op, never crash launchd job. Test: kill feed endpoint, verify no crash + next poll retries.

4. **Empty feed**: No new release found → no-op, no ticket filed, no "all clear" ticket either.

5. **Feed flood**: Multiple betas in one poll window (or replayed entries) → only the newest unseen release gets a ticket. Test: poison feed with 5 old releases + 1 new, verify exactly 1 ticket filed.

6. **Dependency failures distinguish**: Feed unreachable vs. download fails vs. build fails vs. pre-existing test flake — each logs distinctly (use `EnvMissing` shape), never silently swallowed. Test: fail each dependency individually, grep logs for the distinction.

7. **Idempotent replay**: Same release detected twice (beta promoted to GA, or restarted job re-reads state) → no duplicate ticket. Test: manually re-add release to state file, poll again, verify no new ticket.

8. **Concurrent dispatch**: Mini and MacBook poll in same window → only one dispatches build (busy-state checked). Test: trigger poll on both machines simultaneously, verify exactly one build runs.

9. **Wrong/missing environment**: Beta Xcode not installed on chosen machine → environment error (not regression), logs `EnvMissing` shape. Test: `xcode-select` to stable on MacBook, trigger build, verify error is categorized as environment, not app breakage.

10. **Corrupt state recovery**: State file missing/unparsable → treat as "nothing seen yet," do not mass-refile. Test: delete state file, poll, verify exactly N tickets filed (where N = releases newer than running OS), not full feed.

11. **Person's mistake**: Owner closes ticket without fix; next poll still sees release → ticket reopened or mentioned in new context, never mass-refiled. Test: close a filed ticket, poll again, verify no duplicate (lookup existing ticket by release ID, reopen if needed).

12. **Untrusted content handling**: Release notes used in ticket title/body and state file → no shell interpolation (use `--body-file`), no path traversal risk. Test: feed contains `"title": "Exploit: ..'; rm -rf /", "path": "../../etc/passwd"` → verify title appears in ticket body safely, state file path is correct.

## Roadmap & Timing

- **Phase 1** (Slice 1): Foundation — release monitor + state store. Once landed, the system can detect releases even if dispatch isn't wired yet.
- **Phase 2** (Slices 2–3): Integration — dispatch + keyword flagging. Adds the active build loop and release-notes analysis.
- **Phase 3** (Slice 4): Generalization — wire to all iOS/macOS projects. Proves the mechanism isn't Seal-specific.

Post-launch (after clarity-captions ships), this is the next real background agent MARVIN owns.

---

**NOTE FOR IMPLEMENTATION:** This design doc is temporarily stored at `docs/design/ios-update-maintainer-2026-10-27.md` for planning purposes. Per ADR 0071 and test 1 above, it must be moved to `~/.agents/instance/docs/plans/ios-update-maintainer-2026-10-27.md` and committed to the private instance repo before closing #650. This engine-repo PR should carry no `docs/plans/` content — only this design doc, which documents the planning work itself (ADR 0029).
