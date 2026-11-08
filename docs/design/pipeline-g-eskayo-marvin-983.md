## North-star fit

**Reuses before adding anything:**
- `lib/box_trial.py`'s own `quarantine_command()` is the existing pattern for "no tool allowlist — the dispatch `need` tag is the only gate." `security_command()` just needs to drop its `SECURITY_TOOLS` check and match that already-established shape; no new mechanism.
- `@pytest.mark.macos_only("why")` (`lib/tool_requirements.py`, #1117, already used in `lib/tests/test_memory_guard.py`, `test_tool_requirements.py`, `test_macos_evidence.py`) is the one repo-wide marker for Mac-only tests. The one real merge conflict with `main` (`brain-map/scripts/test_generate.py`) is exactly this branch's ad hoc `skipif(not Path("/usr/bin/plutil").exists())` colliding with main's adoption of that marker (`dd80f756`) — resolved by taking main's convention, not inventing a third way.
- The reply itself reuses the exact template a prior "Act on owner decisions" PR used (#935's addressed comment: states what's already built, what changed, conflict-with-main resolution + commit, follow-up ticket if any, ending in `<!-- marvin:decisions-addressed -->`) and `lib/owner_decisions.py`'s `ADDRESSED_MARKER` contract.

**Why this is the simplest sufficient approach:** one decision (`retrieval-graph`) requires zero code — `retrieval_command()` already runs `graphify update .` first, exactly as chosen. The other (`security-tools`) is a two-line deletion (the `SECURITY_TOOLS` frozenset and its `if argv[0] not in SECURITY_TOOLS` check), not a redesign. The only non-trivial step is a one-hunk merge-conflict resolution, required because the branch (`ticket/932-box-trial`, tip `7b12dc71`) is stale against current `main` (`cc830481`) and GitHub reports it `CONFLICTING`.

**Checked, not assumed:** I diffed both branches against their merge-base (`5b93e994`) rather than trusting the PR's three stale "conflicts with main" bot comments. Two of those comments (`lib/tests/test_dispatch_fallback.py`) are now stale — main's changes there (`#1139`/`#992` signal-handling tests) are a clean append at EOF with zero overlap with this branch's mid-file `stdin` plumbing changes; no merge-tree conflict remains. The third (`brain-map/scripts/test_generate.py`) is real and current: both sides touch the exact same decorator line. No recorded decision (CONTEXT.md "Third node" section, ADR 0069) mandates a closed security-tool list — it only scopes the box as "security/network-tools host," so dropping the list doesn't contradict anything on record.

**Tokens:** small, bounded spend now (one deletion, one merge hunk, one reply) prevents the open-ended cost of this sitting stuck — it's the reason #983 exists at all (the 4-hour grace-period auto-file in `lib/owner_decisions.py`). Compounding leverage: unblocking #941 also resolves whatever follow-up scan would otherwise keep re-filing against it.

**User capability:** this is pure pipeline housekeeping — the owner already made both calls; MARVIN's job is mechanical execution and a clear reply, not a design decision. No north star argues against doing this one autonomously.

**No new Decisions needed.** Both `security-tools` and `retrieval-graph` are already unambiguous owner choices with empty notes (no contradiction to flag), and the merge-conflict resolution has only one correct answer (adopt the repo's already-standard marker) — nothing to hand back to Gil.

## Tests to write first

In `lib/tests/test_box_trial.py` (TDD: these fail against today's code, pass after the edit):

1. **`SECURITY_TOOLS` is gone** — `assert not hasattr(bt, "SECURITY_TOOLS")`, driving the deletion itself.
2. **Any tool name is now accepted** — `bt.security_command(argv)` no longer raises for `["claude", "-p", "build #12"]`, `["bash", "-c", "x"]`, `["python3", "x.py"]`, `["hydra", "-l", "root", "10.0.0.5"]`. This *replaces* `test_a_ticket_build_cannot_ride_in_as_a_security_tool`, which currently asserts the opposite — the owner's decision deliberately removes that guarantee, so the old test's premise is wrong now, not just its code.
3. **Misuse: empty command is still refused** — `bt.security_command([])` still raises `ValueError` (the one guard that must survive).
4. **Injection still can't ride the quoting** — `bt.security_command(["sqlmap", "a.example; rm -rf ~"])` still returns one shell-quoted token (use a tool *outside* the old list, to prove quoting is independent of any allowlist).
5. **Bad/huge input doesn't crash or truncate** — `bt.security_command` with ~1000 arguments still returns one correctly-quoted string.
6. **Dependency/CLI path fix** — `test_the_cli_says_where_it_ran_and_refuses_with_exit_2` currently calls `bt.main(["security", "--", "claude", "-p", "x"])` and relies on the old allowlist to get a clean, non-dispatching `ValueError`. Once the list is gone this would instead attempt a real dispatch. Fix it to assert on `bt.main(["security"])` (no tool at all), preserving CLI-level refusal coverage without a hidden dependency on the removed list. This is exactly the kind of ripple "verify fails when code changes without a test changing" exists to catch.
7. **Regression** — `test_each_trial_type_goes_with_its_tag_and_limit` (unchanged) must keep passing: `security` still maps to `need="security", timeout=600`.
8. **Merge-conflict resolution regression** — after resolving `brain-map/scripts/test_generate.py` onto `@pytest.mark.macos_only("plutil reads the plist that Python's parser refuses")`, the existing `lib/tests/test_tool_requirements.py` suite (`test_mac_only_tests_use_the_one_marker_not_their_own_platform_skips`, the marker-mechanics tests) must still pass — proves the merge picked main's side correctly rather than just deleting the skip.

No new tests needed for `retrieval-graph` — nothing in `retrieval_command()` changes.

## Task List

1. Create a local branch tracking `origin/ticket/932-box-trial` (tip `7b12dc71`) in a dedicated worktree.
2. Merge current `origin/main` into it; resolve the single real conflict in `brain-map/scripts/test_generate.py` by replacing the ad hoc `@pytest.mark.skipif(not Path("/usr/bin/plutil").exists(), ...)` with main's `@pytest.mark.macos_only("plutil reads the plist that Python's parser refuses")`.
3. Write/modify the eight tests above in `lib/tests/test_box_trial.py` first (red).
4. Delete `SECURITY_TOOLS` and the `if argv[0] not in SECURITY_TOOLS` check from `security_command()` in `lib/box_trial.py`; update its module docstring/comment that currently explains the closed-list rationale, since that rationale no longer applies.
5. Run `lib/tests/test_box_trial.py`, `lib/tests/test_dispatch_fallback.py`, and `brain-map/scripts/test_generate.py` (plus `lib/tests/test_tool_requirements.py`) locally; confirm green.
6. Commit with a message referencing both decisions and #941/#983; push to `ticket/932-box-trial`.
7. Post a reply comment on PR #941 (not a new "## Decisions" heading — this only reports) stating: `security-tools` built (list dropped, commit SHA); `retrieval-graph` already matched the chosen option, no change needed; the stray main-conflict found and resolved (merge commit SHA); no screenshots in this PR to retake (backend/CLI only — nothing visual changed); ending with `<!-- marvin:decisions-addressed -->`.
8. `marvin-show` the diff/PR to Gil rather than leaving it as a bare commit reference.