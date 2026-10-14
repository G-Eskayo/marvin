## North-star fit

**Reuses, verified by reading the code, not the prior doc's claims:**
`lib/cleanup_sweep.py` already has the DI pattern (`list_*`/`is_*`/`remove_*` callables, `_write_log`, per-item try/except), the parent/child `*.code_sign_clone/code_sign_clone.*` glob, `min_age_hours`, the lsof 0/1/else fail-safe, and the per-item recheck — all already written into this worktree (uncommitted). `lib/disk_reclaim.py` already sweeps unavailable simulators (`xcrun simctl`, confirmed by reading it). `sweep_worktrees`/`drop_build_output` already handle worktrees/.build. None of that needs rebuilding — only the test suite covering it is broken.

**What's actually wrong — found by running the tests, not by re-deriving from the prior design doc (which turned out to describe a different, non-existent bug):**

I ran `~/.agents/venv/bin/python -m pytest lib/tests/test_cleanup_sweep.py -q` directly. Result: **9 failed, 37 passed** — matching the metrics exactly (`pytest_failed: 9`, `tests_failed: 9`, everything else unchanged). Root causes, confirmed from the traceback, not guessed:

1. **`test_8`, `test_11` (`TestListCloneDirs`)**: the fixtures build a *flat* `tmp_path/"test.code_sign_clone"` with files directly inside it. The real `_default_list_clone_dirs()` globs `*.code_sign_clone` **parents**, then `code_sign_clone.*` **children** inside each — exactly what the ticket's own pattern (`*.code_sign_clone/code_sign_clone.*`) specifies. A flat fixture has zero matching children, so `_default_list_clone_dirs()` correctly returns `[]`, and the test's `assert len(clones) == 1` (or `clones[0]`) fails. **The implementation is right; the two fixtures are stale**, written before the parent/child correction landed.
2. **`test_18`–`test_24`, 7 tests (`TestFindOrphanedCloneDirs`, `TestSweepOrphanedClones`)**: all call `cs.find_orphaned_clone_dirs(mock_list, mock_in_use)` / `cs.sweep_orphaned_clones(mock_list, mock_in_use, mock_remove)` **positionally**. But both functions' real first parameter is `min_age_hours: float`, not `list_clone_dirs`. So `mock_list_clones` (a function) lands in the `min_age_hours` slot, and `mock_is_in_use` lands in the `list_clone_dirs` slot — then `for clone in list_clone_dirs():` calls `mock_is_in_use()` with no arguments → `TypeError: missing 1 required positional argument: 'path'`. `test_25`/`test_26`, which already pass keyword args (`min_age_hours=1.0, list_clone_dirs=..., is_in_use=...`), are the only ones in that block that pass — confirming the diagnosis. **These are call-site bugs in the test, not the implementation.**

The **previous design doc's analysis of these 9 failures is wrong on inspection** — it blames `monkeypatch.setattr(..., side_effect=...)` misuse and a `path.name`-vs-`path.stem` dict-key bug in `test_23`. I read the actual file: `test_12`/`test_13`/`test_16` already pass plain raising functions to `monkeypatch.setattr` (no `side_effect=` kwarg anywhere), and they already pass. `test_23`'s dict-key mismatch (`path.name` → `"clone1.code_sign_clone"` vs. dict key `"clone1"`) is real, but it's irrelevant to why `test_23` currently fails — it fails at the `list_clone_dirs()` call before the key lookup is ever reached, from the positional-arg bug above. Fixing only the key would still leave it red. **This doc replaces that analysis with the one verified by actually running pytest.**

