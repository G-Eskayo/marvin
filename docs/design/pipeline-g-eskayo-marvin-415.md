Write access is blocked in this planning step, so here's the full design doc as my response output.

## North-star fit

**Reuses before adding anything:** `relocate_project.open_by()`'s proven one-shot, system-wide `/usr/sbin/lsof -n -P +c 0 -F cn` call and its prefix-matching parse loop — the exact mechanism that catches a process holding a file *inside* a directory open, not just the directory handle itself. The current `lib/clone_sweep.py` in this worktree calls `lsof <dir>` directly (no `+c 0 -F cn`, no prefix match), which is why the last review caught it missing opens on files inside the clone. Also reuses `disk_trim._get_size_kb()` (currently duplicated a third time in `clone_sweep.py`), `readable_guard.py`'s regex-over-source-text shape for the new JS guard, and `cleanup_sweep.run_daily_sweep()`'s existing try/except + `_write_log` wiring for clone sweep results (both already correct in this worktree and untouched by this revision).

**Simplest sufficient approach:** fix exactly what review found broken, nothing more. The target is `*.code_sign_clone/code_sign_clone.*` under `getconf DARWIN_USER_TEMP_DIR`/`DARWIN_USER_CACHE_DIR` for the current user — the ticket's literal spec. The code in this worktree right now globs `~/.agents-pipeline-worktrees` for directories containing `.git/`, which is a **different subsystem's** cleanup target that happens to share a filename pattern. That's the root must-fix: the module solves the wrong problem. `_darwin_user_roots()` already exists and already calls `getconf` correctly — it's just never called by `_default_list_clones()`. The fix is to wire it in, not redesign it.

**Where it spends/saves tokens:** one rewrite of `lib/clone_sweep.py` (~110 lines), one rewrite of `lib/browser_close_guard.py` (~70 lines), two rewritten test files. `cleanup_sweep.py`, `conftest.py`, `test_cleanup_sweep.py`, and the launchd plist comment are already correct in this worktree (verified by reading all four) and are **not touched** — the smallest footprint that closes every must-fix finding. Two new tests spawn a real subprocess and a real `lsof` call (bounded to ~5s each) because every previous test mocked `subprocess.run`, which is exactly what let the broken invocation ship twice.

**User impact:** invisible infra hygiene — replaces Gil manually deleting orphaned clones with a correct, logged, automatic sweep, and stops the brain-map suite from creating new leaks at all. No capability or judgment removed from him.

**Correcting the ticket's own framing against the code:** comment 3 on the issue already downgraded this from a disk-space fix to a hygiene fix (the clones are APFS copy-on-write, freeing ~0 GB) — p1 → p3, confirmed by Gil's own measurement, and that correction is accurate and already reflected in the ticket's labels. What's inaccurate is upstream of the ticket: the code in this worktree doesn't implement what the ticket (or the prior design doc describing it) says it does. This plan fixes the implementation to match the ticket, not the framing.

---

## Decisions

None required. Every open point has a clear right answer from evidence already in hand, not a product/UX choice:

- **Target shape** — `*.code_sign_clone/code_sign_clone.*`, exactly per the ticket's "What" §3.
- **Whether to touch `cleanup_sweep.py`/`conftest.py`/`test_cleanup_sweep.py`/the plist** — no. Confirmed by reading all four: `conftest.py:81` already stubs `clone_sweep.sweep_clones`, `cleanup_sweep.py:319-323` already wraps `clone_sweep.sweep_clones()` in try/except and folds results into the one `_write_log` block, and the plist comment already describes the three-part sweep. Only `lib/clone_sweep.py`, `lib/browser_close_guard.py`, and their test files are wrong.
- **Whether to touch `brain-map/tests/{snapshot,labels,code-layer}.test.mjs`** — no. Already correctly fixed in this worktree: bundled Chromium (`chromium.launch()`, no `channel`) and `after(async () => { await browser?.close() })`. Confirmed by reading and diffing all three against HEAD.
- **Reuse `relocate_project.open_by()` directly, or re-implement its invocation?** — re-implement the *invocation and parsing*, not call the function. `open_by()` catches `(OSError, TimeoutExpired)` and returns `[]` on failure, conflating "nothing has it open" with "lsof is broken" — exactly the distinction the ticket's 4th adversarial test requires (lsof unavailable/failing ⇒ nothing deleted). Calling `open_by()` as-is would silently delete on an lsof failure. `clone_sweep._default_is_open()` uses the same call/parse shape but returns `None` on failure.

