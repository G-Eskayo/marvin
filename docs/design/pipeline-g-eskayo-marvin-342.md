## North-star fit

**Reuses before adding anything new** (re-verified by reading every file in this pass, not re-assuming the first attempt's claims): the display path is unchanged and still correct — `metrics_registry.record()` → per-machine JSON → `dashboard/electron/main/metrics.js:readHistory` → `SubsystemDrilldown.jsx`. `auto_merge_shadow.mutation_score()` / `MIN_SCORE = 80` are the real score parser and threshold (confirmed again at `lib/auto_merge_shadow.py:33,41`) — import both, never re-hardcode 80. `commit_check.py` already writes the skip log; `auto_merge_policy.area()` already classifies a path as `"core"` from `config/auto_merge.json`. `health_checks.py` already imports `quality_trends as qt` under a `try/except ImportError` guard and already calls `qt.check_quality_trends()` inside `run_all()` (`lib/health_checks.py:33-36,1425-1426`) — re-read in full this pass, confirmed correct and untouched; only `JOB_PLACEMENT` (`lib/health_checks.py:1002`) is actually missing the `"quality-trends"` entry. `config/projects/marvin.json` (`clone_mode: "catalog"`) is real and is returned by `project_profile.all_profiles()`, so marvin needs no special-cased branch. The ticket states no north-star fit of its own to check.

**Why this is a rewrite, not a resubmission:** the review's 23 must-fix findings are not surface typos — they show every external contract in the first draft was invented rather than read: `lib.git_token` doesn't exist (real contract: `auto_merge_shadow._gh(args) -> str`, raw JSON text via `project_catalog.run_env()`); `commit_check.py` logs `str(Path.cwd())`, never a GitHub slug; `git rev-list --min-age=<seconds>` takes an absolute epoch, not a duration; `resolve_clone` for a catalog-mode project needs `catalog=`; `metrics_registry.record()` has no same-day replace; severity was a hardcoded string. I verified each of these against the real source this pass (not the prior doc's claims) before committing to a fix.

**Simplest sufficient approach:** same shape as before (one collector module + one Health check), but every fix below replaces an invented behavior with the one the real collaborator already has, rather than adding a parallel abstraction. One new primitive only: an additive `replace_same_day` kwarg on `metrics_registry.record()` (default `False`, every existing caller unaffected — confirmed by grepping all 5 call sites: `health_checks.py:1398`, `sandbox_orchestration.py:368`, `network_reachability.py` uses its own `record`, and the test file's 20-odd calls, none pass this kwarg).

**Where it spends vs. saves tokens:** unchanged — one fixed daily `gh pr list` call per project on the mini (now correctly capped with `--limit 100` instead of silently truncating at gh's default 30), not per-ticket. Idempotent same-day recording now actually works, so a second same-day run (e.g. after a mini restart) replaces instead of duplicating the series.

**Capability, not passivity:** unchanged — pure observability of a rule that's already enforced (ADR 0063). No decision is automated by this ticket.

---

## Root causes of the review failure (not just the symptom list)

1. **Invented contracts instead of reading real ones** — `lib.git_token`, pre-parsed `gh` return value, slug-shaped `repo` in the skip log, absolute-epoch `--min-age`, `resolve_clone` without `catalog=`. Every one of these is fixed below by copying the real signature from the file that already uses it correctly.
2. **Falsy treated as "no data"** — `p.get("score") and ...`, `metrics.get(...) or 0`. Fixed once, structurally: `is not None` everywhere a score is checked, and a metric key is **omitted** (not written as a fabricated `0`) when there is nothing real to report.
3. **Tests that assert their own setup** — `len(results) >= 0`, `<= 10000` on a 10k-line file, a bare `pass`, several tests that never patch `project_profile.all_profiles`/`resolve_clone` and so touch real host state. Every rewritten test below asserts a real, falsifiable outcome against real collaborators, with mocks only at the true I/O boundary (the `gh` callable and — where unavoidable — `time.time`).
4. **Stubbed machinery declared but never wired** — `_RECORDED_TODAY` declared, unused; `check_quality_trends()` hardcoded `"green"`. Both implemented for real this pass.

---

## Current-state findings (re-verified this pass, with exact lines)

- `auto_merge_shadow.py:33,41,189-193` — `MIN_SCORE = 80`, `mutation_score(body) -> int|None`, and the real `_gh(args) -> str` via `subprocess.run(["gh", *args], ..., env=project_catalog.run_env())`. `quality_trends.py` gets an identical local `_gh`.
- `project_catalog.py:404-419` — `run_env()` is the real env-builder (gate `bin/gh` first on PATH, shared `GH_TOKEN`). `catalog_path()` / `read_catalog()` are the real, already-used (`health_checks.check_catalog_fresh`, `lib/health_checks.py:418-432`) pattern for a per-machine catalog that may be stale or missing — reuse exactly, including its "missing = degrade gracefully" behavior.
- `project_profile.py:all_profiles()` returns `config/projects/marvin.json` (`repo: "G-Eskayo/marvin"`, `clone_mode: "catalog"`) — confirmed by listing `config/projects/*.json` and reading the file; no special-cased "home repo" branch needed.
- `project_profile.resolve_clone(profile, catalog=None, ensure=False)` (`lib/project_profile.py`) — for `clone_mode: "catalog"` needs `catalog=project_catalog.read_catalog(project_catalog.catalog_path())`, exactly as `check_catalog_fresh()` already does. Omitting `catalog=` silently resolves every catalog-mode project to `None`.
- `commit_check.py:38,43` — `_log(..., repo: Path)` writes `"repo": str(repo)`, and `main()` calls `check(Path.cwd(), message)` — confirmed: this is always a filesystem path, never `"owner/repo"`. Matching must compare against the resolved local clone path, with a tested fallback for pipeline-ticket worktrees.
- `sandbox_orchestration.py:44,69,314` — `WORKTREES_ROOT = ~/.agents-pipeline-worktrees`; worktree dirname = `branch.replace("/", "-").replace("#", "-")`, confirmed against this very session's own cwd (`pipeline-g-eskayo-marvin-342`, from branch `pipeline/g-eskayo/marvin#342`). The repo's short name (`"marvin"`) always appears as a `-`-delimited token in that dirname.
- `auto_merge_policy.area(path, rules, existing_top_level, extra_core=())` (`lib/auto_merge_policy.py:56`) — `existing_top_level=[]` is safe for the `"core"` branch this ticket needs (it's only consulted for the `"new-top-level"` branch).
- `config/auto_merge.json` — real `core` glob list (`lib/auto_merge*.py`, `.claude/**`, `**/*secret*`, etc.) is exactly what "a core-area change merged without tests" means; loaded once via `amp.load_rules()`.
- `metrics_registry.py:36` **docstring**: *"Subsystem names must not contain a literal '.' as the parser splits on the rightmost '.' to extract the machine label."* — **the first attempt's `f"quality-trends.{short_name}"` subsystem name violates this documented invariant of a shared primitive** (not flagged by the review, found this pass by reading the module's own contract). Fix: hyphen, not dot — `f"quality-trends-{short_name}"`.
- `job_events.py:132-156` — `step(name, detail)` and `reported(default_name, label)` are the real job-observability primitives; `record_all`'s per-repo failures must call `job_events.step(...)` (and print to stderr), not swallow silently.
- `health_checks.py:33-36,1425-1426` — wiring is correct and untouched; `JOB_PLACEMENT` (`:1002`) needs `"quality-trends": "mini"` added.
- `config/launchd/com.marvin.quality-trends.plist` — correct as drafted (mini-only, 06:00 daily); kept as-is.
- Ran the **existing** `lib/tests/test_quality_trends.py` against the **existing** (buggy) `lib/quality_trends.py`: **29/29 pass**. This is the review's point made empirical — every one of these tests is vacuous; none can fail against the bugs they claim to cover. All 29 are replaced, not patched.
- New, previously-unflagged hang risk found by reading `repo_size()` closely: its time-box check runs once per `os.walk` directory, at the top of the loop body — a single huge **leaf** directory (no further iterations after it) can blow the whole budget with no truncation ever triggered, since the next check that would catch it never happens. The existing test only "passes" by luck of directory ordering. Fixed by also checking the budget every N files inside the `fnames` loop.
- `auto_merge_shadow.py`'s `new_top_level_this_week = 0` stub (and its own TODO, already in this worktree's diff) stays flagged, out of scope — unchanged from the first attempt's (correct) call.

## Ambiguity resolved: "red when a core-area change merged without tests"

Unchanged interpretation, now backed by a real test: the only signal for "landed without a test" is the skip log (commit-msg gate). Red = a skip-log entry in the 7-day window whose `files` include a path `auto_merge_policy.area()` classifies `"core"` against `config/auto_merge.json`'s real rules. A scored-but-low-mutation PR had tests, so it's the yellow (trending) signal, not red.

---

## Plan

1. **`lib/metrics_registry.py`** — add `replace_same_day: bool = False` to `record()`. Implementation: open/create a sibling `.lock` file next to the snapshot path, `fcntl.flock(LOCK_EX)`, read-modify-write under the lock, atomic `tmp.write_text(...); tmp.replace(path)`, unlock. When `replace_same_day` and the last snapshot's `timestamp[:10]` equals today's date, overwrite `snapshots[-1]` instead of appending. Narrative-file append stays outside the lock (best-effort, non-authoritative, matches existing behavior). Default `False` — every existing caller (`health_checks.py:1398`, `sandbox_orchestration.py:368`, `tests/test_metrics_registry.py`) is unaffected.

2. **`lib/quality_trends.py` (rewrite in place)**
   - `_gh(args: list[str]) -> str` — `subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=60, env=project_catalog.run_env()).stdout`. Delete the `lib.git_token` import and `mock_gh` fallback entirely.
   - `new_top_level_folders_since` — replace `--min-age=<seconds>` with `git rev-list -1 --before="<since_days> days ago" HEAD` (git's own relative-date parser — no manual epoch/ISO math, no root-commit fallback). Empty `old_ref` → return `set()`.
   - `repo_size` — split `EXCLUDE` into an exact-name set and a glob set (`fnmatch.fnmatch(d, ".venv-*")`); check the time budget both per-directory (existing) **and** every 500 files inside the `fnames` loop (new — closes the single-huge-leaf-directory hang).
   - `_tail_lines(path, max_lines=5000)` — real bounded tail read: seek from EOF in 64 KB chunks, accumulate until `max_lines` lines or BOF, decode only that tail. Documented limitation: assumes chronological appends (true for `commit_check.py`'s log), so a match older-in-file than the tail window is missed even if in the time window — acceptable for an append-only log, called out explicitly in the docstring.
   - `recent_skips(log_path, repo, clone_path, since_days=7)` — new `clone_path` parameter; filters via `_tail_lines` + a new `_repo_matches(logged_repo, clone_path, repo)` helper: exact match against `str(clone_path)`, or (when the logged path's parent is `~/.agents-pipeline-worktrees`) a `-`-delimited token match of the repo's short name against the worktree dirname. Known, documented limitation: a repo whose short name is a substring-token of another repo's owner slug could theoretically collide — flagged, not fixed (same treatment as the existing subsystem short-name collision note).
   - `merged_pr_scores(gh, repo, since_days=7)` — `gh(["pr", "list", "--repo", repo, "--state", "merged", "--limit", "100", "--json", "number,mergedAt,body"])`, `json.loads()` the returned text (catch `Exception` → `[]`, catch `json.JSONDecodeError` → `[]`). Unparseable `mergedAt` → exclude that PR (don't assume "in window"). `pr.get("body") or ""` before `ams.mutation_score(...)` (handles `"body": null`).
   - `collect(...)` — `prs_below_80pct` via `p["score"] is not None and p["score"] < ams.MIN_SCORE`; `mutation_score_pct` stays `None` when no PR was scored (never a fabricated `0`); passes `repo_path` into `recent_skips` as `clone_path`.
   - `record_all(...)` — `resolve_clone(profile, catalog=project_catalog.read_catalog(project_catalog.catalog_path()), ensure=False)`; per-repo `try/except Exception as e: print(..., file=sys.stderr); job_events.step(f"{repo} failed", str(e)[:200]); continue` (no bare `pass`); subsystem name `f"quality-trends-{short_name}"` (hyphen, not dot — honors `metrics_registry`'s documented no-dot invariant); `mr.record(subsystem, payload, replace_same_day=True)` where `payload` always carries `prs_below_80pct`, `prs_unscored`, `test_skips_7d`, `new_top_level_7d`, `repo_files`, `repo_folders`, `repo_size_bytes`, and conditionally `mutation_score_pct` only when not `None`.
   - `check_quality_trends(repos=None)` — load `amp.load_rules()` once; per project, per-project `try/except` (a failure becomes that project's own yellow/red "check failed: …" result, not a silent skip, and never blanks other projects); severity ladder:
     - no snapshot yet → green, "no data yet" (informational, not a failure).
     - else: **red** if any of this project's `recent_skips` (freshly read from the skip log, same path/window as `collect`) match `amp.area(path, rules, [], []) == "core"` for any file in that entry.
     - else **yellow** if `mr.compare(subsystem, previous_snapshot, latest_snapshot)` shows `test_skips_7d` or `mutation_score_pct` in `"regressed"` direction (requires ≥2 snapshots; with only one, skip trend check, not a crash), **or** if the latest snapshot is older than 2 days (stale: the daily job missed a run).
     - else **green**.
   - `run()` — drop the `lib.git_token` try/except and `mock_gh`; build `_gh` directly; keep the `@job_events.reported("quality-trends", "Quality trends")` decorator and `job_events.step(...)` calls.

3. **`lib/health_checks.py`** — add `"quality-trends": "mini"` to `JOB_PLACEMENT` (`:1002`). No other change (wiring at `:33-36,1425-1426` is already correct).

4. **No dashboard/JS changes** — re-confirmed by reading `dashboard/electron/main/metrics.js` and `SubsystemDrilldown.jsx` references again; both already tolerate a metric key being absent from some snapshots.

5. **Deployment** — existing plist kept as-is.

6. **Flag, don't fix** — `auto_merge_shadow.py`'s `new_top_level_this_week = 0` stub and its existing TODO comment stay untouched, out of scope.

---

## Tests first (every one rewritten to exercise real behavior against real collaborators; mocks only at the `gh` I/O boundary and, where unavoidable, a controlled `time.time`)

**`git`/filesystem reality (replaces the self-confirming originals):**
1. `test_new_top_level_folders_since_recent_folder_detected_old_folder_not` — two commits 14 days apart (via `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE`), `since_days=7`: the folder added in the recent commit is caught; a folder from the 14-day-old commit is not. *(Replaces the vacuous `test_new_top_level_folders_since_with_new_folder`.)*
2. `test_new_top_level_folders_since_no_commit_old_enough_returns_empty_not_root` — only "now" commits exist, `since_days=365`: asserts empty set, not a diff against the initial empty tree.
3. `test_new_top_level_folders_since_missing_repo` / `_shallow_history` — kept (already real, already pass for the right reason).
4. `test_repo_size_excludes_hidden_venv_glob` — `.venv-3.11/` with a large file inside, excluded via `fnmatch`, not literal match.
5. `test_repo_size_huge_leaf_directory_truncates` — one directory with 5,000 files, `time.time` patched with a controlled incrementing sequence (deterministic, not wall-clock-flaky) that crosses the budget mid-`fnames` loop: asserts `truncated=True` and `files < 5000` (proves the inner-loop check fired, not just the outer one).
6. `test_repo_size_missing_repo` / `_excludes_git` / `_excludes_node_modules` — kept.

**Skip log (replaces the slug-shaped fixtures with the real contract):**
7. `test_recent_skips_matches_resolved_clone_path` — log entry `"repo"` = `str(clone_path)` (as `commit_check.py` really writes it), matched by `recent_skips(log, repo, clone_path)`.
8. `test_recent_skips_matches_pipeline_worktree_naming` — log entry `"repo"` = a path under `~/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-342` (this session's own real pattern): matches repo `"G-Eskayo/marvin"`, does **not** match `"G-Eskayo/nourished"`.
9. `test_recent_skips_tail_bound_is_real` — 50,000 lines written; the first 40,000 are recent-and-matching but beyond the tail window, the last ~100 are recent-and-matching within it: asserts only the tail-window entries return (proves the bound is real, not just the time filter).
10. `test_recent_skips_tolerates_corrupted_lines` / `_missing_log` — kept (already real).

**`merged_pr_scores` (gh test double now returns raw JSON text, the real contract):**
11. `test_merged_pr_scores_parses_real_json_text` — gh double returns `json.dumps([...])`, not a pre-parsed list; asserts correct scores.
12. `test_merged_pr_scores_uses_limit_100_and_merged_state` — asserts the constructed `gh` args include `--limit`, `"100"`, `--state`, `"merged"`.
13. `test_merged_pr_scores_null_body_does_not_crash` — `"body": None` → treated as unscored, not a `TypeError`.
14. `test_merged_pr_scores_malformed_merged_at_excluded` — a PR with an unparseable `mergedAt` is dropped, not assumed in-window.
15. `test_merged_pr_scores_gh_failure_returns_empty` / `_malformed_json_returns_empty` — real `Exception`/`json.JSONDecodeError` from the gh double.

**`collect` / severity correctness:**
16. `test_prs_below_80_uses_is_not_none_and_min_score_constant` — a real `0%` score **is** counted; patching `ams.MIN_SCORE` to a different value changes the threshold (proves it's not hardcoded `80`).
17. `test_unscored_prs_never_fabricate_a_score` — all-unscored PRs → written payload has no `mutation_score_pct` key at all (not `0`).
18. `test_repo_growth_keys_reach_the_written_snapshot` — `repo_files`/`repo_folders`/`repo_size_bytes`/`new_top_level_7d` are present in the **file on disk** after `record_all`, not just in `collect()`'s return value.

**`record_all` (real `project_profile`, real locked `metrics_registry`, no bare mocks of host state):**
19. `test_record_all_resolves_catalog_mode_clone_with_catalog_arg` — a fake catalog JSON with `localPaths`, patched `project_catalog.catalog_path`/`read_catalog`; asserts the repo is NOT skipped (catches the missing `catalog=` bug).
20. `test_record_all_subsystem_name_has_no_dot` — asserts the subsystem string passed to `mr.record` contains no `.` (locks in the `metrics_registry` contract).
21. `test_record_all_same_day_replaces_not_appends` — through the real locked `record()` path against a tmp `METRICS_DIR`, two calls same (faked) day → one snapshot.
22. `test_record_all_two_different_days_append` — two snapshots.
23. `test_record_all_concurrent_writes_stay_valid_json` — threaded calls against a real tmp file; result parses and has the expected count.
24. `test_record_all_one_repo_gh_fails_other_still_recorded_and_logged` — two repos, one gh-failing; asserts the other is recorded **and** `job_events`'s run log shows a step for the failure (not silently swallowed).
25. `test_record_all_missing_clone_skips_only_that_repo`
26. `test_record_all_metrics_write_permission_failure_continues` — a real `OSError` from a chmod'd read-only directory (not a mocked side effect), caught, next repo still recorded.

**`check_quality_trends`:**
27. `test_check_quality_trends_core_area_skip_is_red` — a real skip-log entry touching a `config/auto_merge.json`-listed core path → red; an owned-area skip → not red.
28. `test_check_quality_trends_trending_up_is_yellow_real_snapshots` — two real recorded snapshots (test-skips rising, or mutation score falling) → yellow via real `mr.compare`.
29. `test_check_quality_trends_stale_snapshot_is_yellow` — a real snapshot file timestamped 3 days old.
30. `test_check_quality_trends_no_data_yet_is_green_informational`
31. `test_check_quality_trends_one_project_failure_does_not_blank_others` — one project's `mr.latest` raises, asserted present as its own degraded entry; the other project's real entry is unaffected.

**CLI / job wiring:**
32. `test_cli_run_records_a_real_job_events_run` — real `job_events.JOBS_DIR` (tmp path), calls `qt.run()`, reads the job log back and asserts a `"passed"` run with steps (replaces the bare-`pass` test).
33. `test_job_placement_includes_quality_trends_mini` — `health_checks.JOB_PLACEMENT["quality-trends"] == "mini"`.

**`metrics_registry.record` (the one new primitive change):**
34. `test_record_replace_same_day_default_unchanged` — default call still appends (existing callers unaffected).
35. `test_record_replace_same_day_concurrent_stays_valid` — threaded writes with `replace_same_day=True` against a real tmp dir; file stays valid JSON, one entry for the day.

## Acceptance-criteria mapping

- "The four trends visible, both Macs" → `record(..., replace_same_day=True)` writing all four (plus growth sub-fields) into the real per-machine file (test 18), read by the unmodified cross-machine `readHistory`.
- "Yellow/red thresholds as above" → tests 27, 28, 29 against real recorded data, not mocks that bypass the branch under test.
- "Tests first" → all 35 above, each written to fail against the current (buggy) worktree code before any fix lands, each tied to a specific review finding or a gap the review's own fixes newly exposed (the dot-in-subsystem-name violation, the single-huge-leaf-directory hang).

No files have been edited — this is the plan only, ready for the next attempt to implement against.