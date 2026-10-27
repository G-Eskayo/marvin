# Apple Release Maintainer: Ticket Slices (Draft)

**Parent issue:** #650 (Apple Release Maintainer)

---

## Slice A: RSS feed fetch + dedupe state (AFK)

### What to build

Fetch Apple's public releases RSS feed once daily as part of `run_colony.py`'s existing daily launchd run. Track seen GUIDs in a state file (`~/.agents/var/apple_releases_seen.json`) to detect new releases. Return list of new items for downstream processing (Slices B, C). Do not fetch release-note pages yet.

End-to-end: `run_colony.py` calls `apple_releases.fetch_feed()` → parses feed → compares GUIDs against state → records new items → returns list for B/C.

### North-star fit

- **Reuse:** extends `run_colony.py`'s existing daily schedule (no new cron job, `feedback-trigger-based-not-polling`). Mirrors `source_monitor.py`'s shape (`try/fetch → list[dict] → except-log-return-[]`).
- **Simplest sufficient:** O(1) on cold start, O(k) on updates (k ≈ 1–3/week). Network: ~50 KB/day. Storage: ~1 MB/year.
- **Compounding:** every iOS project added later gets the probe automatically.

### How we'll try to break it

1. **Bad/malformed input:** corrupted feed XML, truncated response, timeout → return `[]` and log, don't crash.
2. **Network failure:** `developer.apple.com` unreachable → this run no-ops, no partial state write.
3. **Repeats:** same release appearing in multiple polls → dedupe by GUID, not list position.
4. **Stale state:** missing/corrupted `apple_releases_seen.json` on fresh machine → cold-start (nothing seen), not crash.
5. **Concurrency:** Mini and MacBook both running daily at same time → shared state file, last write wins (idempotent GUIDs).
6. **Person's mistake:** manual deletion of state file → next run re-fetches all items from feed (no state = cold-start), could re-file old releases as new. Mitigation: state file lives in `~/.agents/var/`, preserved across runs.

### Acceptance criteria

- [ ] `lib/apple_releases.py::fetch_feed()` fetches feed from `https://developer.apple.com/news/releases/rss/releases.rss`
- [ ] State file `~/.agents/var/apple_releases_seen.json` tracks seen GUIDs with `{guid: {title, link, pubDate, fetched_release_notes: bool, has_speech_audio: null}}`
- [ ] New items compared by GUID; any not in state file returned as a list
- [ ] Function is idempotent: calling twice on same feed snapshot returns same new-items list
- [ ] Network timeouts/errors caught, logged, and return empty list without crashing caller
- [ ] `run_colony.py` calls `fetch_feed()` once daily, logs new items, passes them to Slice B

### Blocked by

None - can start immediately.

### Docs

- `docs/adr/` - none (this is new infra, no prior decision)
- `CONTEXT.md` - mention under iOS playbook section

---

## Slice B: Release-notes fetch + Speech/audio flag (AFK)

### What to build

For each new release from Slice A, fetch its release-notes page and search for Speech/audio framework keywords. Set `has_speech_audio` flag and mark `fetched_release_notes = true` in state. Emit flagged items for Slice C (probe runner).

End-to-end: `apple_releases.flag_speech_audio(item)` → fetches `item.link` → searches for keywords in HTML → updates state → returns flagged items.

### North-star fit

- **Reuse:** extends Slice A output, no new network call structure beyond per-item fetch.
- **Bounded cost:** O(new items) fetches per week (~1–3). Page size ~30–100 KB. Parsing: regex on text extraction.
- **Non-goal:** not parsing full release notes, only flagging items likely to affect Speech/audio frameworks. Seal's own unit tests catch other regressions.

### How we'll try to break it

1. **Bad input:** release-notes page 404s, redirects, or is non-HTML/oversized → treat as "notes not available," mark `fetched_release_notes: true`, `has_speech_audio: null`, don't assert "no audio impact" by default. Retry next run.
2. **Network failure:** fetch times out or 502s → don't update state, item remains `fetched_release_notes: false`, retried next run.
3. **Malformed HTML:** page is valid but keywords don't appear in expected sections → regex search still works (case-insensitive across full text).
4. **Repeats:** same item flagged twice (e.g., dual daily runs) → state dedup by GUID; second run skips items where `fetched_release_notes: true`.
5. **Trust boundary:** release-notes HTML contains shell metacharacters or prompt-injection-style text → parsed as plain string, never interpolated into shell command or handed to model as instruction.

