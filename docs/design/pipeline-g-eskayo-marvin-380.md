## North-star fit

The ticket's own fit still holds, and the previous attempt's correction of it also still holds — no further correction needed. Reusing `session_work.py`'s live-session list (`live_edits_for`) instead of a new lock file is right, and it's already built that way: `session_work.py:175-205` has the per-file staleness check and per-session fail-open try/except, `code_sync.py:330-350` calls it with an injectable `now`, and `conftest.py:140-144` isolates the real state file. I read all four files fresh — none of that needs touching.

What's left is exactly one test. Code review's `fix_these` names a single item: `test_pull_is_unaffected_by_a_live_edit_lease_on_a_dirty_file` claims pull "still stashes/merges/pops normally" mid-edit, but the test never gives origin a new commit, so `pull()` has nothing to merge — the "other Mac pulling mid-edit" break-it case from the ticket is asserted but never actually exercised. Everything else the reviewer flagged (`code_sync.py:339/341/343`, `session_work.py:181/196`, the design doc's self-contradicting completion claims) was filed as a **note**, not a must-fix — the prior attempt explicitly deferred those as a judgment call, and the review didn't object to that call. Reopening them now would be scope creep the review didn't ask for.

Token cost: minimal — one test rewritten, zero production code touched. This is cheaper than the last attempt's framing suggested, because the last attempt already paid the real cost (threading `now` through `push()`, rewriting the lease-timing tests, splitting the malformed-state tests). Spending a few more lines here closes the one gap that caused a full extra review-and-retry cycle — a test that read as proof but asserted nothing about the scenario it claimed to cover. Leaves Gil more free: the specific break-it case from the ticket ("sync on the other Mac pulling mid-edit") now has a test that would actually fail if `pull()` regressed, instead of one that passes regardless.

## Files read this pass

Issue #380 (full body + all 5 comments — four are automated "did not pass verification" notices plus one park notice; no human prose feedback beyond the structured review already in this prompt), `lib/code_sync.py` (full, current), `lib/session_work.py` (full, current), `lib/tests/test_code_sync_live_edit_lease.py` (full, current — confirms the prior attempt's production-code and test changes are already sitting in this worktree, uncommitted, matching `git status`), `lib/tests/conftest.py` (full, confirms `_isolate_session_work_state` is in place), `docs/adr/` listing (through 0064 — no 0065, confirming the design doc's ADR-citation note from last round is moot since no such doc was ever created), `CONTEXT.md` (grepped for "lease"/"code-sync" — no mention of the edit lease yet, consistent with the prior decision not to promote this to CONTEXT.md/ADR for a bug fix).

**Current state of the branch:** everything from the prior attempt's "Implementation Complete" section is real and present — `push(repo, now=None)`, the rewritten lease-timing tests with injected `now`, the stale-lease test asserting actual git state, the permissions test with the root skip-guard, the split malformed-state tests. The only thing not yet done is the one must-fix.

## What to build

**`lib/tests/test_code_sync_live_edit_lease.py` — rewrite `test_pull_is_unaffected_by_a_live_edit_lease_on_a_dirty_file` so it actually forces a merge:**

The current test only dirties `file.md` locally and calls `cs.pull(clone)` — origin never gets a new commit, so `_merge_remote` is a no-op fast-forward-to-self, `pull()` never stashes, and the assertion (`file.md` content unchanged) would hold even if stash/pop were deleted from the function entirely. That's the exact failure mode the review named.

Fix: push a real commit to origin from a second clone (simulating the other Mac) before calling `cs.pull(clone)`, then assert on both halves of the scenario — the remote change lands, and the local dirty content survives:

```python
def test_pull_merges_a_remote_commit_while_local_dirty_content_survives_under_a_live_edit_lease(
    tmp_path, monkeypatch
):
    """Sync on the other Mac pulling mid-edit: a second clone pushes a real commit to origin
    while this clone has local dirty content (under an active edit lease elsewhere). pull()
    must stash, merge the real remote commit, and pop — landing the remote change AND
    preserving the local in-progress edit without ever committing it."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)

    clone = _make_origin_and_clone(tmp_path)
    origin = clone.parent / "origin.git"
    repo_id, _ = sw.file_key(str(clone / "file.md"))

    with sw._Locked() as st:
        sw.record_prompt(st, "sess-A", "editing", T)
        sw.record_edit(st, "sess-A", (repo_id, "file.md"), T)

    # The "other Mac": a second clone commits + pushes a real, unrelated change to origin.
    other = tmp_path / "other-clone"
    subprocess.run(["git", "clone", str(origin), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "Test")
    (other / "remote-change.txt").write_text("from the other Mac\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "other Mac's commit")
    _git(other, "push", "origin", "main")

    before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone,
                                  capture_output=True, text=True).stdout.strip()

    (clone / "file.md").write_text("local dirty\n")
    original_content = (clone / "file.md").read_text()

    cs.pull(clone)

    after_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone,
                                 capture_output=True, text=True).stdout.strip()
    origin_head = subprocess.run(["git", "rev-parse", "main"], cwd=origin,
                                  capture_output=True, text=True).stdout.strip()

    assert after_head != before_head, "pull() should have merged the remote's new commit"
    assert after_head == origin_head, "clone should now match origin's HEAD"
    assert (clone / "remote-change.txt").exists(), "the other Mac's commit should have landed"
    assert (clone / "file.md").read_text() == original_content, \
        "local mid-edit content must survive the stash/merge/pop cycle"
    assert _git_status(clone).strip(), \
        "file.md should still be dirty (uncommitted) after pull — pull() must never commit it"
```

No production code changes. `pull()` takes no `now` parameter and was never implicated by must-fix #1 (confirmed again this pass) — this is purely a test-fidelity fix.

**Explicitly deferred, unchanged from last round (review notes, not must-fix):** `session_work.py:196`'s no-lower-bound future-timestamp check, `code_sync.py:339`'s `repo_id`-from-first-file-only lookup, `code_sync.py:343`'s silent fail-open with no `_log` call, and `session_work.py:181`'s mutate-on-read in `prune()`. None are in the review's `fix_these`, and `test_live_edits_for_treats_a_future_timestamp_as_live_not_stale` already encodes the clock-skew behavior as intentional. Expanding scope to these now, unasked, risks an unreviewed behavior change in a file that's otherwise done.

**One correction for whoever writes the completion summary this time:** the last design doc's own "Implementation Complete" section was flagged by review for claiming the full suite was "running in background" (unverified) and that deferred notes were "documented in ADRs/docstrings" (false — they're only in this doc). Don't repeat that: run the full suite to completion and report real pass/fail counts, and don't claim documentation that doesn't exist.

