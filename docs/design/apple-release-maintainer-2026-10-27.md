# Apple Release Maintainer: automatic beta-Xcode probes for iOS app projects (design, 2026-10-27)

Status: **awaiting decisions** — no build yet. This extends the iOS playbook (`project-playbooks-2026-10-22.md`) with automated early warning for new Apple toolchain releases.

## Why

Four iOS projects need Xcode compatibility checks when Apple ships beta tools:
- **clarity-captions (Seal Speak):** signed app, TestFlight releases, store-review cycle. Beta Xcode can break signing or introduce regressions that only appear once in App Store Connect.
- **marvin-mobile, nourished, killer-sudoku:** all need green builds to pass their gates.

Today, Xcode betas are discovered manually — someone notices the release, downloads it (hours), and runs builds. Missed betas mean surprises at merge time or during App Store review.

**Evidence (2026-10-27):** Xcode 15 beta shipping broke signing; found by hand after 3 days. Apple ships ~weekly on Tuesdays.

**Root cause:** no automation detects new releases. **Fix:** poll Apple's feed, detect new items (Speech/audio framework flagged releases matter most), and probe-build on the MacBook where signing lives.

## North-star fit

- **Reuse:** extends existing systems. `project_profile.all_profiles()` already enumerates all projects. `task_dispatch.dispatch()` already places work cross-machine. `run_colony.py`'s daily loop is the anchor. `to-issues` template already files tickets (see playbooks rollout #2).
- **Compounding:** every iOS project added later gets the probe automatically. Probes and fixes become self-healing over time (ADR 0023 + north-star #1: "machines are cheaper than surprise regressions").
- **No new infrastructure:** RSS poll is O(1) per day. Release-notes fetch only on new items. Dispatch and ticket filing use existing primitives.

## Mechanism

### A. RSS feed poll (daily in `run_colony.py`)

**Input:** Apple's public releases feed (`https://developer.apple.com/news/releases/rss/releases.rss`).

**Logic:**
1. Fetch feed once a day (Tuesday–Saturday, since Apple releases Tuesdays; skip weekend to avoid churn).
2. Track seen GUIDs in a JSON file (`~/.agents/var/apple_releases_seen.json`): `{ "guid": { "title": "...", "link": "...", "pubDate": "...", "fetched_release_notes": false, "has_speech_audio": null } }`.
3. On new item (guid not in seen), **do not fetch release notes yet**. Just store it and mark `fetched_release_notes: false`.
4. Return list of new items for further processing.

**Cost:** O(1) on cold start (first fetch: ~200 items), O(k) on updates (k = new items per week, ~1–3). Network: ~50 KB/day. Storage: ~1 MB for 52 weeks.

### B. Release-notes fetch and Speech/audio flag (run once per new item)

**Trigger:** whenever a new item is detected and `fetched_release_notes == false`.

**Logic:**
1. Fetch the `link` URL (e.g., `https://developer.apple.com/xcode/release-notes/...`).
2. Search for keywords: `speech`, `audio`, `voice` (case-insensitive, in `<h2>`, `<h3>` headings and release summary sections).
3. If any match: set `has_speech_audio = true` and flag the item as speech-audio-relevant.
4. Set `fetched_release_notes = true` for this item.
5. If flagged, emit the item for the probe runner (step C).

**Cost:** O(new items) fetches per week (~1–3). Page size ~30–100 KB each. Parsing: regex on text extracted from HTML.

**Non-goal:** this does *not* parse full release notes. It flags only items likely to affect Seal (Speech/audio frameworks). Seal's own unit tests will catch other regressions.

### C. Cross-profile probe runner (dispatch from MacBook)

**Trigger:** when step B flags an item, or on explicit request.

**Logic:**
1. Enumerate all iOS app projects via `project_profile.all_profiles()` filtered to `playbook == "ios-app"`.
2. For each project:
   - Check `have("xcode")` — if not installed, emit a ticket (step D) and skip the probe.
   - If the flagged release is a beta, override the build environment: point `DEVELOPER_DIR` to the new Xcode installation path (from `config/playbooks/ios-app.md`'s `known_traps` section, or auto-detect via `xcode-select -p`).
   - Dispatch a single `swift build` or `xcodebuild` probe to the MacBook via `task_dispatch.dispatch(tag="xcode", machine="MacBook")`.
   - Tag it with `probe:apple-release` so Activity can group it.
3. Wait for probes to complete (async, ~5–10 min per project depending on build size).
4. If any probe fails: emit a ticket with the error log (step D).
5. If all probes pass: emit a "cleared" ticket update or log-only notification.

**Why MacBook:** signing lives here (`MARVIN_SIGNING_IDENTITY` in the build environment). Single-file tests run on the MacBook by the playbook's rule (§3). Xcode build is heavy; the load-share rule from the storage plan (memory-search, §F) lets work go to the Mac with headroom, but signing is MacBook-only.

**Cost:** O(iOS projects) dispatches per new release. ~10–15 min wall time per release (projects in parallel, gated by the slowest). Storage: probe logs in the dispatch queue (usual practice).

### D. Ticket filing for breaks and the speech/audio flag

**Trigger:** 
- A probe fails.
- A release is flagged as speech-audio-relevant.
- (Decided: which cases emit a ticket? See Decisions block.)

**Logic:**
1. Use the `to-issues` template to file a ticket on `G-Eskayo/marvin` (this is MARVIN infra, not clarity-captions code).
2. Title: `"Xcode [version] beta: [probe status]"` — e.g., `"Xcode 16.1 beta: Seal probe failed (signing)"`.
3. Body:
   - Label: `area:apple-release-maintenance`.
   - Affects: which projects failed (link to their playbooks).
   - Error excerpt from the probe log (first 10 lines of stderr).
   - Link to the release notes.
   - For speech-audio flags: note "Speech/audio frameworks affected" in the description.
4. Check for existing open tickets (same title prefix within 24 hours) to avoid duplicates. If a match exists, comment with the new probe result instead.
5. Link to the dispatch log in Activity so Gil can inspect the full output.

**Who decides:** is the flag enough to file a ticket (Gil gets notified of *every* speech-audio release), or only real probe failures? See Decisions.

**Cost:** O(1) per new release (one ticket or comment). GitHub call: one search, one create-or-comment. Storage: ticket body is ~1 KB.

### E. Known traps entry on `config/playbooks/ios-app.md` and `.json`

**Content:** a new section recording lessons from beta-Xcode probe work, e.g.:
- Non-default beta-Xcode install paths (how to detect via `xcode-select -p` or `xcrun -find swift`).
- Signing certificate/provisioning profile gotchas unique to beta Xcode.
- Previous regressions (Xcode 15 signing, etc.) and how they were caught/fixed.

This entry grows as new regressions are found and fixed. It's a reference for future probe failures and for the probe runner to handle known issues gracefully (e.g., "Xcode 16 has this signing bug, work around it by...").

**Cost:** one-time write, then O(1) on each new trap learned.

## Complexity

- **Daily poll:** O(1) feed fetch, O(k) on new items (k ≈ 1–3/week). Network: ~50 KB/day. Storage: ~1 MB/year.
- **Per-item release-notes fetch:** O(1) per new item. Network: ~30–100 KB per fetch. Parsing: regex on HTML, ~10 ms.
- **Probe dispatch:** O(iOS projects) = 4 dispatches per trigger. Wall time ~10–15 min (projects in parallel, gated by the slowest). CPU: light (Swift build is already gated by the test-cap rule from memory-search-progress, §E).
- **Ticket filing:** O(1) per new release. GitHub API: one search + one create/update. ~500 ms per ticket.
- **Total per new release (worst case):** ~15 min wall time (probes), ~1 KB disk (ticket), ~200 KB network (probes' download of new Xcode APIs from release notes). This is acceptable once per week.

## Rollout (vertical slices)

1. **Slice A — RSS feed fetch + seen-GUID dedupe state, wired into `run_colony.py`'s existing daily call.**
   - File: `lib/apple_releases.py::fetch_feed()` (idempotent, returns new items).
   - State file: `~/.agents/var/apple_releases_seen.json`.
   - Wiring: `run_colony.py` calls `fetch_feed()` once daily, logs new items.

2. **Slice B — Release-notes page fetch + Speech/audio keyword flag on new items.**
   - File: `lib/apple_releases.py::flag_speech_audio()` (fetches one URL, searches for keywords, updates state).
   - Call site: loop in Slice A after fetching new items, before returning.

3. **Slice C — Cross-profile probe runner: `all_profiles()` filtered to `ios-app` playbook, `build_env()` override for new Xcode, `have()` EnvMissing guard, dispatched to MacBook.**
   - File: `lib/apple_probe_runner.py::run_probes()` (takes a release item, enumerates projects, dispatches each).
   - Dependencies: `project_profile`, `task_dispatch`, `have()` from build system.
   - Call site: `run_colony.py` or explicit trigger via `gh run --repo G-Eskayo/marvin` (TBD in Decisions).

4. **Slice D — Ticket filing for real breaks and the flag surface (per Decisions answers), with existing-open-ticket dedupe.**
   - File: `lib/apple_releases.py::file_ticket()` (takes probe result or flag status, files via `to-issues` template).
   - Dedupe: query open tickets with title prefix, comment if exists.
   - Call site: `run_probes()` after probes complete.

5. **Slice E — `known_traps` entry on `config/playbooks/ios-app.md`/`.json` for non-default beta-Xcode paths.**
   - Update: append to the iOS playbook's Known Traps section.
   - Content: current lessons (Xcode 15 signing fix, etc.) + a template for future entries.

## Decisions

<!-- marvin:decisions -->

### feed-trigger: Should every new Xcode release file a ticket, or only ones flagged with Speech/audio?

- [ ] **Every new release** (proactive, Gil stays aware of every beta). Emit a "Xcode X.Y beta: green build on [projects]" ticket, even if no failures.
- [ ] **Only speech-audio releases** (less noise). Emit a ticket only if Speech/audio frameworks are mentioned.
- [ ] **Only actual probe failures.** Emit a ticket only when a probe actually breaks.

**Rationale:** balance notification load (Xcode ~1/week) against signal (Speech/audio ~2/month, real breaks ~1/month). Option 1 keeps Gil in the loop for every beta, which is valuable for early adoption. Option 3 is reactive (surprises at merge time). Option 2 is a middle ground.

### probe-trigger: Who or what decides when to run probes?

- [ ] **Automatic, daily.** Probes run every Tuesday (when Apple releases) as part of `run_colony.py`, same as the feed poll.
- [ ] **On new flagged releases.** Probes run only when Slice B flags a speech-audio item.
- [ ] **Manual, via `gh run`.** Gil explicitly triggers a probe run from the command line, passing the release version or link.

**Rationale:** automatic daily is most reliable (never missed). On-demand is less churn but could miss surprises. Manual is most flexible but requires Gil's attention.

### ticket-surface: How should the ticket surface Speech/audio flags and probe results?

- [ ] **Single "release checkpoint" ticket per release.** One ticket consolidates all probe results and flags. Title: `"Xcode X.Y beta checkpoint"`, body shows each project's status + flags.
- [ ] **One ticket per project.** Separate ticket for each probe result (Seal, marvin-mobile, nourished, sudoku). Body links to the shared flagging ticket.
- [ ] **Logged silently, Gil reviews in Activity.** No ticket. Probes log to the dispatch queue, flagged items update the history store. Gil can inspect in the Activity tab if he wants.

**Rationale:** single ticket is simple, one place to track a release. Per-project tickets align with the iOS playbook (each project is a unit of work). Silent logging is lowest noise but requires Gil to remember to check.

### xcode-path: How should the probe runner find and override the Xcode path for beta versions?

- [ ] **Auto-detect from `xcode-select -p`.** The runner calls `xcode-select -p` to find the active Xcode, then substitutes it in `DEVELOPER_DIR` at dispatch time.
- [ ] **Store explicit paths in `config/playbooks/ios-app.json`.** Add a `beta_xcode_paths: { "16.1": "/path/to/Xcode-16.1-beta.app", ... }` field. The runner looks them up by version.
- [ ] **Accept an override flag at dispatch time.** `task_dispatch.dispatch(..., xcode_override="/path/to/Xcode")` lets the caller (or Slice C) specify it explicitly.

**Rationale:** auto-detect is simplest and always finds the actual Xcode. Stored paths are explicit and easier to test, but require manual updates. Override flag is most flexible but shifts the burden to the caller. Option 1 is recommended; fallback to Option 2 if Option 1 doesn't find the beta Xcode.
