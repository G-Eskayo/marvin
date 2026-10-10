## North-star fit

**Reuses before adding anything new.** The shape from the prior attempt is sound and stays: one small `claims.py` module writing one JSON ledger, read by `portfolio_content.evaluate()` into the existing `findings` list, zero new dashboard/IPC/UI code (`PortfolioHub.jsx:839` still renders `pg.findings` generically as `{f.rule}: {f.detail}`, and no dashboard code reads `f.section` — reverified by grep just now, not assumed). This attempt fixes five real defects in that shape plus a few directly-adjacent correctness/safety gaps the same code touches — it does not re-architect anything.

**Simplest sufficient approach.** Most of the previous plan's own fixes (gh gate env, word-boundary keyword matching, `flag_for_redraft` stub, injectable `jobs_directory` param on `check_jobs_recent`, the real portfolio-repo scan path, plist/install-script wording) are **already applied in the working tree** — I verified each by reading the current files, not by trusting the old plan's claims. What's left is narrower than the prior task list: the 5 must-fix review findings, plus closing a real test-isolation gap the review didn't name but the ticket's own "tests try to break it" rule requires (see below).

**Where it spends/saves tokens.** Unchanged: nightly job pays the read cost once, dashboard reads a small JSON file. No new spend.

**More capable, not more passive.** Unchanged: surfaces which sentence is no longer backed by reality, for Gil to act on; doesn't silently rewrite copy.