---

## Tests to write first

All in `lib/tests/test_clone_sweep.py` / `lib/tests/test_browser_close_guard.py` unless noted. Real collaborators (`/usr/sbin/lsof`, a real child process, the real filesystem) used wherever a mock would hide the exact bug the last review found; mocks remain only for the two unmockable failure modes (binary missing, timeout).

**Ticket's adversarial tests, plus the real-collaborator version that would have caught the regressions:**

1. `_default_is_open()` against **real** `lsof`: spawn a real child process holding a file *inside* a fake `.../x.code_sign_clone/code_sign_clone.1/payload.bin` (not the directory path itself) open, poll for up to 5s, assert it becomes `True`. Fails against the current worktree implementation (misses opens on files inside the dir), passes against the rewrite.
2. Kill that process, poll for up to 5s, assert it becomes `False` — bounded, not a hang (regression test for the old long-timeout failure mode).
3. End-to-end with the real default `is_open`: one real open clone and one real closed clone, both through `find_orphan_clones()` with no injected fakes — only the closed one comes back.
4. TOCTOU: injected `is_open` fake reports closed on listing, open on immediate re-check — never removed.
5. Real symlink `evil.code_sign_clone/code_sign_clone.1` → an unrelated real dir with a marker file, found via a real `_default_list_clones()` scan — rejected, marker file untouched.
6. `_darwin_user_roots()` is actually consulted: monkeypatch it to a fake root, create one matching clone inside it and one identically-shaped clone outside it (directly under `tmp_path`) — only the inside one is found. Regression test for "defined but never called": fails against current code, passes against the rewrite.
7. A git-worktree-clone-shaped path (`.git/`, under a fake `.agents-pipeline-worktrees` root) handed to `_looks_like_clone` directly — rejected. Regression test for the wrong-target bug.
8. A path that doesn't match `*.code_sign_clone/code_sign_clone.*` (wrong parent suffix, wrong entry prefix, independently) handed directly to `_looks_like_clone` — rejected.
9. "Running the brain-map suite twice leaves zero new clones" approximated as a bounded, skip-if-missing smoke test: launch/close (awaited) Python `playwright`'s bundled Chromium twice, diff `*.code_sign_clone` entries under the real roots before/after — expect none. The literal three-file Node suite run stays a documented manual check (task 8), since it also exercises the Node side.
10. `lsof` binary missing (`FileNotFoundError`) and timing out (`TimeoutExpired`) — both make `_default_is_open` return `None`; `find_orphan_clones` removes nothing. Stay mocked (no other way to simulate).

**Misuse the ticket's list didn't name:**

11. Empty input: both `getconf` calls fail → `_darwin_user_roots()` returns `set()`, `_default_list_clones()` returns `[]`, no crash.
12. Huge input: 30+ fake entries (mixed open/closed/old/young/symlink/wrong-shape) — all classified correctly in one call, none dropped, none crash the batch.
13. A root whose `glob()` raises `PermissionError` among several roots — that root is skipped, the other root's clones still found.
14. A clone whose `stat()`/`lstat()` raises `FileNotFoundError` between listing and the age check (one entry among several) — skipped, others still returned.
15. An injected `is_open` that *raises* for one entry among several — skipped, others still correct.
16. `shutil.rmtree`/`unlink` raises `PermissionError` on one entry among several — recorded with `"error"`, rest still removed, call doesn't raise.
17. `shutil.rmtree`/`unlink` raises `FileNotFoundError` (already gone) — treated as already-gone, not an error.
18. Repeats: `find_orphan_clones()` then `sweep_clones()` again on the same now-empty roots returns `[]` both times — idempotent.
19. A plain file (not a directory) directly under a `*.code_sign_clone` parent — rejected by the shape check before `_get_size_kb`/`shutil.rmtree` ever touch it.
20. Extend the existing "no unbounded waits" source-scan test to also cover `_default_is_open`, so this doesn't regress into the prior 1200s verification timeouts.

**Guard tests** — fully replacing `lib/tests/test_browser_close_guard.py`:

