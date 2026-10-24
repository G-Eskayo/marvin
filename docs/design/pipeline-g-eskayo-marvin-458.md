Permission denied for Write — understood, this is a planning-only task so I'll present the plan directly rather than writing it to the design doc file.

## North-star fit

**Reuses, before adding anything new:**
- `lib/scanner_role.py`'s primary/standby pattern (`is_primary(device_id)`, `_primary_device()`) — built for the exact shape of this problem already (ticket-pipeline: the Mini always scans, the MacBook scans only when the Mini's gone quiet). `brief_fallback.is_owner()`/`should_build()` call these directly instead of re-deriving "which machine owns this" from scratch.
- `lib/machine_profile.py`'s `registry_id()`/`machine_label()`/`remote_devices()` — the existing hardware-UUID-based machine-identity resolution, already tolerant of a missing/empty `marvin-network.json` (falls back to `machine_label()`).
- `lib/task_dispatch.SSH_OPTS` and the `ssh ... "cat ..."`-over-SSH idiom already used by `scanner_role.check_primary()` and `health_checks._run_sync_log_remote()` — same options, same shape, same injectable-`run=` convention (`scanner_role.check_primary(now=None, run=subprocess.run)`) so `read_remote()` stays testable against a real local shell instead of a mocked `subprocess.run`.
- The three per-job idempotency checks already in `daily_digest.py` (`if OUT_FILE.exists(): return`) and `research_digest.py` (`if out_path.exists(): return out_path`) — collapsed into one shared, placeholder-aware check (`brief_fallback.produced()`) instead of three near-duplicate, placeholder-blind `.exists()` idioms. This is also what fixes a real correctness gap (below), not just a style tidy.
- `lib/health_checks.py`'s `JOB_PLACEMENT` dict (already updated, in this worktree, to `"daily-digest"`, `"research-colony"`, `"morning-brief"` → `"mini"`, the three new `-fallback` entries → `"laptop"` — verified correct against ADR 0067, no further change needed) and its `check_catalog_fresh`/`check_project_tags` presence-and-age idiom for the new `check_brief_builder()`.

**What's different from the last attempt, and why (the actual point of this revision):**

The last attempt's code review found the fallback logic itself was backwards: `is_owner()` returned `True` on the *standby* (the opposite of its name and of the design, which calls the Mini the owner), and `should_build()` had `if not is_owner(): return False` — which, given that inversion, made it return `False` on the **primary**. Since `daily_digest.main()` and `run_colony.main()` call `should_build()` unconditionally (no `is_owner()` gate at the call site, unlike `morning_brief.write()`, which accidentally masked the bug by gating the call on `is_owner()` itself), the Mac Mini — the one machine meant to always build — would **never build its own daily digest or research digest**. The `.built-by` marker's `reason` field was backwards for the same cause. And the CLI test meant to catch a `build`-command regression re-implemented the command's own `if result: print` branch inline instead of calling the command, so it passed regardless of what the command actually did.

Root cause: `is_owner()`/`should_build()` returned bare booleans with no reason string, so every call site re-derived its own "which case is this, and what do I log" logic, and nothing ever exercised the real `scanner_role.is_primary()`/`machine_profile.registry_id()` composition — every existing test monkeypatched `is_owner`/`should_build` directly, so the inversion was invisible to the suite. This revision:
1. **Fixes the naming/semantics directly**: `is_owner()` becomes `scanner_role.is_primary(machine_profile.registry_id())` — `True` on the Mini, matching the design and its own docstring.
2. **Makes `should_build()` return `(bool, reason)`**, so "owner, always builds" / "standby, Mini already did it" / "standby, covering for the Mini" is one function's three cases, not duplicated at each of three call sites — and the AC's "...and says so in its log" is satisfied by printing that one reason, not by each script inventing its own message.
3. **Adds the tests the review said were missing**: direct tests of `is_owner()`/`should_build()` against the real `scanner_role`/`machine_profile` functions (monkeypatching only `machine_profile.registry_id`, not `brief_fallback.is_owner` itself), so a reintroduced inversion fails a test instead of shipping green.
4. **Rewrites the CLI test** to call the real CLI entry point. `morning_brief.py`'s `if __name__ == "__main__":` block is extracted into `main(argv: list[str])` (the same one-function-the-CLI-calls shape `daily_digest.py`/`research_digest.py` already use), and the test calls `mb.main(["build"])` directly, asserting on real captured stdout.

