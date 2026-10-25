## North-star fit

The ticket's own stated fit (reuse `session_work.py`'s existing live-session list instead of a new lock file) still checks out against the code — that part doesn't need correcting. What's wrong is in the implementation, not the design: `_live_edit_lease` (lib/code_sync.py:207-237) reuses the right data but reimplements its filtering with two gaps the review caught — no per-file staleness check, and no fail-open guard around anything past `load_state()`. Both gaps live in code that *duplicates* logic `session_work.py` should own (it already owns `LIVE_S`, the session/file shape, and the fail-open contract for reading it — `overlaps()` at session_work.py:82 does almost this same filtering for a different caller, `pre_edit()`).

**Revised fit:** fix both defects by moving the live-edit query itself into `session_work.py` as a new, correctly-scoped function, rather than patching two separate guards into `code_sync.py`'s copy. This reuses the existing state format, `LIVE_S`, and `_k()` (removing the reviewer-flagged private reach-in from outside the module) instead of adding a second place that has to get the fail-open contract right. It does **not** reuse `overlaps()` directly — that function has the identical missing-per-file-timestamp gap, but it backs `pre_edit()`'s pause feature with its own passing test suite; changing its semantics to fix this ticket would risk a regression in a feature nobody reported broken. A new, narrowly-scoped sibling function is the simpler, lower-risk fix than either duplicating the bug or silently changing shared behavior.

Token cost: small, fixed — relocating ~15 lines, adding the one missing per-file check, wrapping one try/except, and a defensive-input test matrix that's cheaper to run as plain dict tests in `test_session_work.py` than as new git-repo integration tests. Spends this once to close a real "cron sync crashes" risk and a real "sync deferred forever" risk — both worse than the ticket's original bug in a different way (silent indefinite stall vs. one bad commit). Leaves Gil strictly more free to work in `~/.agents` without the sync silently jamming or quietly never catching up; no new abstraction beyond what the bug requires.

## Files already read (this pass)

`gh issue view 380` (+ zero comments), `lib/code_sync.py` (full, current state — the prior attempt's code is already sitting here uncommitted), `lib/session_work.py` (full), `lib/tests/test_code_sync_push.py` (full), `lib/tests/test_code_sync_pull.py` (full), `lib/tests/test_session_work.py` (relevant sections + confirmed `load_state` tests already present and correct), `lib/tests/conftest.py` (full — confirms the per-module autouse-isolation-fixture convention), `docs/adr/0065-code-sync-waits-on-a-live-edit-lease.md` (full), `docs/design/pipeline-g-eskayo-marvin-380.md` (full — the prior design doc), `docs/agents/decisions-format.md`, `CONTEXT.md`'s Code sync section + confirmed the "Edit lease" bullet is already in place, `docs/adr/0001-*.md`'s title (confirmed it's about the voice client SDK, unrelated to "split-queue escalation").

**State of the branch:** `session_work.py`'s `load_state()` extraction and its tests are already correct and complete — the review raised no findings against that file. Everything below is scoped to `lib/code_sync.py` and its two test files, plus one doc fix.

## What to build

**1. `lib/session_work.py` — new function, replacing `code_sync._live_edit_lease`'s inline loop:**

```python
def live_edits_for(repo_id: str, paths: list[str], now: float | None = None) -> list[dict]:
    """Live (<= LIVE_S) sessions with a recorded edit to repo_id+path, for any path in `paths`.
    Fails open per session: a malformed entry is skipped, never raised — one broken session
    must never hide a real lease held by another, and must never crash the caller."""
    now = now if now is not None else time.time()
    st = load_state()
    out = []
    for sid, s in (st.get("sessions") or {}).items():
        try:
            if now - s.get("last", 0) > LIVE_S:
                continue
            files = s.get("files") or {}
            for p in paths:
                ts = files.get(_k((repo_id, p)))
                if ts is None or now - ts > LIVE_S:
                    continue
                out.append({"session": sid, "path": p, "edited_at": ts,
                            "request": (s.get("request") or "").strip() if isinstance(s.get("request") or "", str) else ""})
        except Exception:
            continue
    return out
```

