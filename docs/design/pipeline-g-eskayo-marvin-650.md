## North-star fit

- **Reuses before adding anything new:**
  - `skills/research-colony/scripts/source_monitor.py`'s `fetch_arxiv()` / `fetch_github()` / `fetch_hackernews()` shape (try/fetch → `list[dict]` → except-Exception-return-`[]`-and-log) for a new `fetch_apple_releases()`, riding `run_colony.py`'s **already-scheduled** daily launchd run on both Macs — no new cron/timer job (`feedback-trigger-based-not-polling`).
  - `lib/project_profile.py`: `all_profiles()` (line 292) to enumerate every project rather than hardcoding clarity-captions, `build_env()` (376) to point `DEVELOPER_DIR` at a newly-installed/beta Xcode, and `have("xcode", env)` (395) to tell "not installed yet" (environment problem, no strike) apart from a real break — the exact convention `project_profile.py` already uses for required tiers.
  - `lib/task_dispatch.py`'s `dispatch()` (226) to force the probe build onto the MacBook, per the ticket's own machine decision (signed builds need Xcode there).
  - `skills/to-issues/SKILL.md`'s issue template + `lib/board_registry.py ensure` for filing and tracking the sliced tickets (AC #2) — the same mechanism #613 and every other design doc already uses.
  - The `config/playbooks/ios-app.md`/`.json` playbook itself (#613) as the thing being driven, not re-specified.
- **Correction to the ticket's stated fit:** the ticket says the design doc goes in `docs/plans/`. That path is correct for the *public engine* only up to ADR 0071 step 2 (`fee623d3`), which untracked `/docs/plans/` and `/config/projects/` from the engine and moved owner state to the private instance (`~/.agents/instance/`, confirmed on disk: `project-playbooks-2026-10-22.md` lives there now, not in this worktree). A doc written to this worktree's `docs/plans/` would be silently gitignored and never committed. The doc goes to **`~/.agents/instance/docs/plans/`** instead, same as every design doc since 2026-10-25.
- **Simplest sufficient approach:** no new service, no new ChromaDB collection, no new timer. One new fetch-source function, a small dedupe/state file, and a dispatch call — all composition of existing primitives.
- **Space/time cost:** the feed poll is one small HTTP GET riding a run that already happens (≈free, O(1) extra per existing daily run). The expensive step — an actual Xcode/simulator probe build — only fires on a genuinely new, relevant release, bounded by Apple's real release cadence (at most a few/week in active beta season), not by request volume. State is one small JSON file of seen GUIDs, O(releases) and append-only.
- **Phone-OS / capability fit:** indirect but real — keeps Seal Speak (the flagship iOS app) from silently drifting out of compatibility, the exact gap that cost Gil a timeline surprise before (iOS 27 beta cadence, memory `project-ios-update-maintainer-agent`). Generalizing it across every `ios-app`-playbook project (not just clarity-captions) is north star 4 directly. Gil stays the owner gate for anything that touches Apple (installing betas, approving fixes) — this removes a discovery chore, not his judgment, so it leaves him more capable, not more passive.

## Verified live
`https://developer.apple.com/news/releases/rss/releases.rss` is a real, current Apple RSS feed (confirmed by fetch: items for iOS/iPadOS/macOS/tvOS/visionOS/watchOS/Xcode/TestFlight, betas and final, with `pubDate`). Each `<item>` carries only a title, GUID/link and a "View release notes" link in `content:encoded` — **no release-note prose**. Flagging Speech/audio-framework impact requires a second fetch of the linked release-notes page per new item, not just the feed itself.

## Tests to write first

This ticket's own deliverable (AC) is a design doc + filed ticket slices, no code — `to-issues/SKILL.md` exempts research/decision issues from "How we'll try to break it," and there's no ticket-provided section to pull from (none exists in #650's body). The list below is what the doc will commit each *filed slice* to (misuse categories from the north-star checklist, applied to the actual mechanism being designed), so slice tickets inherit it rather than reinventing it:

1. **Bad/malformed input:** corrupted/truncated feed XML → `fetch_apple_releases()` returns `[]`, logs, doesn't crash the host run (fixture test, mirrors `fetch_arxiv`'s except-block). Release-notes page 404s, redirects to a placeholder, or is non-HTML/oversized → treated as "notes not yet available," retried next run, never asserted as "no audio impact" by default.
2. **Each dependency failing:** `developer.apple.com` unreachable/timeout → this run no-ops, no partial/corrupt state write. `gh issue create` fails or is rate-limited (gh-gate cooldown) → the release is **not** marked seen, so it's retried, not silently dropped. `task_dispatch.dispatch()` to the MacBook fails (offline/busy) → surfaces "could not run, MacBook unavailable," release stays unmarked. New Xcode/simulator runtime not installed yet → `have("xcode", env)` reports EnvMissing, not a false "build broke."
3. **Repeats/concurrency/wrong order:** same release reappearing across polls dedupes by GUID, not list position — running the detector twice on one feed snapshot must not double-file. Mini and MacBook's independent daily research-colony runs both seeing the release same day must not race into two tickets or two competing builds (reuse the existing cross-machine "last one out" / shared-state pattern already proven for research-colony merges). A probe build must not overlap a prior one for the same project (reuse `ticket_pipeline._local_busy`/dispatch busy-skip).
4. **Wrong permissions/machine:** the probe must hard-fail loud if forced onto the Mini or if the MacBook target is unavailable, never silently fall back. The generalized "every `ios-app` profile" loop must skip profiles that don't actually `require: ["xcode"]` in any verify tier (nourished: no machines, not really an iOS app yet) rather than blindly `swift test`-ing a non-Swift repo.
5. **Stale state:** a missing/corrupted seen-releases file on a fresh machine is cold-start ("nothing seen"), not a crash, and must reconcile with the other machine's state via existing sync rather than mass-re-filing history. An already-open ticket for a given release+project is checked for before filing a duplicate.
6. **A person's mistakes:** Gil closing a filed ticket before the fix lands must not cause an immediate re-file next run. A beta Xcode installed at a non-default path must be supported via `env.DEVELOPER_DIR.first_existing` without breaking the mechanism — logged as a new `known_traps` entry on the `ios-app` playbook.
7. **Trust boundary on fetched text:** release-notes HTML is matched against keywords in plain Python string ops only — never interpolated into a shell command, and never handed to a model as an instruction. Test: a release-notes fixture containing shell metacharacters or prompt-injection-style text must not change behavior beyond the substring match.