**One more real defect found while verifying the fix (same class of bug as the "fix_these" items; fixed the same way — a test added):** `produced()` only checked the local copy when no `remote_host` was given, and went straight to SSH otherwise — so `run_colony.py`, which always passes the Mini's `tailscale_hostname`, never got the "the already-synced local copy already shows this was produced" short-circuit the design's own "zero network calls in the common case" claim promised. Collapsing the three scripts' separate `.exists()` idempotency checks into one `brief_fallback.produced(day, path)` (local-only call) fixes this *and* a more important gap: the bare `OUT_FILE.exists()` checks were placeholder-**blind** — if the Mini's quarantined digest had already synced to the MacBook's identical local path, `daily_digest.py`'s idempotency check would see "file exists" and return immediately, **without ever reaching the logic that's supposed to treat a placeholder as not-produced** — a direct miss of the ticket's own "Mini's output exists but is a failure placeholder: counts as not produced" break-it case, on the path most likely in practice (an already-synced file). `produced()` now checks local content (placeholder-aware) first on every call, falling through to `read_remote_fn` only when the local copy doesn't already show real output.

**Narrower, more honest `FAILURE_MARKERS`:** the generic markers (`"NOT found at"`, `"couldn't measure"`, `"START_FAILED"`, `"Traceback (most recent call last)"`) don't appear in any digest/research-digest/brief file ever written (verified by grep — those strings come from `health_checks.py`/`purpose_metrics.py`'s own unrelated output and launchd's failure log), while the real quarantine placeholder text (`"_Quarantined by safety-monitor before shipping"`) was missing — so a quarantined digest was silently treated as real output. `FAILURE_MARKERS` narrows to exactly the two substrings these scripts actually write on failure: `"(claude call failed:"` and the quarantine placeholder. The dead, unused `FAILURE_MARKERS` copies this ticket's own earlier diff added to `daily_digest.py`/`research_digest.py` (never read by either file) are deleted — one definition, not three that drift.