This directly fixes **must-fix #1** (`ts is None or now - ts > LIVE_S` — the per-file timestamp the design/ADR require) and **must-fix #2** (the whole per-session body is inside `try/except Exception: continue` — a non-dict session, a `null` request, a non-numeric `last` or file timestamp all just drop that one session from consideration instead of raising into the caller; a well-formed sibling session is still correctly checked, so a bad entry can never *hide* a real lease either — only `load_state()`'s existing top-level fail-open can produce a false "no lease anywhere").

**2. `lib/code_sync.py` — `_live_edit_lease` shrinks to formatting + the repo-id lookup:**

```python
def _live_edit_lease(repo: Path, changed_files: list[str], now: float | None = None) -> str | None:
    if not changed_files:
        return None
    now = now if now is not None else time.time()
    try:
        repo_id, _ = session_work.file_key(str(repo / changed_files[0]))
    except Exception:
        return None
    if repo_id is None:
        return None
    edits = session_work.live_edits_for(repo_id, changed_files, now)
    if not edits:
        return None
    e = edits[0]
    minutes_ago = int((now - e["edited_at"]) / 60)
    request_desc = f', working on: "{e["request"]}"' if e["request"] else ""
    return f'file {e["path"]} edited {minutes_ago} min ago by session {e["session"][:8]}{request_desc}'
```

Call site in `push()` (code_sync.py:419-422) is unchanged. No `notify()` — unchanged rationale (expected, self-resolving, not a conflict).

**3. `lib/tests/test_session_work.py` — new unit tests for `live_edits_for`** (the right place for the input-shape matrix — plain dicts, no git/tmp-repo overhead):
- matching edit returns when both session `last` and the file's own timestamp are within `LIVE_S`
- **regression test for must-fix #1:** session `last` is fresh (session is still "live", working on something else) but *this file's* recorded timestamp is older than `LIVE_S` → returns `[]`. This is the literal bug: a session that touched `file.md` hours ago but is still active elsewhere must not hold the lease forever.
- **regression tests for must-fix #2**, one per shape the review named, each proving `live_edits_for` returns `[]` (not an exception) and a *different*, well-formed session's real lease still comes through:
  - a session value that isn't a dict
  - `"request": null"` with otherwise-valid `last`/`files`
  - a non-numeric `last`
  - a non-numeric file timestamp
- two live sessions each with a fresh edit to the same path → both appear in the result (keeps the "two concurrent sessions" acceptance case meaningful at the unit level, not just end-to-end)

**4. `lib/tests/test_code_sync_push.py` — fix the two flagged tests, keep the rest as integration-level proof the wiring works:**