## Decisions
<!-- marvin:decisions -->
### install-step: Who installs a new/beta Xcode or simulator runtime on the MacBook?
- [ ] A: Owner gate — MARVIN only detects it's missing and asks Gil to install it (consistent with the `ios-app` playbook's existing owner-gate list)
- [ ] B: MARVIN attempts an unattended install (e.g. `xcodes`) using stored Apple ID credentials

### scope: Which projects does slice 1 cover?
- [ ] A: Every profile already on the `ios-app` playbook with an `xcode`-requiring verify tier (clarity-captions, marvin-mobile, killer-sudoku) — generalized from day one
- [ ] B: clarity-captions only; generalize to the others in a later slice

### flag-surface: Where does the "Speech/audio framework mentioned, build still passed" flag go?
- [ ] A: A GitHub ticket on the project (same as a real break, lower priority label)
- [ ] B: A Health/dashboard digest note, no ticket, to avoid ticket noise on every beta
- [ ] C: Both, with the ticket only when the flag coincides with a different real failure

### break-granularity: One ticket per release, or per broken verify tier?
- [ ] A: One ticket per project per release, listing every broken tier inside it
- [ ] B: One ticket per broken verify tier (more tickets, each independently closeable)

### notes: Anything to change? (text) (optional)

## Task List

1. Write the design doc at `~/.agents/instance/docs/plans/apple-release-maintainer-2026-10-27.md`, following the `project-playbooks-2026-10-22.md` shape (Why → North-star fit → mechanism → rollout slices → complexity → Decisions block above), covering: the verified Apple releases RSS feed as the trigger; the two-stage fetch (feed poll for new items → release-notes page fetch only on a new item, for the Speech/audio flag); generalization via `project_profile.all_profiles()` filtered to the `ios-app` playbook; the MacBook-targeted probe build via `task_dispatch.dispatch()`; ticket filing via the `to-issues` template + `board_registry.py ensure`; space/time cost.
2. Get Gil's answers to the Decisions block (doc isn't actionable until answered, same as #613's precedent).
3. File ticket slices on `G-Eskayo/marvin` (this is MARVIN infra, not clarity-captions code) via the `to-issues` template, in dependency order:
   - [ ] Slice A — `fetch_apple_releases()` + seen-GUID dedupe state, wired into `run_colony.py`'s existing daily call.
   - [ ] Slice B — release-notes page fetch + Speech/audio keyword flag on new items.
   - [ ] Slice C — cross-profile probe runner: `all_profiles()` filtered to `ios-app` playbook + `xcode` requirement, `build_env()` override for the new Xcode, `have()` EnvMissing guard, dispatched to the MacBook.
   - [ ] Slice D — ticket filing for real breaks and the flag surface (per the Decisions answers), with existing-open-ticket dedupe.
   - [ ] Slice E — `known_traps` entry on `config/playbooks/ios-app.md`/`.json` for non-default beta-Xcode paths.
4. Run `~/.agents/venv/bin/python ~/.agents/lib/board_registry.py ensure G-Eskayo/marvin` so the new slices show on the dashboard board.