### Acceptance criteria

- [ ] `lib/apple_releases.py::flag_speech_audio()` fetches one release-notes URL
- [ ] Searches for keywords: `speech`, `audio`, `voice` (case-insensitive) in HTML headings and summary sections
- [ ] Sets `has_speech_audio: true/false` and `fetched_release_notes: true` in state
- [ ] Network errors caught, logged, state not updated, item retried next run
- [ ] Unparseable HTML treated as "no flag," not an error
- [ ] Called from Slice A's loop after feed fetch, before returning to caller

### Blocked by

- Slice A (needs state file structure and new-items list)

### Docs

- `config/playbooks/ios-app.md` - document Speech/audio framework in context

---

## Slice C: Cross-profile probe runner (AFK)

### What to build

Enumerate all iOS app projects via `project_profile.all_profiles()` filtered to `playbook == "ios-app"` and `require: ["xcode"]`. For each, dispatch a probe build (swift build/xcodebuild) to the MacBook via `task_dispatch.dispatch(tag="probe:apple-release")`. Override `DEVELOPER_DIR` to point at beta Xcode if flagged. Tag probes with `probe:apple-release` for Activity grouping. Collect results and pass to Slice D.

End-to-end: `apple_probe_runner.run_probes(release_item)` → filters projects → for each: check `have("xcode")`, override env, dispatch → collects passes/fails → returns results.

### North-star fit

- **Reuse:** `project_profile.all_profiles()` (line 292) enumerates projects, `build_env()` (376) overrides `DEVELOPER_DIR`, `have("xcode", env)` (395) detects missing as EnvMissing not a break, `task_dispatch.dispatch()` places work on MacBook.
- **Why MacBook:** signing lives there (`MARVIN_SIGNING_IDENTITY`). Load-share rule lets work go to Mac with headroom.
- **Bounded cost:** O(iOS projects) = 4 dispatches per new release. ~10–15 min wall time per release (projects in parallel).

### How we'll try to break it

1. **Missing Xcode:** `have("xcode", env)` returns EnvMissing → emit ticket for Gil, skip probe (not a false "build broke").
2. **Wrong machine:** try to dispatch to Mini instead of MacBook → hard-fail loud, never silently fall back.
3. **Macbook unavailable:** dispatch target offline/busy → surfaces "could not run," release stays unmarked, retried next run.
4. **Non-xcode project:** profile doesn't actually require xcode in any verify tier → skip it (e.g., nourished without Xcode). Check `config/playbooks/ios-app.json` for `require: ["xcode"]`.
5. **Stale state:** prior probe still running → reuse dispatch's existing busy-skip pattern, don't overlap.
6. **Beta Xcode path:** non-standard install path → auto-detect via `xcode-select -p`, store in `known_traps` if found via alternative method.

### Acceptance criteria

- [ ] `lib/apple_probe_runner.py::run_probes(release_item)` takes flagged release (from Slice B)
- [ ] Filters `all_profiles()` to `playbook == "ios-app"` and `require: ["xcode"]`
- [ ] Checks `have("xcode")` per project; if missing, bubbles as EnvMissing (Slice D files ticket)
- [ ] Overrides `DEVELOPER_DIR` to beta Xcode path if flagged release is beta (auto-detect via `xcode-select -p`)
- [ ] Dispatches probe via `task_dispatch.dispatch(tag="probe:apple-release", machine="MacBook", ...)`
- [ ] Collects results (pass/fail/error) with logs, returns to caller
- [ ] No overlap with prior probes (reuse dispatch busy-skip)

### Blocked by

- Slice B (needs flagged release items)

### Docs

- `config/playbooks/ios-app.md` / `.json` - add `known_traps` section for Xcode paths (in Slice E)

---

## Slice D: Ticket filing for breaks and flags (AFK)

### What to build

For each release, file one GitHub ticket on `G-Eskayo/marvin` per the autonomous decisions:
- **One checkpoint ticket per release** with all project results
- **Title:** `"Xcode X.Y beta checkpoint"`
- **Body:** project status (pass/fail/env issue), error excerpts, speech/audio flag note, link to release notes and dispatch log
- **Deduplication:** query open tickets (title prefix within 24h), comment if exists instead of creating duplicate
- **Label:** `area:apple-release-maintenance`, `priority:low` (unless real break)

