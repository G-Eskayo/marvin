## North-star fit

**Reuses before adding anything** (re-verified against the actual files in this worktree, not assumed from the prior design doc):

- `lib/job_events.py:status_of()` (running/idle/failed/crashed/never) is the real status primitive and tolerates unparsable timestamps (`_parse` returns `None`, never raises). The current `check_scheduled_jobs` in `lib/claims_ledger.py:166-243` still re-derives this itself — ignores `status`, calls `datetime.fromisoformat` unguarded — so it will crash on a naive timestamp and silently pass a `"failed"` run with a recent `finished_at`. This attempt deletes that re-derivation and calls `job_events.status_of()` directly.
- `lib/machine_profile.py` (`NETWORK_PATH`, read as a module attribute at call time, `{"devices": {...}}` shape) is the real registry. `check_machine_registry` (`lib/claims_ledger.py:30,100-132`) still reads `~/.agents/config/machines.json` as a flat list — a file that doesn't exist on either Mac — so it reports `"unknown"` forever on a real machine. This is the review's first must-fix and it is **still present in the code**, despite the prior design doc claiming it was fixed. Fixed for real this time by reading `machine_profile.NETWORK_PATH`'s `devices` dict directly (not `remote_devices()`/`registry_id()` — see below for why).
- `lib/health_checks.py:check_main_health` (`lib/health_checks.py:532-548`) confirms the real shape of `~/.claude/logs/main-health.json`: `{"ok": bool, "sha": str, "checked_at": iso, "failed": [...], "summary": str}`. `check_merge_gate` (`lib/claims_ledger.py:246-272`) still reads a key, `main_branch_requires_status_checks`, that this file never has, so it reports `"untrue"` every night regardless of real state — the review's 4th must-fix, also still present. Fixed by reading the real keys directly. **Not** by importing `health_checks.check_main_health` itself: that module imports `code_sync`, `cron_health`, `task_dispatch`, `metrics_registry` at module load — heavy, SSH-touching side effects with no place in a lightweight nightly claim check. Reading the same file with the same field names, without the import, is the smaller reuse.
- `dataDir` in `dashboard/electron/main/portfolio.js:59` is `~/.claude/portfolio`, and `claimsFile`/`latestClaims`/`runClaims` (`portfolio.js:154-164`) are already wired to `claims_ledger_nightly.py` and `marvin-page-claims.json`. `STATUS_DIR` in `lib/claims_ledger.py:32` already matches. The IPC handlers (`dashboard/electron/main/index.js:507-508`) and preload bindings (`dashboard/electron/preload/index.js:104-105`) are already wired. **This part of the prior design doc's claim was true** — no change needed here.
- `lib/launchd/com.marvin.claims-ledger-nightly.plist` already has the `EnvironmentVariables`/`PATH` block (including `/opt/homebrew/bin`) and `HOME`, copied in the style of `brain-map/launchd/com.marvin.snapshot-deploy-nightly.plist`. **Also already true** — no change needed.
- `lib/health_checks.py:1036` already has `"claims-ledger-nightly": "mini"` in `JOB_PLACEMENT`. **Already true** — no change needed.
- `docs/plans/living-marvin-page-2026-10-08.md`'s status table (last section) already says the Lead/story row is "yes (layer 4: nightly checks on four registered claims)" and "What it can do" is "tracked separately (not checked by this ticket)" — matching the ticket's own scope. **Already true** — no change needed.
- `lib/portfolio_content.py:_visible_text()` already strips `<script>`/`<code>`/`<style>`/tags — reused for `scan_unbacked_claims` instead of a second regex (already imported that way in the current code; kept).

**Correction to the prior design doc's own north-star-fit section:** it asserted `check_machine_registry` had been "fixed by calling `machine_profile` instead of hand-parsing a file" and that `check_scheduled_jobs` had been fixed to call `job_events.status_of()`, and that `check_merge_gate` read `main-health.json`'s real keys. None of that is true of the code actually in this worktree — `lib/claims_ledger.py` is still exactly attempt-1-shaped on all four points the review flagged. The design doc described fixes that were never applied. This attempt applies them.

**Why not `machine_profile.remote_devices()`/`registry_id()` for the registry check (deviating from the prior doc on purpose):** `registry_id()` self-identifies by matching this machine's `hardware_uuid`, computed via live `ioreg`/`sysctl` calls. In a test environment that UUID will never match a fixture's device entries, so `remote_devices()` can't be driven to "only one registered" vs "two registered" without mocking hardware identity — exactly the kind of mock that would hide the real rule. The claim is simply "the registry lists at least two machines"; reading `NETWORK_PATH`'s `devices` dict and counting is the direct, testable statement of that, with no hardware dependency. Smaller and more honest than reusing an API built for a different question (which remote machines am I ≠ how many are registered).