Separately, I found one more real, unreported correctness gap by reading `cleanup_sweep.py` lines 62–66 and the ticket's "Chrome, Comet and any other app" requirement: `CLONE_SEARCH_ROOTS` reads `os.environ.get('DARWIN_USER_CACHE_DIR')`. That is not a real environment variable macOS sets — it's only obtainable via `getconf DARWIN_USER_CACHE_DIR` / `confstr()`. In any real shell, cron, or launchd context this `.get()` returns `None` silently, so the cache-dir root is **never actually searched** — only `tempfile.gettempdir()` is. This directly undercuts ticket item 3 ("sweep orphans... Chrome, Comet and any other app") if real orphans live under the cache dir rather than temp. Fixing it (via `getconf`, with a fail-safe fallback to just `tempfile.gettempdir()` if `getconf` is unavailable) is a small, concrete, in-scope correctness fix, not scope creep — it's the same subsystem the ticket is about, found the same way (reading the code, not assuming it works).

The **PR-AUDIT-189.md and IMPLEMENTATION-SUMMARY-189.md already in this worktree both assert "all 26 tests pass" and "test 7 confirms zero leaked chromium processes."** Both claims are false on the evidence above — I ran the suite and it isn't 26/26. These files must not ship as-is; they get corrected, not just kept.

**`browser-lifecycle.test.mjs` is still the heavy spawn-based version** the earlier design doc rightly worried about but — per the diffstat and git status — never actually replaced: it spawns `node --test <file>` **7 times** (guards 1–3 once per file, guards 4–6 the same files again, test 7 a third run of `snapshot.test.mjs`), each a full real-Chrome run through `execFileSync(generate.py)` + Playwright page screenshots. That is almost certainly the ticket's own two recorded "timed out after 1200s" comments (one explicitly names bare `pytest -q`; the other is redacted/dotted — structurally this file is the obvious other candidate: it's the only test file that chains multiple full real-browser runs in one process). The ticket's actual wording for item 2 is a **static** property check ("fail if any test launches a browser without an awaited close, or uses `channel: 'chrome'` without that comment") — not a dynamic 7x-rerun. I'll replace it with a fast source-text guard (no browser, no spawn) plus exactly **one** lightweight in-process real-launch+close check, which satisfies the guard's actual purpose without reproducing the demonstrated hang.

**The 3 brain-map test files need no changes.** `snapshot.test.mjs`, `labels.test.mjs`, `code-layer.test.mjs` already use `chromium.launch({ channel: 'chrome' })` with a justifying comment and `after(async () => { await browser?.close() })` — I read all three diffs directly. Ticket item 1 is already done correctly. The prior design doc's plan to "revert a bundled-Chromium swap" describes a state that doesn't exist in this worktree — there is nothing to revert.

**Simplest sufficient approach:** fix the 9 test bugs at their actual, verified cause (stale fixtures + wrong call signature), add the missing adversarial coverage the ticket's own "How we'll try to break it" and the north-star misuse checklist call for, fix the one real `DARWIN_USER_CACHE_DIR` gap, and replace the one test file that's structurally capable of reproducing the 1200s hang. That's a small, targeted diff — smaller than either prior write-up — because most of the actual implementation is already correct.

**Tokens:** spent on one `pytest` run and reading the actual files (cleanup_sweep.py, test file, 3 brain-map diffs, both audit docs) instead of trusting either prior narrative — this is what caught that the previous attempt's own audit doc contains false "all tests pass" claims, which a third blind rewrite would have repeated.

**User capability:** pure infra hygiene, doesn't touch anything Gil interacts with. Test applies: this stops the disk/process hygiene chore and — this time — stops an audit doc from shipping false test-pass claims next to code that demonstrably fails. No decisions needed from Gil.

**Ticket's own stated fit:** none (bug-fix ticket).

## No Decisions needed

One place I'm making a call rather than following the ticket's literal text, so I'll state it instead of guessing silently: the ticket's test list says "running the brain-map suite twice leaves zero new clones." I'm implementing this as one lightweight real-launch-and-close check in the default/fast test path, plus a separately labeled, not-auto-run "full double-run" check that satisfies the literal wording — rather than wiring the literal double-run into the default gate. This isn't a preference call; it's forced by hard evidence already on the ticket (two recorded 1200s timeouts, one explicitly the bare test runner), and Gil's own correction comment already downgraded this from P1 to P3 ("isn't a disk-space fix"), i.e., lower urgency to force the expensive literal form into the automated gate. Documented in the PR, not left as a silent substitution.