## Decisions

None requiring Gil's input. The one change is a direct, mechanical fix for the single must-fix the review named; deferring the four source-level notes is a re-affirmation of last round's already-accepted judgment call, not a new fork.

## Tests to write first

From the ticket's "How we'll try to break it" (all three already covered by tests currently in this worktree, re-verified against current code):
1. Builder crashes holding the lease → `test_push_proceeds_once_a_held_lease_goes_stale` (already rewritten last round to call `push()` and assert real git state — confirmed correct on this read).
2. Two sessions editing at once → `test_push_defers_when_either_of_two_concurrent_sessions_holds_the_lease` + `test_live_edits_for_returns_every_live_session_not_just_one` (both already correct).
3. Sync on the other Mac pulling mid-edit → **the one test being rewritten this round**, `test_pull_merges_a_remote_commit_while_local_dirty_content_survives_under_a_live_edit_lease`. This is the regression test for the must-fix: it fails if `pull()`'s stash/merge/pop path is ever broken (it would previously have passed regardless, since nothing forced a merge).

Already-correct coverage kept as-is (re-verified, no change needed): `test_push_defers_and_commits_nothing_when_a_live_session_is_mid_edit_on_a_dirty_file`, `test_push_commits_and_pushes_dirty_files_when_no_lease_is_held`, the three malformed-state tests (`missing`/`corrupt`/`wrong_shape`), `test_live_edit_lease_returns_none_for_no_changed_files`, `test_live_edit_lease_handles_a_large_changed_file_list` (positive case on a 300-file list), `test_push_defers_idempotently_across_repeated_calls_while_lease_holds`, `test_push_proceeds_when_sessions_state_is_unreadable_due_to_permissions` (root-skip guarded), `test_live_edits_for_treats_a_future_timestamp_as_live_not_stale`, `test_live_edits_for_ignores_old_crashed_session_entries`.

Verification: delete the old `test_pull_is_unaffected_by_a_live_edit_lease_on_a_dirty_file`, confirm the new test fails against the current (unpatched-for-this-round) test body — trivially true since the old version is being replaced — then run `~/.agents/venv/bin/python -m pytest lib/tests/test_code_sync_live_edit_lease.py lib/tests/test_code_sync_push.py lib/tests/test_code_sync_pull.py lib/tests/test_session_work.py -v` to completion (not backgrounded), plus the full `lib/tests/` suite once, reporting actual counts. `lib/commit_check.py` (ADR 0063) gates the test-file change against itself, with no production file touched this round.