**Simplest sufficient approach:** same shape as before — one module, a static registry, pure check functions, one JSON status file the dashboard already polls. The redraft queue is simplified further than either prior attempt: recompute the full set of currently-failing sections from this run's results every night, no diffing against a previous file. There is no consumer yet (#269 doesn't exist) that needs night-over-night dedup, so building that machinery now would be dead code — the review's own finding ("drops sections still failing," "partial overwrite") is a symptom of that premature mechanism, not something to patch in place.

**Tokens:** unchanged — zero at runtime, pure Python/file reads, one `gh` call behind an injected `run=`. No LLM.

**Phone-OS fit:** unchanged, neutral-to-positive — a small, general, machine-checkable truth primitive.

**More capable, not more passive:** unchanged — it only ever flags a claim or section for Gil to look at; it never rewrites copy itself.

## Tests to write first

Rewritten wholesale: `lib/tests/test_claims_ledger.py` currently in the worktree is the attempt-1 test file (asserts the wrong `machines.json` shape, the wrong `main-health.json` keys, and one tautology — `test_40`'s `assert len(unbacked) >= 0`, which passes no matter what the function does). It gets replaced, not patched.

**Registry correctness (unchanged, already pass):**
1. Empty registry → no exception.
2. Unknown `check_fn` → `validate_registry` flags it.
3. Duplicate ids → flagged.

**Machine registry (closes must-fix #1):**
4. `marvin-network.json` shaped `{"devices": {"mac-mini-1": {...}, "macbook-pro-1": {...}}}`, written to a temp file monkeypatched onto `machine_profile.NETWORK_PATH` → `status == "true"`.
5. Only one device in `devices` → `"untrue"`, detail names the count.
6. File missing → `"unknown"`.
7. Malformed JSON → `"unknown"`, not an uncaught exception.
8. `devices` present but not a dict (e.g. a list) → `"unknown"`.
9. Regression guard: `check_machine_registry()` takes no path argument and reads `machine_profile.NETWORK_PATH` fresh on every call — assert by monkeypatching the module attribute to a nonexistent path and confirming `"unknown"`, never asserting against whatever real file happens to exist on the machine running the suite.

**Repo visibility (already correct in the current code — keep, just re-verify, no regression):**
10. `run=` returns `{"isPrivate": false}` → `"true"`.
11. `{"isPrivate": true}` → `"untrue"`.
12. Non-zero exit → `"unknown"`.
13. Non-JSON stdout → `"unknown"`.
14. `run=` raises `TimeoutExpired` → `"unknown"`, not uncaught.
15. Missing `isPrivate` key entirely → `"unknown"` (closes the review *note*: a missing key must not silently default to "private" → `"untrue"`).

**Scheduled jobs (closes must-fix #2 and #3), built on real `job_events.status_of`:**
16. Last run `status="passed"`, `finished_at` 2h ago → `"true"`.
17. Last run `status="failed"`, `finished_at` recent → `"untrue"` (the exact bug: recency alone no longer passes a failed run).
18. Last run stuck `status="running"` with `started_at` older than `job_events.CRASHED_AFTER_S` (so `status_of` returns `"crashed"`) → `"untrue"`.
19. No job file at all → `"untrue"` ("never run" — not `"unknown"`; a job that silently stopped existing is a real, reportable untrue claim, closing must-fix #3).
20. Job file exists with `"runs": []` → same as above, `"untrue"`, not `"unknown"` (two different ways to reach "never run" must agree).
21. `finished_at` is a naive ISO string (no tz) → no exception; handled consistently with `job_events._parse`.
22. Newest run `status="running"` (not crashed), run before it `"passed"` recently → `"true"` (checks the prior run, doesn't treat "still running" as failure).
23. Newest run `status="running"`, run before it `"failed"` → `"untrue"` (the prior-run fallback still enforces failure, doesn't just grab recency).
24. Last `"passed"` run is 7 days old (over the 48h default) → `"untrue"` (stale), not forever-true.
25. Unreadable/corrupt job JSON → `"unknown"` for that job, not an uncaught exception, and the loop continues to the next required job.

**Merge gate (closes must-fix #4):**
26. `main-health.json` has `"ok": true`, `"checked_at"` recent → `"true"`.
27. `"ok": false`, `"failed": ["test_x", "test_y"]` → `"untrue"`, detail includes the failing test names (not a generic message).
28. File missing → `"unknown"`.
29. Malformed JSON → `"unknown"`.
30. `"ok": true` but `"checked_at"` older than the staleness threshold (24h) → `"untrue"` (stale), not silently true.
31. `"checked_at"` is a naive ISO string → no exception.

**Orchestrator:**
32. One check raising an unexpected exception → that claim's status is `"unknown"` with the exception message; the rest of the run still completes.
33. `run_all()` touches no filesystem — pass a nonexistent `status_dir` and confirm it's never created.
34. Unknown `check_fn` name on a claim → `"unknown"`, not silently skipped or treated as passing.

**Atomic write — concurrency and shape (closes must-fix #5's sibling: unlocked queue write):**
35. Round-trip through `write_status_atomic` → `section` and `claim_id` both present (regression for a dropped field).
36. Two threads calling `write_status_atomic` against the same file concurrently (real `fcntl.flock`, not mocked) → file is always valid JSON after both finish, never torn.
37. Status dir doesn't exist yet → created once, write still atomic.
38. The redraft-queue write uses the same lock-and-replace helper as the status write (not a bare `write_text`) → concurrent writers never tear the queue file either (direct test for the review's unlocked-queue-write note).

**Redraft queue (closes must-fix #5 and #6 — the dropped-entry bug and the unknown-collapses-to-false bug):**
39. Two `"untrue"` claims in the same section → exactly one queue entry for that section.
40. A section with only `"unknown"` results (no `"untrue"`) → **no** queue entry (closes must-fix #6: unknown must never be treated as evidence the page is false).
41. A section failing two nights running (same failing claims both times, called twice with fresh `results` each time, no `previous_queue_file` concept) → both calls produce the same single entry — it is never dropped on the second call (direct regression test for must-fix #5: the exact "comes back the night after" bug).
42. A claim flips `"untrue"` → `"true"` → its section no longer appears in the next call's queue (recomputed from scratch, not accumulated).
43. `"true"` results only → empty queue list.

**Unbacked-claims scanner:**
44. A sentence containing "network" must not be flagged as matching the "two Macs" claim merely because "two" is a substring of "network" — word-boundary matching only (already correct — keep).
45. "MARVIN **runs** on two Macs" (inflected form) is recognized as fact-stating via the keyword heuristic, where the un-inflected literal `\brun\b` would miss it (closes the review's note on keyword-substring false negatives: `run`/`prove`/`work` as bare words don't match `runs`/`proves`/`working`).
46. A sentence matching a registered claim's exact text → no finding.
47. A new fact-stating sentence not in the registry → exactly one finding.
48. Empty copy / missing content → no crash, empty list.
49. `<script>`fact-shaped text`</script>` → never surfaces as a claim (stripped via `_visible_text`).
50. Large input (the realistic page repeated 200×) → completes in well under a second, not quadratic.
51. Seed claim texts match Gil's literal wording from `docs/plans/living-marvin-page-2026-10-08.md` ("it runs on two Macs", "it's open source", "it keeps working while I'm away", "it proves every change with tests before I see it") — a sentence using that exact wording is never flagged unbacked (closes the review's note that the seed texts didn't match the real sentences, so nothing was actually backed).

**Infra (regression-only, cheap, catches silent breakage):**
52. `lib/launchd/com.marvin.claims-ledger-nightly.plist` parsed as XML still declares `EnvironmentVariables`/`PATH` including `/opt/homebrew/bin`, and `HOME`.
53. `claims_ledger.STATUS_DIR` equals `dashboard/electron/main/portfolio.js`'s `dataDir` by literal path comparison — the two halves of this feature must keep agreeing on one file path.

All assertions are exact (no `status in (...)` disjunctions), and every rewritten check function is exercised on all three of its true/untrue/unknown paths.

## Decisions
<!-- marvin:decisions -->
### subtab: Where should the claims ledger show in the dashboard's Portfolio tab?
- [ ] A: A new "Claims" subtab (every claim, its section, status true/untrue/unknown, last-checked time) — mirrors the existing Evaluation subtab's run/results pattern
- [ ] B: Added into the existing "Content" subtab, as a per-page claims block next to its coverage/findings
- [ ] C: Added into the existing "Evaluation" subtab, as a new finding type alongside copy/media findings

### redraft-trigger: #269 doesn't exist yet. When a section has a failing claim, what should happen today, beyond marking it untrue in the status file?
- [ ] A: Nothing further — the durable queue file is the whole mechanism; #269 reads it once built; nothing else visible to Gil before then
- [ ] B: Same queue file, plus a comment on ticket #269 each time a section's queue entry first appears, so Gil sees it without waiting for #269 to ship
- [ ] C: Same queue file, plus open a small `needs-info` ticket per affected section immediately, instead of touching #269

### claim-list: Any claims to cut, or edit the wording of, before they're backed by a check? (text) (optional)
Proposed registry (unchanged from the prior attempt's proposal, using Gil's own sentences from `docs/plans/living-marvin-page-2026-10-08.md:64-75`, the nearest thing to a spec this ticket has): "it runs on two Macs" → machine registry; "it's open source" → repo visibility; "it keeps working while I'm away" → scheduled jobs (`snapshot-deploy-nightly`); "it proves every change with tests before I see it" → merge gate (`main-health.json`). Numeric claims stay out of scope per the ticket's own text ("numbers already come from facts.json").

## Task List

1. Rewrite `lib/tests/test_claims_ledger.py` per tests 1–53 above (red), isolated from real HOME/GitHub/hardware throughout (temp dirs, monkeypatched `machine_profile.NETWORK_PATH`, injected `run=`).
2. Rewrite `lib/claims_ledger.py`:
   - `check_machine_registry()` — no parameters; reads `machine_profile.NETWORK_PATH` fresh each call, counts `devices`, `"true"` if ≥2, `"untrue"` if <2, `"unknown"` on missing/malformed/wrong-shape file.
   - `check_repo_visibility(repo=..., run=...)` — unchanged except: missing `isPrivate` key → `"unknown"` (not default-private).
   - `check_scheduled_jobs(claim_args=None, jobs_dir=None, required_jobs=None, max_age_hours=48)` — rewritten on `job_events.status_of()`; `"never"` → `"untrue"`; `"failed"`/`"crashed"` → `"untrue"`; `"running"` falls back to the prior run (itself checked for `"failed"` and staleness); otherwise stale-checks `finished_at` (normalizing a naive timestamp to UTC before subtracting) against `max_age_hours`.
   - `check_merge_gate(path=None, now=None, stale_hours=24)` — reads `ok`/`failed`/`checked_at`/`sha`/`summary` from `main-health.json` directly (no `gh` call, no import of `health_checks`); missing file → `"unknown"`; `ok: false` → `"untrue"` with failing test names; stale `checked_at` → `"untrue"`; fresh and ok → `"true"`.
   - Add one shared `_write_json_atomic(path, data)` helper (the existing `fcntl.flock`-on-sibling-`.lock`-then-`tmp.replace()` pattern, kept exactly); `write_status_atomic()` becomes a thin wrapper over it.
   - `build_redraft_queue(results)` — drop `previous_queue_file` entirely; group `status == "untrue"` results by section (never `"unknown"`); return one entry per currently-failing section, recomputed from scratch every call.
   - `scan_unbacked_claims()` — keyword patterns gain inflection (`\brun(s)?\b`, `\bprove(s|n)?\b`, `\bwork(s|ing)?\b`, `\bcheck(s|ed|ing)?\b`, `\btest(s|ed|ing)?\b`, plus the existing bare `open`/`two`/`macs?`/`machines?`).
3. Update `lib/claims_ledger_nightly.py`:
   - Correct the four seed claim texts to Gil's literal wording (see `claim-list` decision above).
   - Call `scan_unbacked_claims()` against the current MARVIN page copy: locate the page's `content/longform/*.json` source via `project_catalog.portfolio_repo_path()` (confirm the exact slug — e.g. `marvin.json` — by listing that directory at implementation time; `PORTFOLIO_PAGE_URL` stays as a human-readable label in the log line, not a fetch target), guarded by `readable_guard.readable_within()` so the iCloud-hang case degrades to a logged, skipped step rather than blocking or crashing the whole nightly run.
   - Write the redraft queue through the same `_write_json_atomic` helper used for status, every run (never conditionally `unlink`s a file that's still relevant).
4. `lib/launchd/com.marvin.claims-ledger-nightly.plist`, `lib/health_checks.py` `JOB_PLACEMENT`, dashboard backend (`portfolio.js`/`index.js`/`preload/index.js`), and `docs/plans/living-marvin-page-2026-10-08.md`'s status table: confirmed already correct by reading them — no changes.
5. Frontend: add the subtab/placement decided in `subtab` above to `dashboard/src/components/PortfolioHub.jsx` — add `['claims', 'Claims']` to `SUBTABS` (line 15-23), a `Claims()` component mirroring `Evaluation()` (lines 853-927: `latestClaims()`/`runClaims()`, a status badge per claim, grouped by section), and wire it into the subtab ternary at line 1295.
6. Add vitest coverage in `dashboard/test/portfolio.test.js`, mirroring the existing `describe('evaluation', …)` block (lines 100-129) for `latestClaims`/`runClaims`: null-when-nothing-run, corrupt-file tolerance, reads-latest-result, run-surfaces-real-failure.
7. Rewrite `docs/adr/0061-marvin-page-claims-ledger.md`: machine registry source corrected to `machine_profile.NETWORK_PATH`'s `devices` dict (not `remote_devices()`/`registry_id()`, with the reasoning above), merge-gate field names corrected to `ok`/`failed`/`checked_at`/`sha`/`summary`, redraft-queue section rewritten to "recomputed every run, no diffing, no `previous_queue_file`" — status stays `Proposed` until the Decisions above are answered.
8. Run the full pytest + vitest suite, and `lib/mutation_check.py` against `lib/claims_ledger.py`, before opening the PR; carry the Decisions section through to the PR body verbatim per `docs/agents/decisions-format.md`.