## Tests I'll write/fix first

**Fixing the 9 real failures (minimal, targeted):**
1. `test_8`: rebuild the fixture as `tmp_path/"app.code_sign_clone"/"code_sign_clone.1"/file.txt` (parent/child), assert it's found.
2. `test_11`: same parent/child rebuild, files inside the child, assert size sums correctly.
3. `test_18`–`test_24`: fix each call site to pass `list_clone_dirs=`, `is_in_use=`, `remove_clone_dir=` as keywords (matching how `test_25`/`test_26` already do it correctly). Re-verify `test_23`'s dict-key bug (`path.name` vs. `"clone1"`) is also fixed while touching that test, since it's a second latent bug in the same test once the call-site bug no longer masks it.

**Verify-fails-first check:** confirm all 9 are red for the stated reason (not some other reason) before editing, matching the actual pytest traceback already captured above.

**New coverage for the `DARWIN_USER_CACHE_DIR` fix:**
5. A new `_darwin_user_dirs()`-style helper: mock `subprocess.run` for `getconf DARWIN_USER_CACHE_DIR`/`DARWIN_USER_TEMP_DIR` returning real-looking paths → both appear in the search roots alongside `tempfile.gettempdir()`.
6. `getconf` missing/erroring (mocked `FileNotFoundError`/non-zero exit) → falls back to `tempfile.gettempdir()` alone, no crash.