End-to-end: `apple_releases.file_ticket(release_item, probe_results)` → builds body → searches for existing ticket → creates or comments → returns ticket link.

### North-star fit

- **Reuse:** `to-issues` template for ticket format, `board_registry.py ensure` to register on dashboard board.
- **Simplest sufficient:** one ticket per release, consolidates all project results, fits in one GitHub conversation.
- **No infrastructure:** using existing GitHub API and dispatch log storage.

### How we'll try to break it

1. **GitHub rate limit:** `gh issue create` rate-limited → log, surface in Health, don't crash runner. Retry next daily run.
2. **Existing open ticket:** same release+project combo already filed → query for title prefix, comment with new result, don't duplicate.
3. **Gil closed the ticket early:** closing a filed ticket doesn't re-file it next run (state is in ticket, not in our code).
4. **Network failure:** can't reach GitHub → don't mark release as "filed," retry next run.
5. **Malformed probe log:** error excerpt is empty/oversized → cap at first 10 lines, never infinite scroll.
6. **Missing Xcode case:** `have()` returned EnvMissing → file ticket with "Xcode not installed" label, not as a break.

### Acceptance criteria

- [ ] `lib/apple_releases.py::file_ticket(release_item, probe_results)` formats body with project status
- [ ] Title: `"Xcode {version} beta checkpoint"`
- [ ] Body includes: affected projects, pass/fail status per project, error excerpts (first 10 lines), Speech/audio flag note, links
- [ ] Label: `area:apple-release-maintenance`, `priority:low`
- [ ] Queries for existing open tickets by title prefix (24h window), comments if exists
- [ ] Uses `to-issues` template format (see SKILL.md)
- [ ] GitHub API errors caught and logged, ticket not marked filed
- [ ] Called from Slice C after probes complete

### Blocked by

- Slice C (needs probe results)

### Docs

- `docs/adr/` - link to decision-log (what was decided about ticket surface, break-granularity)
- `CONTEXT.md` - reference under "Release automation"

---

## Slice E: Known traps entry on ios-app playbook (HITL)

### What to build

Document lessons from beta-Xcode probe work in `config/playbooks/ios-app.md` and `.json`. Include:
- Non-default beta-Xcode install paths and how to detect them (xcode-select -p, xcrun -find swift)
- Signing certificate/provisioning profile gotchas unique to beta Xcode
- Previous regressions (Xcode 15 signing, etc.) and how they were caught/fixed
- Template for future entries (as new regressions are found and fixed)

This is HITL because the content is lessons learned from real breaks—Gil must review and approve what goes in here.

### North-star fit

- **Reuse:** leverages existing `config/playbooks/ios-app.md` structure (ADR 0036 playbook format).
- **Compounding:** grows as new regressions are found, feeds into Slice C's beta-Xcode-path detection.
- **No new infra:** simple markdown + JSON update, no code changes required.

### How we'll try to break it

N/A for HITL slice (no automated behavior to test).

### Acceptance criteria

- [ ] Add `## Known Traps` section to `config/playbooks/ios-app.md`
- [ ] Document: Xcode 15 signing regression (detected Oct 2026, workaround: ...)
- [ ] Document: beta-Xcode detection via `xcode-select -p` and `xcrun -find swift`
- [ ] Add entry template for future regressions (Xcode version, symptom, fix/workaround)
- [ ] Corresponding JSON entry in `config/playbooks/ios-app.json` under `known_traps` field

### Blocked by

- Slice D (findings from probe runs inform what goes here)

### Docs

- `config/playbooks/ios-app.md` / `.json` - primary target for this slice

---

## Summary: Dependencies and Order

```
Slice A (RSS fetch)
  ↓
Slice B (Release-notes flag)  +  Slice C (Probe runner) [can run in parallel]
  ↓                                ↓
  └────────────────┬───────────────┘
                   ↓
              Slice D (Ticket filing)
                   ↓
              Slice E (Known traps) [HITL: review + approve]
```

**Ready to file in order:** A → B (blocked by A) → C (blocked by A) → D (blocked by B+C) → E (blocked by D, HITL)