**Correcting the previous attempt's own fit claim:** it asserted `docs/plans/living-marvin-page-2026-10-08.md`'s layer-4 status table "already correctly say[s] 'yes (layer 4, #281)'" for both rows and needed no change. I checked: the "What it can do (use cases)" row now says "yes (layer 4, #281)" but that section (#268) isn't built yet — there is nothing there to truth-check. That's the exact overstatement the review flagged. This row needs correcting; the "Lead, story sections" row is fine (the 4 claims it covers do have real checks now).

**Decisions:** none needed. Every gap found below (visibility-check unknown-vs-false semantics, the dead `jobs_directory`/`ledger_path` params, the missing test-isolation conftest) is a narrow, low-risk engineering call with a stated reason — not a product choice for Gil to pick between.

## What's already fixed (verified by reading current code, not re-touched)

- `check_jobs_recent` already takes `jobs_directory` — only the *tests* still bypass it.
- `check_repo_visibility`'s gh fallback already passes `env=project_catalog.run_env()` (gate dir first on PATH) — fix confirmed in code, just needs its regression test.
- `scan_for_unchecked_claims` already uses word-boundary matching and a pronoun-stripped substring check, and the keyword list already excludes `"works"`/`"uses"`.
- `gather()` already reads `project_catalog.portfolio_repo_path() / "content/longform/marvin.json"` via `portfolio_content._page_html()`, with `scan_error` captured.
- `flag_for_redraft` stub exists and is called once per failed claim in `gather()`.
- `_read_claims_ledger`'s `checked_at` parsing already treats a naive/missing/unparseable timestamp as stale (TypeError/ValueError both caught).
- ADR/plist/install-script already say "local time" and "Mini only" — not UTC, not "install on each machine."
- `lib/health_checks.py`'s `JOB_PLACEMENT["claims-ledger-nightly"] = "mini"` already present and correct.
- `CONTEXT.md`'s claims-ledger glossary entry already uses `section`, not `role`.
- Unused imports (`machine_profile`, `time`, `timedelta`) already gone from `claims.py`.

None of these need re-touching. Re-doing them would be pure waste.

## What's actually broken (the 5 must-fix findings + 2 adjacent gaps in the same code)

1. **`gather()`'s `checked` dict excludes unknown claims** (fix #1) — built from `passed ∪ failed` only, so `_claims_findings` can never resolve a `claim-unknown` finding's `section`.
2. **`TestCheckJobsRecent`'s three tests never call `claims.check_jobs_recent`** (fix #2) — they either reimplement its body inline or just inspect `job_events.status_of` directly.
3. **`TestNightlyIntegration.test_nightly_writes_ledger` never calls anything and asserts nothing** (fix #3) — passes vacuously.
4. **`test_atomic_write_no_half_written` checks the wrong temp-file name and can't fail** (fix #4) — checks `test.json.tmp`; `_atomic_write` uses `path.with_suffix(".tmp")` → `test.tmp`. The scenario it sets up (nonexistent-as-directory parent) also never reaches the failure branch.
5. **`portfolio_content.evaluate()`'s default ledger path reads real `~/.claude/logs/claims-ledger.json`** (fix #5) — any test calling `evaluate()`/`findings_for_evaluation()` with a marvin page and no explicit `ledger_path` touches real HOME state. This is the exact pattern that caused the real `~/.claude/logs` wipe on 2026-10-09 (memory: `claude-logs-wipe-2026-10-09`) — not from this code, but the same category of mistake.
6. **(adjacent, same function as fix #5's regression target, flagged in review notes but not in fix_these) `check_repo_visibility` reads "unknown" as "false"** — a catalog entry with missing/`None` visibility, or *any* nonzero/malformed `gh` response other than the explicit gate-defer code 75, returns `ok: False` ("page lies") instead of `ok: None` ("couldn't tell"). This directly violates the ticket's own required test category — "each dependency failing" — so I'm fixing it alongside fix #5's test additions for that category, not leaving it as a known gap.
7. **(adjacent, not in review at all — found while checking isolation) `brain-map/scripts/test_claims.py` has no `conftest.py`**, unlike `lib/tests/`. `lib/tests/conftest.py` exists specifically because side-effecting code must never touch real `~/.claude` state or real `gh` from a test (its own docstring: "a new call to a side-effecting module can never touch real state"). `brain-map/scripts/` has no equivalent. Any test here that calls `collect()`/`gather()` without mocking every check function will read the real `marvin-network.json`, real `health-status.json`, and — if the real catalog's visibility isn't a clean `PUBLIC` — shell out to the real `gh` with no blocking fake on `PATH`. This is exactly the "a person's mistake" and "wrong permissions/stale state" misuse category the ticket asks for, and it's currently wide open for every future test author in this directory, not just this ticket's own new tests.

## Tests first

Each test below is written **before** its corresponding code fix, per `tdd`.

### New: `brain-map/scripts/conftest.py` (closes gap #7, written first — everything else in this directory should run inside it)
- Autouse fixture: fake `gh` first on `PATH` that writes to a log and exits 1 (mirrors `lib/tests/conftest.py`'s `_no_real_github`) — any accidental real `gh` call fails loud and visibly, not silently against the real account.
- Autouse fixture: `monkeypatch.setattr(job_events, "JOBS_DIR", tmp_path)` so a test that forgets to pass `jobs_directory` can't touch the real `~/.claude/logs/jobs`.

### `brain-map/scripts/test_claims.py`

- **[fix #1 regression]** `test_gather_includes_unknown_claims_in_checked`: monkeypatch all four `check_*` functions on the `claims` module (one returns `{"ok": None, ...}`), call the real `claims.gather(jobs_directory=tmp_path)`, assert the unknown claim's id is present in `result["checked"]` with the right `id`/`section` — this is the shape `portfolio_content._claims_findings` actually depends on, pinned at the producer.
- Regression for the dead params found in gap-adjacent review notes: `test_gather_threads_jobs_directory_into_check_jobs_recent` — put one `never`-run job file in a custom `jobs_directory`, pass it through `gather(jobs_directory=...)` with the other three checks mocked passing, assert the `keeps-working` claim fails (today it silently always uses the default directory regardless of the argument).
- **[fix #2]** `TestCheckJobsRecent`, rewritten to call `claims.check_jobs_recent(jobs_directory=...)` directly: all idle, one failed, one crashed (stuck "running" >30 min via `job_events.CRASHED_AFTER_S`), one never-run, zero jobs discovered, jobs directory missing entirely, and one malformed-JSON file alongside valid ones (skipped, not a crash).
- `TestCheckTwoMachines.test_missing_devices_key`: keep as-is — it already tests the real missing-key branch (`check_two_machines({"other_key": {}})`, not a wrong-shape dict), contrary to the old plan's claim that it needed rewriting. Verified by reading the code: no change needed.
- **[fix #6 adjacent]** `TestCheckRepoVisibility`, extended: a catalog entry with `visibility: null` or the key missing entirely → `ok is None`, not `False`. `subprocess.run` returning a nonzero non-75 exit code (e.g. a network blip, exit 1) → `ok is None`. Malformed JSON from a successful `gh` call → `ok is None`. Existing `PRIVATE`/`INTERNAL`-from-catalog tests keep asserting `ok is False` (those are real, known answers, not failures). This is the regression set for "each dependency failing."
- Existing `test_gh_call_timeout` and `test_gh_malformed_json`: update their assertions from `ok is False` to `ok is None` to match the corrected semantics above.
- **[fix #3]** `TestNightlyIntegration.test_nightly_writes_ledger`, rewritten: refactor `main()` to accept `argv: list[str] | None = None` (currently reads `sys.argv` unconditionally, untestable); call `claims.main(["--nightly", "--ledger-path", str(tmp_ledger), "--jobs-directory", str(tmp_jobs)])` with the four `check_*` functions monkeypatched; assert the ledger file exists with the corrected shape, and `tmp_jobs / "claims-ledger-nightly.json"` was written with `status: "passed"`.
- New: running `--nightly` twice in a row (repeats) leaves one clean, valid ledger (not partially merged with the previous run) and a job-run history of 2 entries, not a corrupted one.
- New: concurrency — two threads calling `_atomic_write` on the same path with different payloads never leave a half-written or mixed-content file; the path always ends up as one complete, valid JSON document (whichever write "wins").
- New: wrong permissions — ledger's parent directory `chmod(0o000)`; `main(["--nightly", ...])` does not raise uncaught out of the CLI, and the job record shows `status: "failed"`, not silently swallowed. (Skipped under root, where permission bits are ignored — `os.geteuid() == 0`.)
- **[fix #4]** `test_atomic_write_no_half_written`, rewritten: `monkeypatch.setattr(Path, "replace", <raises OSError>)` so the failure happens *after* a successful temp-file write (the realistic case), using the correct path `path.with_suffix(".tmp")`; assert the temp file is gone and the `OSError` propagates.
- New: `gather()` when the marvin content file is missing/corrupt — `scan_error` is set, `unchecked == []`, no crash (dependency failing).
- New: a person's mistake — ledger has a `failed` claim id with no matching entry in `CLAIMS` (claim retired since the ledger was last written); `_claims_findings` (tested via the portfolio-content suite) falls back gracefully, never `KeyError`.
- Keep all currently-passing `TestScanForUncheckedClaims`, `TestVisibleText`, `TestCollect` cases as-is — verified correct against the current code, not stale.

### `lib/tests/conftest.py` (closes gap #5, written first)
- New autouse fixture `_isolate_claims_ledger`: `monkeypatch.setattr(portfolio_content, "CLAIMS_LEDGER_PATH", tmp_path_factory.mktemp("claims-ledger") / "claims-ledger.json")`, mirroring the existing `_isolate_job_events`/`_isolate_launch_log`/`_isolate_board_registry` fixtures already in this file for the identical reason stated in its own module docstring.

### `lib/tests/test_portfolio_content.py`

- **[fix #5]** All 6 existing claims-ledger tests rewritten to **stop mocking `_read_claims_ledger`**: write a real ledger JSON file to `tmp_path` and call `pc.evaluate(tmp_path, ledger_path=ledger_file)`, exercising the real reader end to end — including its staleness/parsing logic, which the mock previously hid entirely.
- New: a test that calls `pc.evaluate(tmp_path)` **with a marvin page and no `ledger_path` argument at all** (the exact scenario the review warned about) and asserts it does not raise and does not require any real file on disk — proving the conftest isolation actually works, not just that explicit calls are safe.
- **[fix #1, consumer side]** `test_marvin_page_with_unknown_claim_adds_finding`, rewritten: build its ledger fixture's `checked` dict using the real shape (`checked` ⊇ `unknown` ∪ `failed` ∪ passed, matching what `claims.gather()` now actually writes, pinned by the producer-side test above) instead of hand-building a `checked` that happens to include the unknown claim; assert the resulting `claim-unknown` finding's `section` is correct — this would have caught the original bug, the hand-built fixture would not.
- Kept: missing-ledger, stale-ledger, unchecked-sentence, non-marvin-page-unaffected cases — logic unchanged, now driven through the real reader per fix #5.

## Decisions

None. (No `<!-- marvin:decisions -->` block — every open question above resolved to a stated engineering call, not an owner choice.)

## Task List

1. `lib/portfolio_content.py`: add module-level `CLAIMS_LEDGER_PATH = Path.home() / ".claude" / "logs" / "claims-ledger.json"` (matching the `HOME`-constant convention in `health_checks.py`/`job_events.py`); change `_read_claims_ledger`'s default to `ledger_path or CLAIMS_LEDGER_PATH`.
2. `lib/tests/conftest.py`: add the `_isolate_claims_ledger` autouse fixture (write this and its test first, per tdd).
3. `lib/tests/test_portfolio_content.py`: rewrite the 6 claims-ledger tests to use real ledger files + explicit `ledger_path`, not a mocked `_read_claims_ledger`; add the no-explicit-path safety test; rewrite the unknown-claim test's fixture to the real `checked` shape.
4. `brain-map/scripts/conftest.py` (new file): fake-`gh`-on-`PATH` autouse fixture + `job_events.JOBS_DIR` isolation autouse fixture.
5. `brain-map/scripts/claims.py`:
   - `gather()`: fix `checked` to include unknown claims (iterate `results.keys()`, not `passed.keys() + failed.keys()`); drop the dead, unused `claims` key from its return dict; drop the dead `ledger_path` parameter (never read inside the function); thread `jobs_directory` into `collect()` so `--jobs-directory` actually affects `check_jobs_recent`.
   - `collect()`: accept an optional `jobs_directory` param, pass it to `check_jobs_recent` when the claim being checked is `check_jobs_recent`.
   - `check_repo_visibility()`: a catalog entry with missing/`None` visibility → `ok: None` (not `False`); any `gh` exit code other than 0 (success) or 75 (gate-defer) → `ok: None`; malformed JSON from a successful `gh` call → `ok: None`. Only an explicit non-`PUBLIC` value (from catalog or a clean `gh` response) stays `ok: False`.
   - `main()`: accept `argv: list[str] | None = None`, pass to `parser.parse_args(argv)`; stop passing the now-removed `ledger_path` into `gather()` (still passed to `_atomic_write` directly, unchanged).
6. `brain-map/scripts/test_claims.py`: write all tests from the "Tests first" section above (steps 4–5's regression tests included), before considering steps 4–5 done.
7. `docs/plans/living-marvin-page-2026-10-08.md`: revert the "What it can do (use cases)" row's "True" column from "yes (layer 4, #281)" back to "layer 4" (not yet — #268 isn't built, nothing to truth-check there). Leave the "Lead, story sections" row as "yes (layer 4, #281)" — that one is accurate.
8. Run the full pytest suite (`lib/tests/` and `brain-map/scripts/`) and vitest (confirming no dashboard files are touched, which they shouldn't be); run `graphify update .` to pick up the corrected modules.

Deliberately out of scope, unchanged from the prior attempt's own (still-valid) call: `install-claims-ledger-job.sh`'s `hostname -s` fallback and its no-`bootout`-on-reload behavior are copied from the already-shipped `install-snapshot-jobs.sh`; fixing only this copy would create inconsistency, not close a gap.