**Where this saves tokens/compute:** halves model calls for daily-digest/research-colony on a normal day (the Mini builds once; the MacBook's fallback is a filesystem/SSH check, no model call, unless actually covering). The `produced()` fix makes "zero network calls in the common case" actually true for `run_colony.py`, not just the other two.

**Where it costs tokens:** none — pure control-flow and a few filesystem/SSH-metadata reads.

**Phone-OS direction:** unchanged — infrastructure for who builds a feed, not endpoint/content-facing.

**More capable or more passive:** removes silent duplicate work and makes "which machine actually built today's brief" visible and *correct* in Health (via the `.built-by` marker, not a guess from mtime) — lets Gil trust the pipeline instead of checking by hand.

**Checking the ticket's stated fit against the code:** "reuses the existing jobs and launchd setup" still holds — no correction needed.

## Decisions

None needed — ADR 0067, the existing primary/standby pattern, and the existing job-placement table fully determine this design; nothing here is a toss-up for the owner.

Three things to flag in the PR description, not as Decisions (each is either a physical action the diff can't perform, or a scoping call with a stated reason, not an open choice):
- Installing the laptop's three `*-fallback` plists and confirming the Mini only runs the unchanged primary plists requires a live `launchctl bootout`/`bootstrap` on each physical machine; this PR adds/relocates plist files but can't touch either Mac's real `~/Library/LaunchAgents`.
- `cross_machine_merge.py` (the fan-out+merge step ADR 0067 calls "unnecessary... for these jobs") is left untouched: its `run_merge_authority()` already no-ops gracefully on exactly the day the standby has nothing to merge, which is now the normal case. Retiring it fully is real cleanup but not in this ticket's AC, and it still does unrelated, still-needed item-sync work (`sync_research_feed`/`sync_qa_knowledge`/`sync_paper_knowledge`).
- A late-recovering fallback doesn't retroactively rebuild a downstream job that already ran without it (e.g., digest fallback finishes at 10:30, after the Mini's own 09:45 brief already built). Each job's one-hour window is independent, matching ADR 0067's own framing. Out of scope here; noted so it isn't mistaken for an oversight.

## Tests to write first

**`lib/tests/test_brief_fallback.py` (rewrite):**
1. `is_owner()` True/False driven by `machine_profile.registry_id()` (monkeypatched), not by mocking `is_owner` itself — catches the exact inversion that shipped.
2. `is_owner()` resolves correctly when `registry_id()` falls through to `machine_label()` (registry missing/empty).
3. `produced()` True for real local content; `read_remote_fn` never called.
4. `produced()` False, local-only: missing file, empty file, each `FAILURE_MARKERS` string (parametrized).
5. `produced()` False, local-only, unreadable file (chmod, try/finally restore, root-skip guard as in `test_code_sync_live_edit_lease.py:350`).
6. `produced()` with `remote_host` given but local already shows real content: `read_remote_fn` never called (the network-savings claim, verified).
7. `produced()` with `remote_host` given, local missing/placeholder: falls through; True/False per `read_remote_fn`'s return (parametrized: real content, `None`, empty, placeholder).
8. `produced()` never raises when `read_remote_fn` raises.
9. `produced()` handles a multi-MB garbage blob from `read_remote_fn`.
10. `should_build()` returns `(True, "owner")` whenever `is_owner()` is True regardless of `produced()` — the test that would have caught `if not is_owner(): return False`.
11. `should_build()` on a standby: `(False, ...)` when the Mini already produced it, `(True, "covering for the Mini...")` when not.
12. `should_build()` fails open to `(True, "covering...")` with no primary registered or no `tailscale_hostname`.
13. `_infer_remote_path()`: home-relative → `$HOME/...` (parametrized across `briefs/`, `daily-digest/`, `research-digest/`); outside home passed through.
14. `test_read_remote_lets_home_expand_but_quotes_rest`: real local `sh -c` via injected `run=`, planted file under a tmp `$HOME`.
15. `test_read_remote_quotes_against_shell_injection`: malicious path with `; touch pwned #` through the same real local `sh -c` — no `pwned` file, no raise.
16. `test_read_remote_handles_ssh_failure`: `run=` raises or returns non-zero → `None`, never raises (also covers dropping `|| echo ""`).
17. `mark_built()` writes `{day}.built-by` with `built_by`/`reason`/`built_at`.
18. `FAILURE_MARKERS` contains the real quarantine string and `"(claude call failed:"` (regression guard on the narrowing).

**`lib/tests/test_morning_brief.py` (rewrite the 5 fallback tests):**
19. `write()` idempotent via `produced()` for a real existing brief (raise-on-call sources).
20. Standby, Mini already produced (real `registry_id`/`_primary_device` plumbing, not mocked `should_build`): `write()` returns `None`.
21. Standby, nothing produced: `write()` builds; marker names this machine, reason `"covering for the Mini..."`.
22. Owner: `write()` builds unconditionally; marker names the Mini, reason `"owner"`.
23. `main(["build"])` — the real CLI entry point — prints nothing when already built, prints the path when it builds (catches the exact defect found: the old test never called the CLI at all).

**`skills/improve/scripts/tests/test_daily_digest.py` (rewrite tests 19–21):**
24. No module-level `FAILURE_MARKERS` left in `daily_digest.py` (regression guard against the drift the review flagged).
25. `main()` short-circuits via `produced()` for real content (unchanged behavior); does **not** short-circuit on a placeholder-only existing file — proceeds to `should_build()` instead.
26. Standby, Mini already produced (real plumbing): context-assembly functions never called, skip reason printed.
27. Standby, covering: existing flow unchanged, `mark_built` writes a `.built-by` naming this machine with a covering reason.
28. Owner: unchanged flow, `.built-by` names the Mini, reason `"owner"`.

**`skills/research-colony/scripts/tests/` (new `test_run_colony.py`; extend `test_research_digest_fallback.py`):**
29. `run_colony.main()` short-circuits via `produced()` when today's digest has real content — `source_monitor.main()`/`correlate.correlate()` never called.
30. Standby, Mini already produced: same never-called assertion; assert the injected remote reader is never invoked when local already shows real content (this is the specific gap this revision fixes, tested at its exposing call site).
31. Standby, covering: fetch→correlate→digest runs unchanged; `.built-by` written next to the research digest.
32. `research_digest.py` has no local `FAILURE_MARKERS` left (deletion asserted directly); `generate()`'s own `.exists()` idempotency untouched (existing test 24, kept).

**`lib/tests/test_health_checks.py` (rewrite tests 25–28):**
33. `JOB_PLACEMENT` has all six job names correctly mapped (regression lock on what's already correct).
34. Existing `test_job_placement_flags_missing_stray_and_unplaced_jobs` passes unmodified.
35. `check_brief_builder()` before any builder's deadline, nothing built: **green** ("not due yet") — the case the old design didn't have (it cried wolf any time of day).
36. After a deadline with that builder still missing: **yellow**; all three past-deadline and missing: **red**.
37. Output present → reads its `.built-by` marker and names the machine in the detail string (AC #4, verified against a real marker, not mtime).
38. Output present but marker missing/malformed → still counts as built, names "unknown machine", never crashes.
39. All against `tmp_path`-based path constants, never real `~/.claude`.

## Task List

1. Rewrite `lib/brief_fallback.py`: fix `is_owner()` to `scanner_role.is_primary(machine_profile.registry_id())`; change `should_build()` to return `(bool, reason)`; make `produced()` always check local content first (placeholder-aware, injectable `read_remote_fn=read_remote`) before any SSH; narrow `FAILURE_MARKERS` to the two real substrings; rewrite `read_remote(..., run=subprocess.run)` with `shlex.quote` on everything except a leading `$HOME/`, dropping `|| echo ""` so failure yields `None`; add `mark_built(output_dir, day, reason)`.
2. Rewrite `lib/tests/test_brief_fallback.py` per tests 1–18; confirm each fails against the current buggy code first, passes after.
3. In `lib/morning_brief.py`: extract `__main__` into `main(argv)`; rework `write()` around `produced()` + `should_build()`, print only the non-`"owner"` reason, call `mark_built()` on the correct branch.
4. Add tests 19–23 to `lib/tests/test_morning_brief.py`.
5. In `daily_digest.py`: delete dead `FAILURE_MARKERS`; swap `.exists()` for `produced()`; swap the unconditional `should_build()` call for the fixed tuple form; call `mark_built()` after a successful write.
6. Rewrite tests 24–28 in `test_daily_digest.py`.
7. In `run_colony.py`: same `produced()`-then-`should_build()` pair; call `mark_built()` after `research_digest.generate()` returns a path. Verify `import brief_fallback` resolves to this worktree's copy under tests (confirmed by reasoning: the real `~/.agents/lib` has no `brief_fallback.py` yet, so resolution falls through to the worktree copy regardless of insertion order) — re-confirm with the new tests in place rather than leaving it as an assumption.
8. In `research_digest.py`: delete dead `FAILURE_MARKERS`; leave `generate()`'s own idempotency and `today_path()` untouched.
9. Add tests 29–32 (new `test_run_colony.py`; extend `test_research_digest_fallback.py`).
10. In `lib/health_checks.py`: add `time` to the `datetime` import; replace `check_brief_builder()`'s mtime-staleness logic with the deadline-aware, marker-reading version; remove the now-unused `BRIEF_BUILDER_STALE_HOURS`. No `JOB_PLACEMENT` change needed (already correct).
11. Rewrite tests 33–39 in `test_health_checks.py`.
12. Move `config/launchd/com.marvin.daily-digest-fallback.plist` to `skills/improve/com.marvin.daily-digest-fallback.plist` (matching its primary's colocation, and `research-colony-fallback.plist`'s already-correct placement) and fix its comment ("09:30 primary" is wrong — the primary runs at 08:30; 09:30 is `cross-machine-merge`'s slot). The other two fallback plists are already correctly placed and commented.
13. Run the full affected suites and confirm every new/changed test fails pre-fix, passes post-fix, on its own step.
14. In the PR description: the three flagged Decisions-section items (manual `launchctl` step; `cross_machine_merge.py` left untouched and why; independent per-job fallback windows).