21. `name = await x.launch(...)` with `await name?.close()` anywhere later in the file (including a separate `after()` block several lines down, matching the real brain-map shape) → not flagged. Regression test for the "outside the `range(i, i+5)` window" bug.
22. Same shape but `after(() => name?.close())` — not awaited → flagged. Regression test for "any `close()` within the next 4 lines passes."
23. `name.close()` exists but never preceded anywhere by `await name` → flagged.
24. No `.close()` call for `name` anywhere → flagged.
25. `.launch(` result never assigned to a variable → flagged as its own violation ("can never be closed").
26. `try { name = await x.launch() } finally { await name.close() }` (real JS, not Python) → not flagged, with no special-cased context-manager branch needed.
27. A commented-out `.launch(` line → not flagged at all (comments stripped before the scan); `width:`/`withCredentials:` near a launch/channel line never trip anything (no more bare `"with" in line` substring check).
28. `channel: 'chrome'` with a `//` comment same-line or next-line → accepted; with none → flagged; a fully-commented-out `channel:` line isn't re-flagged.
29. `check_repo()` against the **real repo root** → zero violations. Fails against the current guard (flags the already-fixed brain-map files), passes against the rewrite — the regression test that matters most.
30. `__main__` via `runpy.run_path(..., run_name="__main__")` on a clean `tmp_path` repo → `SystemExit(0)`, `✓` captured via `capsys` — replacing the tautological old assertion.
31. Same via `runpy` on a violating `tmp_path` repo → `SystemExit(1)`, violation text in stdout.

**Dropped from the prior test file:** the two tests feeding Python `async with`/`finally:` syntax into a `.mjs`-file checker — replaced by #26 (real JS `try/finally`) and made unnecessary by the variable-tracking design.

---

## Task List

1. Rewrite `lib/clone_sweep.py`: accurate docstring (`*.code_sign_clone/code_sign_clone.*`, not git-worktree clones); `CLONE_PARENT_GLOB = "*.code_sign_clone"`, `CLONE_ENTRY_GLOB = "code_sign_clone.*"`; `_looks_like_clone()` rejects symlinks first, then checks parent-suffix + entry-prefix; `_default_list_clones()` iterates `_darwin_user_roots()` (now actually called), glob two levels deep, per-root and per-entry exception isolation; `_default_is_open()` using the one-shot system-wide `lsof -n -P +c 0 -F cn` call with prefix matching (`True`/`False`/`None`, `None` on `OSError`/`TimeoutExpired`); `find_orphan_clones()`/`sweep_clones()` keep their existing age-filter/fail-closed-recheck/per-entry-isolation logic over the corrected shape; `from disk_trim import _get_size_kb` instead of a third duplicate; `__main__` unchanged.
2. Rewrite `lib/browser_close_guard.py`: comment-stripping helper for the launch/close scan only; `LAUNCH_RE` captures the assigned variable name; for each match, check for any later `{name}.close(` and specifically an awaited one, flagging "no close found" vs. "found but not awaited"; flag any bare unassigned `.launch(`; channel-chrome check kept on original (non-stripped) lines, skips whole-line comments, fixes the missing `f`-string prefix; `__main__` uses `sys.exit()` not `exit()`.
3. Rewrite `lib/tests/test_clone_sweep.py` covering items 1–20 above.
4. Rewrite `lib/tests/test_browser_close_guard.py` covering items 21–31 above.
5. Re-run `lib/tests/test_cleanup_sweep.py` and the `conftest.py` fixture by eye against the new `clone_sweep.py` surface (no edits expected there — confirmed correct in this plan); fix forward immediately if the rewrite exposes any mismatch (e.g. an import-time issue from the new `disk_trim` import).
6. Leave `brain-map/tests/{snapshot,labels,code-layer}.test.mjs` untouched — already correct.
7. Audit pass per ticket item 4 ("cleaning up after ourselves, generally"): check Xcode DerivedData/simulators, pytest temp dirs, worktree/`.build` handling for the same leak-on-kill pattern; record findings in the PR description, no code change unless a real leak is found.
8. Manually run the three brain-map test files twice via `node --test`, diff the real `code_sign_clone` entry count under `DARWIN_USER_TEMP_DIR`/`DARWIN_USER_CACHE_DIR` before/after, paste counts into the PR — the ticket's own literal acceptance test.
9. Run the full `lib/tests` suite locally and confirm the new real-collaborator tests stay bounded (≤ ~15s added wall-clock) so this doesn't repeat the prior two 1200s verification timeouts.