**From the ticket's "How we'll try to break it" (direct):**
7. Sweep never removes a clone a live process has open (already covered: `test_19`, fixed `test_21`/`test_24`).
8. Including one opened between listing and the recheck right before removal (already covered: `test_24`, fixed).
9. Sweep never touches a dir that doesn't match `*.code_sign_clone`/`code_sign_clone.*` (already covered: `test_9`; add: a parent whose child name does **not** match `code_sign_clone.*` is ignored).
10. Sweep never follows or removes a **symlink** named like a clone child (new — not currently tested at all).
11. Sweep never touches a structurally-matching decoy outside the configured `CLONE_SEARCH_ROOTS` ("other users' folders", new).
12. `lsof` unavailable/failing → nothing deleted: `FileNotFoundError` (covered, `test_12`), `TimeoutError` (covered, `test_13`), unexpected exit code e.g. `2` (new — only 0/1 are currently tested explicitly against `_default_is_in_use`'s three-way branch; add the `else` branch), explicit `PermissionError` from `lsof` itself (new).
13. Running the brain-map suite (one pass, all 3 files) leaves zero new clones — implemented as the one lightweight real-launch+close check in `browser-lifecycle.test.mjs`, plus a separate, explicitly-labeled slow/manual double-run script satisfying the literal "twice" wording (per the north-star-fit note above).

**Additional misuse the ticket section didn't spell out, per the north-star checklist:**
14. Empty candidate list → clean no-op (new).
15. `min_age_hours=0` → documented "no filter," doesn't crash (new).
16. Negative `min_age_hours` behaves the same as `0` (new, locks in a reasonable default rather than leaving it unspecified).
17. A clone with a future mtime (clock skew, negative computed age) is never misread as eligible — locks in the existing `age_hours < min_age_hours → skip` behavior as intentional (new).
18. `shutil.rmtree` raises `PermissionError` on one item → that item is reported as a genuine failure, the sweep continues for the rest (covered: `test_16`/`test_22`, keep).
19. The dir **vanishes** between the recheck and the actual `rmtree` call (e.g., a concurrent sweep on the other Mac, or the owning app's own cleanup winning the race) → `shutil.rmtree` raises `FileNotFoundError` → this must be treated as **already gone / success**, not logged as a failure. **This is a real bug in the current `_default_remove_clone_dir`**, which catches bare `Exception` and returns `False` for `FileNotFoundError` exactly like a real permission failure — new test added, implementation fix needed.
20. Running the sweep twice back-to-back is idempotent — second run finds nothing left to remove (new).
21. A `*.code_sign_clone` parent matching a non-Chrome app name (e.g. `com.comet.Browser.code_sign_clone`) is found identically — locks in that the glob is already app-agnostic, per the ticket's "Chrome, Comet and any other app" (new).
22. `_default_list_clone_dirs` raising `OSError`/`PermissionError` mid-walk on one root doesn't abort the whole sweep — other roots still get searched (new, exercises the existing try/except that's currently untested).

**Static guard tests in the rewritten `browser-lifecycle.test.mjs`** (regex over source text, no process spawn, no browser):
23. Flags `after(() => browser?.close())` (unawaited) as a failure.
24. Passes on `after(async () => { await browser?.close() })`.
25. Flags `channel: 'chrome'` with no nearby explanatory comment.
26. Passes when the comment is present (the real files' current state).
27. No false positive on a file with no `.launch(` call at all.
28. No false positive on `.launch(`/`channel: 'chrome'` appearing only inside a comment or string literal.

## Task List

1. Fix `test_8`/`test_11` fixtures in `lib/tests/test_cleanup_sweep.py` to the parent/child structure.
2. Fix the positional→keyword call-site bug in `test_18`–`test_24`; fix `test_23`'s `path.name`/`path.stem` key mismatch while there.
3. Re-run `~/.agents/venv/bin/python -m pytest lib/tests/test_cleanup_sweep.py -q` (never bare `pytest -q`) and confirm 0 failures (currently 9).
4. Replace `CLONE_SEARCH_ROOTS`'s `os.environ.get('DARWIN_USER_CACHE_DIR')` with a `getconf`-based lookup (`DARWIN_USER_CACHE_DIR` and `DARWIN_USER_TEMP_DIR`), falling back to `tempfile.gettempdir()` alone if `getconf` fails or isn't present; add tests 5–6.
5. Fix `_default_remove_clone_dir` to treat `FileNotFoundError` from `shutil.rmtree` as success (already gone), distinct from other exceptions (genuine failure); add test 19.
6. Add new tests 9 (non-matching child name), 10 (symlink), 11 (outside configured roots), 12's unexpected-lsof-code and `lsof` `PermissionError` cases, 14–18, 20–22.
7. Rewrite `brain-map/tests/browser-lifecycle.test.mjs`: replace the 7x spawn-based guards with the static source-text regex guard (tests 23–28) plus one lightweight in-process real-launch+close leak check (test 13's fast half); add a separate, clearly-labeled slow/manual script (not wired into the default gate) for the literal full-suite double-run, documenting why it's kept out of the automated path.
8. Correct `PR-AUDIT-189.md` and `IMPLEMENTATION-SUMMARY-189.md` (or fold their accurate parts into the final PR body and delete them) so they state the real, verified test result instead of the current false "26/26 pass."
9. Delete the stale `docs/design/browser-lifecycle-cleanup-189.md`, `pipeline-g-eskayo-marvin-415.md`, `pipeline-g-eskayo-marvin-415-tasks.md` (superseded by this doc) before opening the PR.
10. Run `node --test brain-map/tests/*.test.mjs` once and `~/.agents/venv/bin/python -m pytest lib/tests/test_cleanup_sweep.py -v` once locally; confirm green; note in the PR that bare full-suite commands (`pytest -q` with no path, or any command chaining multiple real-browser full-suite reruns) are what caused both prior 1200s timeouts on this ticket and must not be used for verification here.
11. Write the PR body's audit section (ticket item 4) using the verified file list already confirmed by reading the code: the 3 brain-map tests (clean), `dashboard/scripts/capture_screenshot.mjs` (clean, `finally`+awaited close), `brain-map/render_map_images.py` (clean, `async with`), `lib/render_diagrams.py`/`lib/portfolio_parity.py`/`lib/portfolio_inventory.py` (bundled Chromium only, mechanism doesn't apply), `tools/browser/browser_ctl.py` (intentional persistent CDP connection, not a leak) — and correct the existing audit docs' unverified claims rather than repeating them.