- **`test_missing_or_corrupt_sessions_state_never_blocks_push`** (must-fix #3): parametrize over three state-file shapes — missing file, invalid JSON text (`"{not json"`), and valid-JSON-but-non-dict (`"[1, 2, 3]"`) — each run through `cs.push()`, each asserting the commit lands (not just that it doesn't crash).
- **`test_push_is_not_blocked_by_a_same_path_edit_in_a_sibling_worktree`** (must-fix #4): rewritten to actually create a sibling worktree and use `sw.file_key()`, not hand-rolled `git rev-parse --git-dir`:
  ```python
  clone = _make_origin_and_clone(tmp_path)
  sibling = tmp_path / "sibling-worktree"
  subprocess.run(["git", "worktree", "add", str(sibling), "-b", "sibling"], cwd=clone, check=True, capture_output=True)
  repo_id, relpath = sw.file_key(str(sibling / "file.md"))   # proves same repo-id as clone's own file.md
  # lease recorded against repo_id + relpath, as if the sibling worktree's own session touched it
  ...
  (clone / "other.txt").write_text("new content\n")   # dirty file in *this* clone is unrelated
  cs.push(clone)
  # clone's file.md itself stays untouched/clean — the lease must not block what *is* dirty here
  ```
  This proves the actual regression: same repo-id (via a real worktree, via the real key function — can't pass vacuously), file not among this push's own dirty files → push proceeds.
- small cleanup, same file: point `LOG_PATH` for the idempotency test (currently `clone / "sync-log.md"`, line 146) at `tmp_path / "sync-log.md"` instead, matching every other test in the file — removes the self-dirtying fragility the review flagged as a note, at zero behavior cost.

**5. `lib/tests/test_code_sync_pull.py` — small cleanup (reviewer note, not must-fix):**
- `LOG_PATH` at line 202 moved outside `clone_a`, same reasoning as above.
- `pull_ok` (line 233) is dead — either assert it (`assert pull_ok`) or delete the line; deleting it since it duplicates what the real assertion on `status_b` already proves.

**6. `lib/tests/conftest.py` — one new autouse fixture**, following this file's own established per-module isolation pattern (`_isolate_job_events`, `_isolate_launch_log`, etc.):
  ```python
  @pytest.fixture(autouse=True)
  def _isolate_session_work_state(tmp_path_factory, monkeypatch):
      # push()/pull() tests that don't explicitly set up a lease must never read the real
      # ~/.claude/logs/sessions-active.json; a stray real session could change their outcome.
      import session_work
      monkeypatch.setattr(session_work, "STATE_PATH", tmp_path_factory.mktemp("sessions") / "sessions-active.json")
  ```
  Tests that need specific lease content still call `monkeypatch.setattr(cs.session_work, "STATE_PATH", state_file)` explicitly afterward, which simply overrides the autouse default — no conflict, no test changes required beyond this one new fixture.

**7. `docs/adr/0065-code-sync-waits-on-a-live-edit-lease.md` — two factual fixes:**
- Context section currently says both "propagated to the other machine" and "discovered in tests (not in production)" — these contradict each other, and the ticket itself says the owner *noticed* the real auto-sync commit (5c7cf79), i.e. it was a real production event, not something caught in a test run. Rewrite to match the ticket: discovered when the owner noticed the auto-sync had committed in-progress work; it happened to pass its tests, which is *why* a test gate (option 3) wouldn't have caught it.
- Remove the "ADR 0001 (split-queue escalation)" reference — ADR 0001 in this repo is "Agent SDK over Remote Control for voice client," unrelated; no split-queue-escalation ADR exists. Drop the sentence rather than inventing a citation.

## Decisions

None. Nothing above is a matter of Gil's taste or an irreversible fork — relocating the buggy logic into `session_work.py` is a correctness fix justified by the review itself (must-fix #1/#2 plus the "private reach-in" note), not a design alternative needing his input.

## Tests to write first

From the ticket's "How we'll try to break it" (already covered by existing, unchanged tests — re-verified against the current code, not rewritten):
1. Builder crashes holding the lease → `test_push_proceeds_once_the_lease_goes_stale` (unchanged, still correct).
2. Two sessions editing at once → `test_two_concurrent_live_sessions_both_hold_the_lease` (unchanged) + new unit case in `live_edits_for`'s tests.
3. Sync on the other Mac pulling mid-edit → `test_pull_on_another_machine_is_unaffected_while_push_elsewhere_is_deferred` (unchanged).

Direct acceptance-criteria tests (unchanged, still pass against the relocated logic): `test_push_defers_when_a_live_session_is_mid_edit_on_a_dirty_file`, `test_push_defers_is_idempotent_on_repeated_calls`.

New, to close this review's findings:
4. `test_push_proceeds_when_the_session_is_live_but_this_files_edit_is_stale` (session_work-level, kills must-fix #1).
5. Four malformed-session-shape tests in `test_session_work.py` (kills must-fix #2): non-dict session value, null request, non-numeric `last`, non-numeric file timestamp — each proving fail-open *and* that a sibling well-formed session's real lease still comes through.
6. `test_missing_or_corrupt_sessions_state_never_blocks_push`, parametrized over missing/corrupt/non-dict, run through `cs.push()` (kills must-fix #3 — proves the top-level fail-open end-to-end, not just at the unit level).
7. Rewritten `test_push_is_not_blocked_by_a_same_path_edit_in_a_sibling_worktree`, using a real `git worktree add` and `sw.file_key()` (kills must-fix #4 — the test can no longer pass vacuously).

Misuse the ticket's section didn't list, already covered and kept as-is: `test_push_is_not_blocked_by_an_unrelated_files_lease`, `test_push_is_not_blocked_by_a_lease_in_a_different_repo`.

Verify fails if `code_sync.py`/`session_work.py` change without a matching test changing (`lib/commit_check.py`, ADR 0063) — every test above uses real temp git repos or the real `session_work` data shape, no mocks of `git` or of the state file's semantics.